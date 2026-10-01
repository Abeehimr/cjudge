"""Separate student/admin submission contracts; live student results stay opaque."""
from contextlib import contextmanager
import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from cjudge import identity, labs, tasks, submissions as store
from cjudge.identity.api import StrictModel, admin, admin_write, no_store
from cjudge.labs.api import student, student_write, student_access, ReasonInput
from cjudge.labs.binding import client_ip
from cjudge.submissions import service, files
from cjudge.submissions import review
from cjudge.tasks.api import bounded_body, json_input

student_router = APIRouter(prefix='/api/labs/{lab_id}/submissions', dependencies=[Depends(student), Depends(no_store)])
admin_router = APIRouter(prefix='/api/admin/labs/{lab_id}/submissions', dependencies=[Depends(admin), Depends(no_store)])


class SubmissionOutput(StrictModel):
    id: UUID
    revision_id: UUID
    filename: str
    size: int
    accepted_at: datetime
    status: str
    compiler_feedback: str | None = None
    compiler_truncated: bool = False
    best_for_review: bool = False
    deleted_at: datetime | None = None
    delete_reason: str | None = None


class AdminSubmission(SubmissionOutput):
    account_id: UUID
    roll_number: str
    name: str
    client_ip: str
    client_mac: str | None
    mac_source: str | None
    mac_observed_at: datetime | None
    attempt_count: int
    fault: str | None
    passed: int | None
    total: int | None
    score_numerator: str | None
    score_denominator: str | None
    accepted_revision_id: UUID
    result_revision_id: UUID | None
    run_id: UUID | None
    rejudge_status: str | None
    marks: str | None
    ip_changed: bool = False
    mac_changed: bool = False


