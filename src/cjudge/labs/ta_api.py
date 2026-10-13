"""TA access is scoped to active assignments and rechecked inside every transaction."""
import asyncio
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from cjudge import identity, labs, submissions as submission_store
from cjudge.events import hub
from cjudge.identity.api import COOKIE, StrictModel, current, no_store, same_origin, write_guard
from cjudge.labs import binding
from cjudge.labs.api import FreezeInput, ReasonInput, transaction, summary
from cjudge.submissions import api as submission_api, review

router = APIRouter(prefix='/api/ta', dependencies=[Depends(no_store)])


def ta(account: dict = Depends(current)) -> dict:
    if account['role'] != 'ta':
        raise HTTPException(403, 'TA access required')
    return account


def ta_write(account: dict = Depends(write_guard)) -> dict:
    if account['role'] != 'ta':
        raise HTTPException(403, 'TA access required')
    return account


def access(conn: sa.Connection, request: Request, account: dict, lab_id: UUID | None = None,
           *, write: bool = False) -> dict | None:
    """Account → lab → assignment lock order also used by admin assignment removal."""
    row = conn.execute(sa.select(identity.accounts.c.active, identity.accounts.c.role)
        .where(identity.accounts.c.id == account['id']).with_for_update(read=True)).first()
    session = conn.execute(sa.select(identity.sessions.c.expires_at).where(
        identity.sessions.c.token_hash == identity.token_digest(request.cookies.get(COOKIE, '')),
        identity.sessions.c.account_id == account['id'], identity.sessions.c.expires_at > identity.now())).scalar_one_or_none()
    if not row or not row.active or row.role != 'ta' or session is None:
        raise HTTPException(401, 'Login required')
    if lab_id is None:
        return None
    lab = labs.find(conn, lab_id, shared=not write)
    assigned = conn.execute(sa.select(labs.ta_assignments.c.ta_id).where(
        labs.ta_assignments.c.lab_id == lab_id, labs.ta_assignments.c.ta_id == account['id'])
        .with_for_update(read=True)).first()
    if not assigned:
        raise HTTPException(403, 'Lab assignment required')
    if write:
        labs.editable(lab)
    return lab


class TALab(StrictModel):
    id: UUID
    title: str
    phase: str
    starts_at: datetime | None
    ends_at: datetime | None
    server_time: datetime
    results_visible: bool
    archived: bool


def lab_output(conn: sa.Connection, lab: dict) -> dict:
    return summary(conn, lab) | {'results_visible': bool(lab['first_released_at'] and lab['reveal_results']),
        'archived': bool(lab['archived_at'])}


@router.get('/labs', response_model=list[TALab])
def assigned(request: Request, account: dict = Depends(ta)) -> list[dict]:
    with transaction() as conn:
        access(conn, request, account)
        rows = conn.execute(sa.select(labs.labs).join(labs.ta_assignments,
            labs.ta_assignments.c.lab_id == labs.labs.c.id).where(labs.ta_assignments.c.ta_id == account['id'])
            .order_by(labs.labs.c.created_at.desc()).limit(100)).mappings()
        return [lab_output(conn, dict(row)) for row in rows]


@router.get('/labs/{lab_id}', response_model=TALab)
def lab_detail(lab_id: UUID, request: Request, account: dict = Depends(ta)) -> dict:
    with transaction() as conn:
        return lab_output(conn, access(conn, request, account, lab_id))


class StudentStatus(StrictModel):
    id: UUID
    roll_number: str
    name: str
    frozen: bool
    freeze_reason: str | None
    frozen_by_name: str | None
    cancelled: bool
    cancel_reason: str | None
    cancelled_by_name: str | None
    bound: bool
    ip_changed: bool
    submission_count: int
    last_submission_at: datetime | None


