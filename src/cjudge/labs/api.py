"""Lab routes with separate admin/student response contracts."""
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, Field
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from cjudge import identity, labs, tasks
from cjudge.labs import binding as lab_binding, files as lab_files
from cjudge.identity.api import CredentialOutput, StrictModel, admin, admin_write, current, write_guard, COOKIE, no_store
from cjudge.tasks.api import bounded_body, json_input
from cjudge.tasks.grading import TaskConfig


def private(response: Response) -> None:
    no_store(response)


def student(account: dict = Depends(current)) -> dict:
    if account['role'] != 'student':
        raise HTTPException(403, 'Student access required')
    return account


def student_write(account: dict = Depends(write_guard)) -> dict:
    if account['role'] != 'student':
        raise HTTPException(403, 'Student access required')
    return account


admin_router = APIRouter(prefix='/api/admin/labs', dependencies=[Depends(admin), Depends(private)])
student_router = APIRouter(prefix='/api/labs', dependencies=[Depends(student), Depends(private)])


class TitleInput(StrictModel):
    title: str = Field(min_length=1, max_length=160, pattern=r'^[^\x00-\x1f]+$')
    strict_ip: bool = False


class VersionInput(StrictModel):
    version: int = Field(ge=1)


class EarlyFeedbackInput(VersionInput):
    visible: bool


class EditInput(TitleInput, VersionInput):
    pass


class TaskInput(VersionInput):
    revision_ids: list[UUID] = Field(max_length=100)


class EnrollmentInput(VersionInput):
    ids: list[UUID] = Field(min_length=1, max_length=1000)


class StudentInput(VersionInput):
    roll_number: str = Field(max_length=64)
    name: str = Field(max_length=120)


class ScheduleInput(VersionInput):
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime


class DeadlineInput(VersionInput):
    ends_at: AwareDatetime
    action: Literal['extend', 'reopen']
    reason: str = Field(min_length=1, max_length=500)


class ReasonInput(StrictModel):
    reason: str = Field(min_length=1, max_length=500)


class StopInput(ReasonInput, VersionInput):
    pass


class FreezeInput(ReasonInput):
    frozen: bool


class AnnouncementInput(StrictModel):
    body: str = Field(min_length=1, max_length=4000)


class LabSummary(StrictModel):
    id: UUID
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    phase: str
    server_time: datetime


class PublicTask(StrictModel):
    position: int
    revision_id: UUID
    previous_revision_ids: list[UUID] = []
    title: str
    statement: str
    maximum_marks: str
    cpu_seconds: float
    wall_seconds: float
    memory_mib: int
    stack_mib: int


class AssignedTask(StrictModel):
    position: int
    revision_id: UUID
    previous_revision_ids: list[UUID] = []
    task_id: UUID
    number: int
    config: TaskConfig


class PdfOutput(StrictModel):
    id: UUID
    name: str
    size: int


class AdminPdf(PdfOutput):
    active: bool
    replaces_id: UUID | None
    created_at: datetime


class AnnouncementOutput(StrictModel):
    id: UUID
    body: str
    created_at: datetime
    audience: str = 'Everyone'


class RosterOutput(StrictModel):
    id: UUID
    roll_number: str
    name: str
    frozen: bool
    freeze_reason: str | None
    bound_ip: str | None
    last_ip: str | None
    ip_changed: bool
    bound_at: datetime | None


class AdminLab(LabSummary):
    scoreboard_visible: bool
    early_feedback_visible: bool
    version: int
    strict_ip: bool
    compiler_feedback: str
    first_released_at: datetime | None
    reveal_results: bool
    archived_at: datetime | None
    tasks: list[AssignedTask]
    pdfs: list[AdminPdf]
    students: list[RosterOutput]
    announcements: list[AnnouncementOutput]


class StudentLab(LabSummary):
    scoreboard_visible: bool
    early_feedback_visible: bool
    results_visible: bool
    frozen: bool
    tasks: list[PublicTask]
    pdfs: list[PdfOutput]
    announcements: list[AnnouncementOutput]
    admission: dict


@contextmanager
def transaction() -> Iterator[sa.Connection]:
    try:
        with identity.engine().begin() as conn:
            yield conn
    except labs.LabError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except IntegrityError as exc:
        error = labs.overlap_error(exc)
        raise HTTPException(error.status, str(error)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, 'Credentials unavailable') from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def summary(conn: sa.Connection, lab: dict, timestamp: datetime | None = None) -> dict:
    timestamp = timestamp or labs.now(conn)
    return {key: lab[key] for key in ('id', 'title', 'starts_at', 'ends_at')} | {
        'phase': labs.phase(lab, timestamp), 'server_time': timestamp}