@contextmanager
def transaction():
    try:
        with identity.engine().begin() as conn:
            yield conn
    except service.SubmissionError as exc:
        raise HTTPException(exc.status, {'code': exc.code, 'message': str(exc),
            'retry_at': exc.retry_at.isoformat() if exc.retry_at else None}) from exc
    except labs.LabError as exc:
        raise HTTPException(exc.status, {'code': 'lab_access', 'message': str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, {'code': 'invalid_source', 'message': str(exc)}) from exc
    except (OSError, SQLAlchemyError) as exc:
        logging.getLogger(__name__).warning('Transaction unavailable (%s)', type(exc).__name__)
        raise HTTPException(503, {'code': 'storage_unavailable', 'message': 'Acceptance unavailable; retry with the same key'}) from exc


def query(lab_id: UUID):
    assigned_revision = tasks.revisions.alias('assigned_revision')
    assigned = sa.select(labs.assignments.c.revision_id).join(assigned_revision,
        assigned_revision.c.id == labs.assignments.c.revision_id).where(labs.assignments.c.lab_id == lab_id,
        assigned_revision.c.task_id == tasks.revisions.c.task_id).correlate(tasks.revisions).scalar_subquery()
    return sa.select(store.submissions, assigned.label('current_revision_id'), tasks.revisions.c.task_id,
        store.reviews.c.run_id, store.reviews.c.deleted_at, store.reviews.c.delete_reason,
        store.jobs.c.kind, store.jobs.c.batch_id,
        store.runs.c.revision_id.label('result_revision_id'), identity.accounts.c.roll_number, identity.accounts.c.name, store.jobs.c.state, store.jobs.c.attempt_count,
        store.runs.c.verdict, store.runs.c.compiler_feedback, store.runs.c.compiler_truncated,
        store.runs.c.passed, store.runs.c.total, store.runs.c.score_numerator, store.runs.c.score_denominator,
        store.attempts.c.fault).select_from(store.submissions.join(store.jobs,
        store.jobs.c.submission_id == store.submissions.c.id).join(identity.accounts,
        identity.accounts.c.id == store.submissions.c.account_id).join(tasks.revisions,
        tasks.revisions.c.id == store.submissions.c.revision_id).outerjoin(store.reviews,
        store.reviews.c.submission_id == store.submissions.c.id).outerjoin(store.runs,
        store.runs.c.id == store.reviews.c.run_id).outerjoin(store.attempts,
        store.attempts.c.id == store.jobs.c.attempt_id)).where(store.submissions.c.lab_id == lab_id)


def output(row: dict, feedback: str, *, admin_view: bool = False) -> dict:
    status = ('Passed' if row['verdict'] == 'AC' else 'Compile error' if row['verdict'] == 'CE' else 'Failed') if row['run_id'] else {
        'queued': 'Queued', 'judging': 'Judging', 'delayed': 'Judging delayed', 'complete': 'Judging'}[row['state']]
    result = {key: row[key] for key in SubmissionOutput.model_fields if key not in ('status', 'compiler_feedback', 'compiler_truncated', 'best_for_review')}
    result.update(status=status, compiler_feedback=None, compiler_truncated=False, best_for_review=False)
    result['revision_id'] = row['current_revision_id'] or row['revision_id']
    if row['verdict'] == 'CE' and (admin_view or feedback != 'none'):
        diagnostic = row['compiler_feedback'] or ''
        short = not admin_view and feedback == 'short'
        result.update(compiler_feedback='\n'.join(diagnostic.splitlines()[:20]) if short else diagnostic,
                      compiler_truncated=bool(row['compiler_truncated'] or short and len(diagnostic.splitlines()) > 20))
    if admin_view:
        computed = {'accepted_revision_id', 'rejudge_status', 'ip_changed', 'mac_changed', 'marks'}
        result.update({key: row[key] for key in AdminSubmission.model_fields if key not in SubmissionOutput.model_fields and key not in computed})
        result.update(accepted_revision_id=row['revision_id'], rejudge_status=(
            'Staged' if row['batch_id'] and row['state'] == 'complete' else row['state'])
            if row['kind'] != 'initial' and (row['state'] != 'complete' or row['batch_id']) else None)
        result['marks'] = review.displayed(review.exact(row)) if row['run_id'] else None
    return result


@student_router.post('', response_model=SubmissionOutput)
async def upload(lab_id: UUID, request: Request, response: Response,
                 revision_id: UUID, filename: str = Query(max_length=160),
                 idempotency_key: UUID = Header(), account: dict = Depends(student_write)):
    if request.headers.get('content-type', '').split(';')[0] != 'application/octet-stream':
        raise HTTPException(415, 'Raw C source required')
    source = await bounded_body(request, files.SOURCE_BYTES)
    def create():
        with transaction() as conn:
            lab, enrollment, _ = student_access(conn, lab_id, account, request)
            row, created = service.accept(conn, lab, enrollment, revision_id, idempotency_key, filename, source, client_ip(request))
            result = conn.execute(query(lab_id).where(store.submissions.c.id == row['id'])).mappings().one()
            return output(result, lab['compiler_feedback']), created
    value, created = await run_in_threadpool(create)
    response.status_code = 201 if created else 200
    return value


@student_router.get('', response_model=list[SubmissionOutput])
def history(lab_id: UUID, request: Request, offset: int = Query(default=0, ge=0),
            revision_id: UUID | None = None, account: dict = Depends(student)):
    with transaction() as conn:
        lab, _, _ = student_access(conn, lab_id, account, request)
        selection = query(lab_id).where(store.submissions.c.account_id == account['id'])
        if revision_id:
            selection = selection.where(tasks.revisions.c.task_id == sa.select(tasks.revisions.c.task_id)
                .where(tasks.revisions.c.id == revision_id).scalar_subquery())
        rows = conn.execute(selection.order_by(store.submissions.c.accepted_at.desc(), store.submissions.c.id).offset(offset).limit(100)).mappings()
        best = review.best_for_review(conn, lab_id, account['id']) if lab['first_released_at'] and lab['reveal_results'] else set()
        return [dict(output(row, lab['compiler_feedback']), best_for_review=row['id'] in best) for row in rows]


@student_router.get('/{submission_id}', response_model=SubmissionOutput)
def detail(lab_id: UUID, submission_id: UUID, request: Request, account: dict = Depends(student)):
    with transaction() as conn:
        lab, _, _ = student_access(conn, lab_id, account, request)
        row = conn.execute(query(lab_id).where(store.submissions.c.id == submission_id,
            store.submissions.c.account_id == account['id'])).mappings().first()
        if not row:
            raise HTTPException(404, 'Submission not found')
        return output(row, lab['compiler_feedback'])


@admin_router.get('', response_model=list[AdminSubmission])
def admin_history(lab_id: UUID, offset: int = Query(default=0, ge=0),
                  account_id: UUID | None = None, revision_id: UUID | None = None, order: Literal['latest', 'best'] = 'latest'):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        selection = query(lab_id)
        if account_id:
            selection = selection.where(store.submissions.c.account_id == account_id)
        if revision_id:
            selection = selection.where(tasks.revisions.c.task_id == sa.select(tasks.revisions.c.task_id)
                .where(tasks.revisions.c.id == revision_id).scalar_subquery())
        if order == 'best':
            # ponytail: exact rational sorting loads filtered history; move ordering
            # into PostgreSQL if per-lab histories outgrow server memory.
            rows = list(conn.execute(selection).mappings())
            rows.sort(key=lambda row: (2 if row['deleted_at'] else 1 if row['run_id'] is None else 0,
                -review.exact(row) if row['run_id'] else 0, row['accepted_at'], str(row['id'])))
            rows = rows[offset:offset + 100]
        else:
            rows = conn.execute(selection.order_by(store.submissions.c.accepted_at.desc(), store.submissions.c.id)
                                .offset(offset).limit(100)).mappings()
        flags = review.network_flags(conn, lab_id)
        best = review.best_for_review(conn, lab_id, account_id)
        return [dict(output(row, 'full', admin_view=True), best_for_review=row['id'] in best, **flags.get(row['account_id'], {})) for row in rows]


@admin_router.get('/{submission_id}/source')
def source(lab_id: UUID, submission_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        row = conn.execute(sa.select(store.submissions).where(store.submissions.c.lab_id == lab_id,
            store.submissions.c.id == submission_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Submission not found')
        return Response(files.read(row), media_type='application/octet-stream', headers={'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'attachment; filename="{submission_id}.c"'})


@admin_router.get('/{submission_id}')
def admin_detail(lab_id: UUID, submission_id: UUID, run_id: UUID | None = None):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        row = conn.execute(query(lab_id).where(store.submissions.c.id == submission_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Submission not found')
        official_run_id = row['run_id']
        if run_id:
            selected = conn.execute(sa.select(store.runs).where(store.runs.c.id == run_id,
                store.runs.c.submission_id == submission_id)).mappings().first()
            if not selected:
                raise HTTPException(404, 'Judge run not found')
            row = dict(row) | {key: selected[key] for key in ('verdict', 'compiler_feedback', 'compiler_truncated',
                'passed', 'total', 'score_numerator', 'score_denominator')}
            row.update(run_id=run_id, result_revision_id=selected['revision_id'])
        result = output(row, 'full', admin_view=True)
        result['official_run_id'] = official_run_id
        result['history'] = [dict(item) for item in conn.execute(sa.select(store.runs.c.id, store.runs.c.revision_id,
            store.runs.c.verdict, store.runs.c.finished_at).where(store.runs.c.submission_id == submission_id)
            .order_by(store.runs.c.finished_at.desc())).mappings()]
        result['attempts'] = [dict(item) for item in conn.execute(sa.select(store.attempts.c.id,
            store.attempts.c.started_at, store.attempts.c.finished_at, store.attempts.c.outcome, store.attempts.c.fault)
            .where(store.attempts.c.submission_id == submission_id).order_by(store.attempts.c.started_at.desc())).mappings()]
        result.update(review.network_flags(conn, lab_id).get(row['account_id'], {}))
        result['source'] = files.read(row).decode('utf-8', errors='replace')
        result['cases'] = case_details(conn, row['run_id'], row['result_revision_id'], admin_view=True)
        return result


def preview(data: bytes) -> tuple[str, bool]:
    return data[:65536].decode('utf-8', errors='replace'), len(data) > 65536


def case_details(conn: sa.Connection, run_id: UUID | None, revision_id: UUID | None, *, admin_view: bool = False) -> list[dict]:
    case_rows = conn.execute(sa.select(store.cases).where(store.cases.c.run_id == run_id)
        .order_by(store.cases.c.number)).mappings().all()
    pairs = []
    if case_rows:
        key = conn.execute(sa.select(tasks.revisions.c.cases_key).where(tasks.revisions.c.id == revision_id)).scalar_one()
        pairs = tasks.load_cases(key)
    result = []
    for case in case_rows:
        item = {key: case[key] for key in ('number', 'verdict', 'cpu_seconds', 'wall_seconds', 'memory_kib')}
        disclosed = admin_view or case['verdict'] != 'AC'
        for part, data in (('stdin', pairs[case['number'] - 1][0]), ('expected', pairs[case['number'] - 1][1]),
                           ('stdout', case['stdout']), ('stderr', case['stderr'])):
            value, truncated = preview(data)
            item[part] = value if disclosed else None
            item[part + '_truncated'] = bool(disclosed and (truncated or case.get(part + '_truncated', False)))
        result.append(item)
    return result


class ReleasedCase(StrictModel):
    number: int
    verdict: str
    cpu_seconds: float
    wall_seconds: float
    memory_kib: int
    stdin: str | None
    expected: str | None
    stdout: str | None
    stderr: str | None
    stdin_truncated: bool
    expected_truncated: bool
    stdout_truncated: bool
    stderr_truncated: bool


class ReleasedRun(StrictModel):
    id: UUID
    revision_id: UUID
    verdict: str
    finished_at: datetime


class ReleasedSubmission(SubmissionOutput):
    source: str
    official_run_id: UUID | None
    run_id: UUID | None
    result_revision_id: UUID | None
    marks: str | None
    official_marks: str | None
    passed: int | None
    total: int | None
    grading_pending: bool
    history: list[ReleasedRun]
    cases: list[ReleasedCase]


def released_row(conn: sa.Connection, lab_id: UUID, submission_id: UUID, request: Request, account: dict) -> tuple[dict, dict]:
    from cjudge.labs.release import visible
    lab, _, _ = student_access(conn, lab_id, account, request)
    row = conn.execute(query(lab_id).where(store.submissions.c.id == submission_id,
        store.submissions.c.account_id == account['id'])).mappings().first()
    if not row:
        raise HTTPException(404, 'Submission not found')
    visible(lab)
    return lab, dict(row)


@student_router.get('/{submission_id}/details', response_model=ReleasedSubmission)
def released_detail(lab_id: UUID, submission_id: UUID, request: Request, run_id: UUID | None = None,
                    account: dict = Depends(student)):
    with transaction() as conn:
        lab, row = released_row(conn, lab_id, submission_id, request, account)
        official_run_id = row['run_id']
        official_marks = review.displayed(review.exact(row)) if official_run_id else None
        if run_id:
            selected = conn.execute(sa.select(store.runs).where(store.runs.c.id == run_id,
                store.runs.c.submission_id == submission_id)).mappings().first()
            if not selected:
                raise HTTPException(404, 'Judge run not found')
            row.update({key: selected[key] for key in ('verdict', 'compiler_feedback', 'compiler_truncated',
                'passed', 'total', 'score_numerator', 'score_denominator')})
            row.update(run_id=run_id, result_revision_id=selected['revision_id'])
        return output(row, 'full') | dict(source=files.read(row).decode('utf-8', errors='replace'),
            official_run_id=official_run_id, official_marks=official_marks, run_id=row['run_id'],
            result_revision_id=row['result_revision_id'], marks=review.displayed(review.exact(row)) if row['run_id'] else None,
            passed=row['passed'], total=row['total'], grading_pending=row['state'] != 'complete' or bool(row['batch_id']),
            history=[dict(item) for item in conn.execute(sa.select(store.runs.c.id, store.runs.c.revision_id,
                store.runs.c.verdict, store.runs.c.finished_at).where(store.runs.c.submission_id == submission_id)
                .order_by(store.runs.c.finished_at.desc())).mappings()],
            cases=case_details(conn, row['run_id'], row['result_revision_id']))


@student_router.get('/{submission_id}/source')
def released_source(lab_id: UUID, submission_id: UUID, request: Request, account: dict = Depends(student)):
    with transaction() as conn:
        _, row = released_row(conn, lab_id, submission_id, request, account)
        return Response(files.read(row), media_type='application/octet-stream', headers={'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'attachment; filename="{submission_id}.c"'})