def student_status(conn: sa.Connection, lab_id: UUID, student_id: UUID | None = None,
                   search: str = '') -> list[dict]:
    frozen_actor = identity.accounts.alias('frozen_actor')
    cancelled_actor = identity.accounts.alias('cancelled_actor')
    counts = sa.select(submission_store.submissions.c.account_id,
        sa.func.count().label('submission_count'),
        sa.func.max(submission_store.submissions.c.accepted_at).label('last_submission_at')).where(
        submission_store.submissions.c.lab_id == lab_id).group_by(submission_store.submissions.c.account_id).subquery()
    query = sa.select(identity.accounts.c.id, identity.accounts.c.roll_number, identity.accounts.c.name,
        labs.enrollments.c.frozen, labs.enrollments.c.freeze_reason, frozen_actor.c.name.label('frozen_by_name'),
        labs.enrollments.c.cancelled, labs.enrollments.c.cancel_reason,
        cancelled_actor.c.name.label('cancelled_by_name'),
        labs.enrollments.c.binding_hash.is_not(None).label('bound'), labs.enrollments.c.ip_changed,
        sa.func.coalesce(counts.c.submission_count, 0).label('submission_count'),
        counts.c.last_submission_at).join(labs.enrollments,
        labs.enrollments.c.account_id == identity.accounts.c.id).outerjoin(frozen_actor,
        frozen_actor.c.id == labs.enrollments.c.frozen_by).outerjoin(cancelled_actor,
        cancelled_actor.c.id == labs.enrollments.c.cancelled_by).outerjoin(counts,
        counts.c.account_id == identity.accounts.c.id).where(labs.enrollments.c.lab_id == lab_id)
    if student_id:
        query = query.where(identity.accounts.c.id == student_id)
    else:
        query = query.where(sa.or_(identity.accounts.c.roll_number.ilike(f'%{search}%'),
            identity.accounts.c.name.ilike(f'%{search}%')))
    return [dict(row) for row in conn.execute(query.order_by(identity.accounts.c.roll_number)
        .limit(1 if student_id else 50)).mappings()]


@router.get('/labs/{lab_id}/students', response_model=list[StudentStatus])
def search_students(lab_id: UUID, request: Request, search: str = Query(default='', max_length=64),
                    account: dict = Depends(ta)) -> list[dict]:
    with transaction() as conn:
        access(conn, request, account, lab_id)
        return student_status(conn, lab_id, search=search.strip()) if search.strip() else []


@router.get('/labs/{lab_id}/students/{student_id}', response_model=StudentStatus)
def student_detail(lab_id: UUID, student_id: UUID, request: Request, account: dict = Depends(ta)) -> dict:
    with transaction() as conn:
        access(conn, request, account, lab_id)
        rows = student_status(conn, lab_id, student_id=student_id)
        if not rows:
            raise HTTPException(404, 'Student not found')
        return rows[0]


@router.post('/labs/{lab_id}/students/{student_id}/freeze', status_code=204)
def freeze(lab_id: UUID, student_id: UUID, body: FreezeInput, request: Request,
           account: dict = Depends(ta_write)) -> None:
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    with transaction() as conn:
        lab = access(conn, request, account, lab_id, write=True)
        labs.freeze(conn, lab, student_id, body.frozen, body.reason.strip(), account['id'])


class TACancellationInput(ReasonInput):
    cancelled: bool


@router.put('/labs/{lab_id}/students/{student_id}/cancellation', status_code=204)
def cancel(lab_id: UUID, student_id: UUID, body: TACancellationInput, request: Request,
           account: dict = Depends(ta_write)) -> None:
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    with transaction() as conn:
        lab = access(conn, request, account, lab_id, write=True)
        labs.set_cancelled(conn, lab, student_id, body.cancelled, body.reason.strip(), account['id'])


@router.post('/labs/{lab_id}/students/{student_id}/release')
def release(lab_id: UUID, student_id: UUID, body: ReasonInput, request: Request,
            account: dict = Depends(ta_write)) -> dict:
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    with transaction() as conn:
        lab = access(conn, request, account, lab_id, write=True)
        result = binding.release(conn, lab, student_id, body.reason.strip(), account['id'])
        return result


@router.post('/labs/{lab_id}/students/{student_id}/password')
def reveal_password(lab_id: UUID, student_id: UUID, request: Request,
                    account: dict = Depends(ta_write)) -> dict:
    with transaction() as conn:
        access(conn, request, account, lab_id, write=True)
        cipher = identity.checked_cipher(conn)
        row = conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number,
            identity.accounts.c.name, identity.accounts.c.active, identity.accounts.c.encrypted_password)
            .where(identity.accounts.c.id == student_id, identity.accounts.c.role == 'student')
            .with_for_update(read=True)).mappings().first()
        if not row:
            raise HTTPException(404, 'Student not found')
        if not row['active']:
            raise HTTPException(409, 'Student account inactive')
        labs.enrollment(conn, lab_id, student_id)
        identity.audit(conn, 'ta_student_password_accessed', account['id'], student_id,
            detail={'lab_id': str(lab_id)})
        try:
            password = cipher.decrypt(row['encrypted_password']).decode()
        except (InvalidToken, UnicodeError) as exc:
            raise RuntimeError('Credentials unavailable') from exc
        return {'id': row['id'], 'roll_number': row['roll_number'], 'name': row['name'],
            'password': password}