def snapshot(conn: sa.Connection, lab: dict, enrollment: dict | None = None) -> dict:
    from cjudge.submissions import batches
    previous = {}
    for item in conn.execute(sa.select(batches.c.task_id, batches.c.base_revision_id).where(batches.c.lab_id == lab['id'])).all():
        previous.setdefault(item.task_id, []).append(item.base_revision_id)
    admin_view = enrollment is None
    scoreboard_visible = lab['scoreboard_visible']
    assigned = labs.task_rows(conn, lab['id'])
    pdf_query = sa.select(labs.pdfs).where(labs.pdfs.c.lab_id == lab['id'])
    if not admin_view:
        pdf_query = pdf_query.where(labs.pdfs.c.active)
    pdf_rows = [dict(row) for row in conn.execute(pdf_query.order_by(labs.pdfs.c.created_at, labs.pdfs.c.id)).mappings()]
    message_query = sa.select(labs.announcements, identity.accounts.c.roll_number, identity.accounts.c.name).outerjoin(
        identity.accounts, identity.accounts.c.id == labs.announcements.c.recipient_id).where(labs.announcements.c.lab_id == lab['id'])
    if not admin_view:
        message_query = message_query.where(sa.or_(labs.announcements.c.recipient_id.is_(None),
            labs.announcements.c.recipient_id == enrollment['account_id']))
    messages = []
    for row in conn.execute(message_query.order_by(labs.announcements.c.created_at, labs.announcements.c.id)).mappings():
        audience = 'Everyone' if row['recipient_id'] is None else f"Only {row['roll_number']} · {row['name']}" if admin_view else 'Only you'
        messages.append(dict(row, audience=audience))
    result = summary(conn, lab) | {'pdfs': [{key: row[key] for key in (AdminPdf if admin_view else PdfOutput).model_fields}
                                          for row in pdf_rows],
        'announcements': [{key: row[key] for key in AnnouncementOutput.model_fields} for row in messages]}
    if admin_view:
        roster = conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number, identity.accounts.c.name,
            *[labs.enrollments.c[key] for key in RosterOutput.model_fields if key not in ('id', 'roll_number', 'name')])
            .join(labs.enrollments, identity.accounts.c.id == labs.enrollments.c.account_id)
            .where(labs.enrollments.c.lab_id == lab['id']).order_by(identity.accounts.c.roll_number)).mappings()
        result.update(version=lab['version'], strict_ip=lab['strict_ip'], compiler_feedback=lab['compiler_feedback'], first_released_at=lab['first_released_at'], reveal_results=lab['reveal_results'], archived_at=lab['archived_at'],
            students=[dict(row) for row in roster], tasks=[{'position': row['position'], 'revision_id': row['id'],
                'previous_revision_ids': previous.get(row['task_id'], []),
                'task_id': row['task_id'], 'number': row['number'], 'config': row['config']} for row in assigned])
    else:
        public_tasks = []
        for row in assigned:
            config = TaskConfig.model_validate(row['config']).model_dump(mode='json')
            public_tasks.append({'position': row['position'], 'revision_id': row['id'],
                'previous_revision_ids': previous.get(row['task_id'], []),
                **{key: config[key] for key in PublicTask.model_fields if key not in ('position', 'revision_id', 'previous_revision_ids')}})
        from cjudge.submissions.service import allowance
        result.update(results_visible=bool(lab['first_released_at'] and lab['reveal_results']), frozen=enrollment['frozen'], tasks=public_tasks, admission=allowance(conn, lab, enrollment))
    result['scoreboard_visible'] = scoreboard_visible
    result['early_feedback_visible'] = lab['early_feedback_visible']
    return result


def student_access(conn: sa.Connection, lab_id: UUID, account: dict, request: Request,
                   enter: bool = False, readonly: bool = False) -> tuple[dict, dict, str | None]:
    readonly = readonly and not enter
    lab = labs.find(conn, lab_id, shared=True, lock=not readonly)
    row, token = lab_binding.access(conn, lab, account['id'], request.cookies.get(COOKIE),
        request.cookies.get(lab_binding.cookie_name(lab_id)), lab_binding.client_ip(request), enter=enter, readonly=readonly)
    return lab, row, token


