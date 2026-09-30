"""Separate student/admin submission contracts; live student results stay opaque."""
from contextlib import contextmanager
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
        raise HTTPException(503, {'code': 'storage_unavailable', 'message': 'Acceptance unavailable; retry with the same key'}) from exc


def query(lab_id: UUID):
    return sa.select(store.submissions, identity.accounts.c.roll_number, identity.accounts.c.name, store.jobs.c.state, store.jobs.c.attempt_count,
        store.runs.c.verdict, store.runs.c.compiler_feedback, store.runs.c.compiler_truncated,
        store.runs.c.passed, store.runs.c.total, store.runs.c.score_numerator, store.runs.c.score_denominator,
        store.attempts.c.fault).select_from(store.submissions.join(store.jobs,
        store.jobs.c.submission_id == store.submissions.c.id).join(identity.accounts,
        identity.accounts.c.id == store.submissions.c.account_id).outerjoin(store.runs,
        store.runs.c.id == store.jobs.c.attempt_id).outerjoin(store.attempts,
        store.attempts.c.id == store.jobs.c.attempt_id)).where(store.submissions.c.lab_id == lab_id)


def output(row: dict, feedback: str, *, admin_view: bool = False) -> dict:
    status = {'queued': 'Queued', 'judging': 'Judging', 'delayed': 'Judging delayed',
              'complete': 'Passed' if row['verdict'] == 'AC' else 'Compile error' if row['verdict'] == 'CE' else 'Failed'}[row['state']]
    result = {key: row[key] for key in SubmissionOutput.model_fields if key not in ('status', 'compiler_feedback', 'compiler_truncated')}
    result.update(status=status, compiler_feedback=None, compiler_truncated=False)
    if row['verdict'] == 'CE' and (admin_view or feedback != 'none'):
        diagnostic = row['compiler_feedback'] or ''
        short = not admin_view and feedback == 'short'
        result.update(compiler_feedback='\n'.join(diagnostic.splitlines()[:20]) if short else diagnostic,
                      compiler_truncated=bool(row['compiler_truncated'] or short and len(diagnostic.splitlines()) > 20))
    if admin_view:
        result.update({key: row[key] for key in AdminSubmission.model_fields if key not in SubmissionOutput.model_fields})
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
            selection = selection.where(store.submissions.c.revision_id == revision_id)
        rows = conn.execute(selection.order_by(store.submissions.c.accepted_at.desc(), store.submissions.c.id).offset(offset).limit(100)).mappings()
        return [output(row, lab['compiler_feedback']) for row in rows]


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
                  account_id: UUID | None = None, revision_id: UUID | None = None):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        selection = query(lab_id)
        if account_id:
            selection = selection.where(store.submissions.c.account_id == account_id)
        if revision_id:
            selection = selection.where(store.submissions.c.revision_id == revision_id)
        rows = conn.execute(selection.order_by(store.submissions.c.accepted_at.desc(), store.submissions.c.id)
                            .offset(offset).limit(100)).mappings()
        return [output(row, 'full', admin_view=True) for row in rows]


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
def admin_detail(lab_id: UUID, submission_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        row = conn.execute(query(lab_id).where(store.submissions.c.id == submission_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Submission not found')
        result = output(row, 'full', admin_view=True)
        result['source'] = files.read(row).decode('utf-8', errors='replace')
        case_rows = conn.execute(sa.select(store.cases).join(store.runs, store.runs.c.id == store.cases.c.run_id)
            .join(store.jobs, store.jobs.c.attempt_id == store.runs.c.id)
            .where(store.jobs.c.submission_id == submission_id).order_by(store.cases.c.number)).mappings().all()
        inputs = []
        if case_rows:
            cases_key = conn.execute(sa.select(tasks.revisions.c.cases_key)
                .where(tasks.revisions.c.id == row['revision_id'])).scalar_one()
            inputs = tasks.load_cases(cases_key)
        result['cases'] = [{**case, 'stdin': inputs[case['number'] - 1][0].decode('utf-8', errors='replace'),
                           'stdout': case['stdout'].decode('utf-8', errors='replace'),
                           'stderr': case['stderr'].decode('utf-8', errors='replace')} for case in case_rows]
        return result