class TASubmission(submission_api.SubmissionOutput):
    marks: str | None
    maximum_marks: str | None
    passed: int | None
    total: int | None


@router.get('/labs/{lab_id}/students/{student_id}/marks', response_model=list[dict])
def student_marks(lab_id: UUID, student_id: UUID, request: Request,
                  account: dict = Depends(ta)) -> list[dict]:
    with transaction() as conn:
        access(conn, request, account, lab_id)
        labs.enrollment(conn, lab_id, student_id, lock=False)
        return review.marks(conn, lab_id, student_id)


@router.get('/labs/{lab_id}/students/{student_id}/submissions',
            response_model=list[TASubmission])
def released_history(lab_id: UUID, student_id: UUID, request: Request,
                     offset: int = Query(default=0, ge=0), account: dict = Depends(ta)) -> list[dict]:
    with transaction() as conn:
        access(conn, request, account, lab_id)
        labs.enrollment(conn, lab_id, student_id, lock=False)
        rows = conn.execute(submission_api.query(lab_id).where(
            submission_store.submissions.c.account_id == student_id).order_by(
            submission_store.submissions.c.accepted_at.desc(), submission_store.submissions.c.id)
            .offset(offset).limit(100)).mappings()
        best = review.best_for_review(conn, lab_id, student_id)
        return [dict(submission_api.output(row, 'full', results_visible=True),
            best_for_review=row['id'] in best, marks=review.displayed(review.exact(row)) if row['run_id'] else None,
            maximum_marks=f"{submission_api.run_maximum(row):.2f}" if row['run_id'] else None,
            passed=row['passed'], total=row['total']) for row in rows]


@router.get('/labs/{lab_id}/students/{student_id}/submissions/{submission_id}',
            response_model=submission_api.ReleasedSubmission)
def released_submission(lab_id: UUID, student_id: UUID, submission_id: UUID, request: Request,
                        run_id: UUID | None = None, account: dict = Depends(ta)) -> dict:
    with transaction() as conn:
        access(conn, request, account, lab_id)
        labs.enrollment(conn, lab_id, student_id, lock=False)
        row = conn.execute(submission_api.query(lab_id).where(
            submission_store.submissions.c.id == submission_id,
            submission_store.submissions.c.account_id == student_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Submission not found')
        return submission_api.released_data(conn, row, submission_id, run_id)


@router.get('/labs/{lab_id}/events')
async def events(lab_id: UUID, request: Request, account: dict = Depends(ta)):
    if request.headers.get('origin') is not None:
        same_origin(request)
    def authorize() -> None:
        with transaction() as conn:
            access(conn, request, account, lab_id)
    await run_in_threadpool(authorize)
    if not hub.available:
        raise HTTPException(503, 'Live connection unavailable')
    async def stream():
        async with hub.subscribe(lab_id, account['id']) as queue:
            yield 'event: refresh\ndata: {}\n\n'
            while not await request.is_disconnected():
                try:
                    await asyncio.wait_for(queue.get(), timeout=25)
                except TimeoutError:
                    try:
                        await run_in_threadpool(authorize)
                    except HTTPException as exc:
                        yield 'event: denied\ndata: {"detail":"Access changed"}\n\n' if exc.status_code == 401 else 'event: access-lost\ndata: {}\n\n'
                        return
                    yield ': keepalive\n\n'
                    continue
                try:
                    await run_in_threadpool(authorize)
                except HTTPException as exc:
                    yield 'event: denied\ndata: {"detail":"Access changed"}\n\n' if exc.status_code == 401 else 'event: access-lost\ndata: {}\n\n'
                    return
                yield 'event: refresh\ndata: {}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})


@router.get('/events')
async def list_events(request: Request, account: dict = Depends(ta)):
    if request.headers.get('origin') is not None:
        same_origin(request)
    def authorize() -> None:
        with transaction() as conn:
            access(conn, request, account)
    await run_in_threadpool(authorize)
    if not hub.available:
        raise HTTPException(503, 'Live connection unavailable')
    async def stream():
        async with hub.subscribe(UUID(int=0), account['id']) as queue:
            yield 'event: refresh\ndata: {}\n\n'
            while not await request.is_disconnected():
                try:
                    await asyncio.wait_for(queue.get(), timeout=25)
                except TimeoutError:
                    try:
                        await run_in_threadpool(authorize)
                    except HTTPException:
                        yield 'event: denied\ndata: {}\n\n'
                        return
                    yield ': keepalive\n\n'
                    continue
                try:
                    await run_in_threadpool(authorize)
                except HTTPException:
                    yield 'event: denied\ndata: {}\n\n'
                    return
                yield 'event: refresh\ndata: {}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})