@admin_router.get('', response_model=list[LabSummary])
def list_admin_labs(offset: int = Query(default=0, ge=0)):
    with transaction() as conn:
        timestamp = labs.now(conn)
        return [summary(conn, dict(row), timestamp) for row in conn.execute(sa.select(labs.labs)
            .order_by(labs.labs.c.created_at.desc(), labs.labs.c.id).offset(offset).limit(100)).mappings()]


@admin_router.get('/task-options', response_model=list[AssignedTask])
def task_options(offset: int = Query(default=0, ge=0)):
    with transaction() as conn:
        rows = conn.execute(sa.select(tasks.revisions).order_by(tasks.revisions.c.created_at.desc(), tasks.revisions.c.id)
                            .offset(offset).limit(100)).mappings()
        return [{'position': 0, 'revision_id': row['id'], 'task_id': row['task_id'], 'number': row['number'],
                 'config': row['config']} for row in rows]


@admin_router.post('', response_model=AdminLab, status_code=201)
async def create_lab(request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, TitleInput)
    if not body.title.strip():
        raise HTTPException(400, 'Title cannot be blank')
    def create():
        with transaction() as conn:
            return snapshot(conn, labs.create(conn, body.title.strip(), body.strict_ip, actor['id']))
    return await run_in_threadpool(create)


@admin_router.get('/{lab_id}', response_model=AdminLab)
def admin_lab(lab_id: UUID):
    with transaction() as conn:
        return snapshot(conn, labs.find(conn, lab_id, shared=True))


@admin_router.put('/{lab_id}/early-feedback/visibility', response_model=AdminLab)
async def early_feedback_visibility(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, EarlyFeedbackInput)
    def change():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            return snapshot(conn, labs.changed(conn, lab, actor['id'], 'lab_early_feedback_visibility',
                message=f'Early passed/total feedback {"enabled" if body.visible else "disabled"}.',
                early_feedback_visible=body.visible))
    return await run_in_threadpool(change)


@admin_router.put('/{lab_id}', response_model=AdminLab)
async def edit_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, EditInput)
    if not body.title.strip():
        raise HTTPException(400, 'Title cannot be blank')
    def edit():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            labs.setup_open(lab, labs.now(conn))
            return snapshot(conn, labs.changed(conn, lab, actor['id'], 'lab_edited', title=body.title.strip(), strict_ip=body.strict_ip))
    return await run_in_threadpool(edit)


@admin_router.put('/{lab_id}/tasks', response_model=AdminLab)
async def assign_tasks(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, TaskInput)
    def assign():
        with transaction() as conn:
            return snapshot(conn, labs.set_tasks(conn, labs.find(conn, lab_id, body.version), body.revision_ids, actor['id']))
    return await run_in_threadpool(assign)


@admin_router.post('/{lab_id}/students', response_model=AdminLab)
async def enroll_students(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, EnrollmentInput)
    def enroll():
        with transaction() as conn:
            return snapshot(conn, labs.enroll(conn, labs.find(conn, lab_id, body.version), body.ids, actor['id']))
    return await run_in_threadpool(enroll)


@admin_router.post('/{lab_id}/students/manual', response_model=AdminLab)
async def manual_student(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, StudentInput)
    def enroll():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            rows = [(identity.normalize_roll(body.roll_number), identity.normalize_name(body.name))]
            report = labs.import_roster(conn, lab, rows, actor['id'])
            result = snapshot(conn, labs.find(conn, lab_id))
            if report['name_mismatches']:
                raise labs.LabError(409, 'Existing student name differs; enroll the existing account or edit its name first')
            return result
    return await run_in_threadpool(enroll)


@admin_router.post('/{lab_id}/students/import')
async def import_students(lab_id: UUID, request: Request, version: int = Query(ge=1), actor: dict = Depends(admin_write)):
    if request.headers.get('content-type', '').split(';')[0] != 'text/csv':
        raise HTTPException(415, 'CSV required')
    payload = await bounded_body(request, 1024 * 1024)
    def enroll():
        with transaction() as conn:
            return labs.import_roster(conn, labs.find(conn, lab_id, version), identity.parse_csv(payload), actor['id'])
    return await run_in_threadpool(enroll)


@admin_router.delete('/{lab_id}/students/{account_id}', response_model=AdminLab)
def remove_student(lab_id: UUID, account_id: UUID, version: int = Query(ge=1), actor: dict = Depends(admin_write)):
    with transaction() as conn:
        return snapshot(conn, labs.remove_student(conn, labs.find(conn, lab_id, version), account_id, actor['id']))


@admin_router.post('/{lab_id}/students/{account_id}/freeze', status_code=204)
async def freeze_student(lab_id: UUID, account_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, FreezeInput)
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    def freeze():
        with transaction() as conn:
            labs.freeze(conn, labs.find(conn, lab_id, shared=True), account_id, body.frozen, body.reason.strip(), actor['id'])
    await run_in_threadpool(freeze)


@admin_router.post('/{lab_id}/students/{account_id}/release', response_model=CredentialOutput)
async def release_binding(lab_id: UUID, account_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, ReasonInput)
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    def release():
        with transaction() as conn:
            return lab_binding.release(conn, labs.find(conn, lab_id, shared=True), account_id, body.reason.strip(), actor['id'])
    try:
        return await run_in_threadpool(release)
    except RuntimeError as exc:
        raise HTTPException(503, 'Credentials unavailable') from exc


@admin_router.post('/{lab_id}/schedule', response_model=AdminLab)
async def schedule_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, ScheduleInput)
    def schedule():
        with transaction() as conn:
            return snapshot(conn, labs.schedule(conn, labs.find(conn, lab_id, body.version), body.starts_at, body.ends_at, actor['id']))
    return await run_in_threadpool(schedule)


@admin_router.post('/{lab_id}/deadline', response_model=AdminLab)
async def change_deadline(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, DeadlineInput)
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    def change():
        with transaction() as conn:
            return snapshot(conn, labs.deadline(conn, labs.find(conn, lab_id, body.version), body.ends_at,
                            body.action, body.reason.strip(), actor['id']))
    return await run_in_threadpool(change)


@admin_router.post('/{lab_id}/pdfs', response_model=AdminLab)
async def upload_pdf(lab_id: UUID, request: Request, name: str = Query(min_length=1, max_length=160, pattern=r'^[^\x00-\x1f]+$'),
                     version: int = Query(ge=1), replaces: UUID | None = None, actor: dict = Depends(admin_write)):
    if request.headers.get('content-type', '').split(';')[0] != 'application/pdf':
        raise HTTPException(415, 'PDF required')
    payload = await bounded_body(request, lab_files.MAX_PDF)
    def upload():
        with transaction() as conn:
            return snapshot(conn, lab_files.upload(conn, labs.find(conn, lab_id, version), payload, name, actor['id'], replaces))
    return await run_in_threadpool(upload)


@admin_router.delete('/{lab_id}/pdfs/{pdf_id}', response_model=AdminLab)
def remove_pdf(lab_id: UUID, pdf_id: UUID, version: int = Query(ge=1), actor: dict = Depends(admin_write)):
    with transaction() as conn:
        return snapshot(conn, lab_files.remove(conn, labs.find(conn, lab_id, version), pdf_id, actor['id']))


def pdf_response(data: bytes, pdf_id: UUID) -> Response:
    return Response(data, media_type='application/pdf', headers={'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Disposition': f'attachment; filename="{pdf_id}.pdf"'})


@admin_router.get('/{lab_id}/pdfs/{pdf_id}')
def admin_pdf(lab_id: UUID, pdf_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        return pdf_response(lab_files.read(conn, lab_id, pdf_id, active_only=False), pdf_id)


@admin_router.post('/{lab_id}/announcements', response_model=AdminLab)
async def post_announcement(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, AnnouncementInput)
    if not body.body.strip():
        raise HTTPException(400, 'Announcement cannot be blank')
    def post():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, shared=True)
            labs.editable(lab)
            labs.announce(conn, lab_id, body.body.strip(), actor['id'])
            return snapshot(conn, lab)
    return await run_in_threadpool(post)


@student_router.get('', response_model=list[LabSummary])
def assigned_labs(account: dict = Depends(student)):
    with transaction() as conn:
        timestamp = labs.now(conn)
        rows = conn.execute(sa.select(labs.labs).join(labs.enrollments, labs.labs.c.id == labs.enrollments.c.lab_id)
            .where(labs.enrollments.c.account_id == account['id'], labs.labs.c.starts_at.is_not(None))
            .order_by(labs.labs.c.starts_at.desc())).mappings()
        return [summary(conn, dict(row), timestamp) for row in rows]


@student_router.post('/{lab_id}/enter', response_model=StudentLab)
def enter_lab(lab_id: UUID, request: Request, response: Response, account: dict = Depends(student_write)):
    with transaction() as conn:
        lab, row, token = student_access(conn, lab_id, account, request, enter=True)
        result = snapshot(conn, lab, row)
    if token:
        response.set_cookie(lab_binding.cookie_name(lab_id), token, max_age=lab_binding.COOKIE_DAYS * 86400,
            secure=True, httponly=True, samesite='lax', path=f'/api/labs/{lab_id}')
    return result


@student_router.get('/{lab_id}', response_model=StudentLab)
def student_lab(lab_id: UUID, request: Request, account: dict = Depends(student)):
    with transaction() as conn:
        lab, row, _ = student_access(conn, lab_id, account, request, readonly=True)
        return snapshot(conn, lab, row)


@student_router.get('/{lab_id}/pdfs/{pdf_id}')
def student_pdf(lab_id: UUID, pdf_id: UUID, request: Request, account: dict = Depends(student)):
    with transaction() as conn:
        student_access(conn, lab_id, account, request, readonly=True)
        return pdf_response(lab_files.read(conn, lab_id, pdf_id, active_only=True), pdf_id)


@student_router.get('/{lab_id}/events')
async def lab_events(lab_id: UUID, request: Request, account: dict = Depends(student)):
    import asyncio
    import time
    from starlette.responses import StreamingResponse
    from cjudge.events import hub
    from cjudge.identity.api import same_origin
    # EventSource sends Origin for cross-origin requests; same-origin clients may omit it.
    if request.headers.get('origin') is not None:
        same_origin(request)
    def authorize():
        with transaction() as conn:
            student_access(conn, lab_id, account, request, readonly=True)
            return conn.execute(sa.select(identity.sessions.c.expires_at).where(
                identity.sessions.c.token_hash == identity.token_digest(request.cookies[COOKIE]))).scalar_one()
    expires = await run_in_threadpool(authorize)
    if not hub.available:
        raise HTTPException(503, 'Live connection unavailable; reconnect shortly')
    if len(hub.clients) >= 512 or sum(member == str(account['id']) for _, member in hub.clients.values()) >= 5:
        raise HTTPException(429, 'Too many live connections; close another lab tab')
    # Subscription registration precedes initial refresh, closing the snapshot/subscription gap.
    remaining = max(0, (expires - identity.now()).total_seconds())
    expires_clock = time.monotonic() + remaining
    async def stream():
        try:
            async with hub.subscribe(lab_id, account['id']) as queue:
                yield 'event: refresh\ndata: {}\n\n'
                while not await request.is_disconnected():
                    remaining = expires_clock - time.monotonic()
                    if remaining <= 0:
                        yield 'event: denied\ndata: {"detail":"Login required"}\n\n'
                        return
                    try:
                        await asyncio.wait_for(queue.get(), timeout=min(25, remaining))
                    except TimeoutError:
                        yield ': keepalive\n\n'  # No database query or process spawning.
                        continue
                    if not hub.available:
                        yield 'event: reconnect\ndata: {}\n\n'
                        return
                    try:
                        await run_in_threadpool(authorize)
                    except HTTPException:
                        yield 'event: denied\ndata: {"detail":"Lab access changed; sign in or enter again"}\n\n'
                        return
                    yield 'event: refresh\ndata: {}\n\n'
        except RuntimeError:
            yield 'event: reconnect\ndata: {}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff'})


@admin_router.post('/{lab_id}/stop', response_model=AdminLab)
async def stop_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, StopInput)
    def perform():
        with transaction() as conn:
            return snapshot(conn, labs.stop(conn, labs.find(conn, lab_id, body.version), body.reason, actor['id']))
    return await run_in_threadpool(perform)


class RevealInput(StopInput):
    enabled: bool
    acknowledge_reuse: bool = False


@admin_router.get('/{lab_id}/release-warnings')
def release_warnings(lab_id: UUID, revision_id: UUID | None = None):
    from cjudge.labs import release
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        return release.reuse(conn, lab_id, revision_id)


@admin_router.post('/{lab_id}/results', response_model=AdminLab)
async def results(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    from cjudge.labs import release
    body = await json_input(request, RevealInput)
    def perform():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            return snapshot(conn, release.reveal(conn, lab, body.enabled, body.acknowledge_reuse, actor['id'], body.reason))
    return await run_in_threadpool(perform)


@admin_router.post('/{lab_id}/archive', response_model=AdminLab)
async def archive_lab(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    from cjudge.labs import release
    body = await json_input(request, StopInput)
    def perform():
        with transaction() as conn:
            return snapshot(conn, release.archive(conn, labs.find(conn, lab_id, body.version), actor['id'], body.reason))
    return await run_in_threadpool(perform)
