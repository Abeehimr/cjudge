"""Admin-only task authoring. Students receive no task data until lab access exists."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool

from cjudge import identity, tasks as store
from cjudge.identity.api import admin, admin_write
from cjudge.tasks.cases import MAX_FILE, MAX_ZIP, parse_zip, validate_cases
from cjudge.tasks.grading import TaskConfig


def private(response: Response, account: dict = Depends(admin)) -> None:
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/admin/tasks', dependencies=[Depends(private)])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class DraftInput(StrictModel):
    version: int = Field(ge=1)
    config: TaskConfig


class VersionInput(StrictModel):
    version: int = Field(ge=1)


class CaseInput(VersionInput):
    input: str = Field(max_length=MAX_FILE)
    answer: str = Field(max_length=MAX_FILE)


class CaseSummary(StrictModel):
    number: int
    input_bytes: int
    answer_bytes: int


class RevisionOutput(StrictModel):
    id: UUID
    number: int
    draft_version: int
    created_at: datetime


class TaskOutput(StrictModel):
    id: UUID
    version: int
    config: TaskConfig
    case_count: int
    created_at: datetime


class DetailOutput(TaskOutput):
    cases: list[CaseSummary]
    revisions: list[RevisionOutput]


class PublishedOutput(RevisionOutput):
    task_id: UUID
    config: TaskConfig
    case_count: int
    cases: list[CaseSummary]


async def bounded_body(request: Request, maximum: int = MAX_ZIP) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, 'Upload exceeds size limit')
        data.extend(chunk)
    return bytes(data)


async def json_input(request: Request, schema: type[BaseModel]) -> BaseModel:
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, 'JSON required')
    try:
        return schema.model_validate_json(await bounded_body(request))
    except ValidationError as exc:
        # Do not reflect submitted test data in validation errors.
        raise HTTPException(422, '; '.join(error['msg'] for error in exc.errors(include_input=False))) from exc


def find_task(conn: sa.Connection, task_id: UUID, version: int | None = None) -> dict:
    query = sa.select(store.tasks).where(store.tasks.c.id == task_id)
    if version is not None:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise HTTPException(404, 'Task not found')
    if version is not None and version != row['version']:
        raise HTTPException(409, 'Draft changed; reload before editing or publishing')
    return dict(row)


def cases_for(row: dict) -> list[tuple[bytes, bytes]]:
    try:
        cases = store.load_cases(row['cases_key'])
        if len(cases) != row['case_count']:
            raise ValueError('Case count mismatch')
        return cases
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Task cases unavailable') from exc


def detail(conn: sa.Connection, row: dict) -> dict:
    history = conn.execute(sa.select(store.revisions).where(store.revisions.c.task_id == row['id'])
                           .order_by(store.revisions.c.number.desc())).mappings()
    return {**{key: row[key] for key in TaskOutput.model_fields},
            'cases': store.case_summary(cases_for(row)),
            'revisions': [{key: item[key] for key in RevisionOutput.model_fields} for item in history]}


def update_cases(conn: sa.Connection, row: dict, cases: list[tuple[bytes, bytes]], actor: dict) -> dict:
    try:
        validate_cases(cases)
        key = store.save_cases(cases) if cases else None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, 'Task storage unavailable') from exc
    conn.execute(sa.update(store.tasks).where(store.tasks.c.id == row['id']).values(
        cases_key=key, case_count=len(cases), version=row['version'] + 1))
    identity.audit(conn, 'task_cases_updated', actor['id'], detail={'task_id': str(row['id']), 'count': len(cases)})
    return detail(conn, find_task(conn, row['id']))


@router.get('', response_model=list[TaskOutput])
def list_tasks(response: Response, offset: int = 0) -> list[dict]:
    if offset < 0:
        raise HTTPException(400, 'Invalid offset')
    with identity.engine().connect() as conn:
        rows = conn.execute(sa.select(store.tasks).order_by(store.tasks.c.created_at.desc(), store.tasks.c.id)
                            .offset(offset).limit(100)).mappings()
        return [{key: row[key] for key in TaskOutput.model_fields} for row in rows]


@router.post('', response_model=DetailOutput, status_code=201)
async def create_task(request: Request, actor: dict = Depends(admin_write)) -> dict:
    config = await json_input(request, TaskConfig)
    def create() -> dict:
        with identity.engine().begin() as conn:
            task_id = uuid4()
            conn.execute(sa.insert(store.tasks).values(id=task_id, version=1, config=config.model_dump(mode='json'),
                                                       cases_key=None, case_count=0))
            identity.audit(conn, 'task_created', actor['id'], detail={'task_id': str(task_id)})
            return detail(conn, find_task(conn, task_id))
    return await run_in_threadpool(create)


@router.get('/{task_id}', response_model=DetailOutput)
def get_task(task_id: UUID, response: Response) -> dict:
    with identity.engine().connect() as conn:
        return detail(conn, find_task(conn, task_id))


@router.put('/{task_id}', response_model=DetailOutput)
async def edit_task(task_id: UUID, request: Request, actor: dict = Depends(admin_write)) -> dict:
    body = await json_input(request, DraftInput)
    def edit() -> dict:
        with identity.engine().begin() as conn:
            row = find_task(conn, task_id, body.version)
            conn.execute(sa.update(store.tasks).where(store.tasks.c.id == task_id).values(
                config=body.config.model_dump(mode='json'), version=row['version'] + 1))
            identity.audit(conn, 'task_draft_updated', actor['id'], detail={'task_id': str(task_id)})
            return detail(conn, find_task(conn, task_id))
    return await run_in_threadpool(edit)


@router.post('/{task_id}/cases', response_model=DetailOutput)
async def add_case(task_id: UUID, request: Request, actor: dict = Depends(admin_write)) -> dict:
    body = await json_input(request, CaseInput)
    def add() -> dict:
        with identity.engine().begin() as conn:
            row = find_task(conn, task_id, body.version)
            return update_cases(conn, row, [*cases_for(row), (body.input.encode(), body.answer.encode())], actor)
    return await run_in_threadpool(add)


@router.put('/{task_id}/cases', response_model=DetailOutput)
async def replace_zip(task_id: UUID, request: Request, version: int, actor: dict = Depends(admin_write)) -> dict:
    if request.headers.get('content-type', '').split(';')[0] != 'application/zip':
        raise HTTPException(415, 'ZIP required')
    payload = await bounded_body(request)
    def replace() -> dict:
        try:
            cases = parse_zip(payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        with identity.engine().begin() as conn:
            return update_cases(conn, find_task(conn, task_id, version), cases, actor)
    return await run_in_threadpool(replace)


@router.delete('/{task_id}/cases/{number}', response_model=DetailOutput)
def delete_case(task_id: UUID, number: int, version: int, actor: dict = Depends(admin_write)) -> dict:
    with identity.engine().begin() as conn:
        row = find_task(conn, task_id, version)
        cases = cases_for(row)
        if not 1 <= number <= len(cases):
            raise HTTPException(404, 'Case not found')
        del cases[number - 1]
        return update_cases(conn, row, cases, actor)


@router.post('/{task_id}/publish', response_model=PublishedOutput, status_code=201)
async def publish_task(task_id: UUID, request: Request, actor: dict = Depends(admin_write)) -> dict:
    body = await json_input(request, VersionInput)
    def publish() -> dict:
        with identity.engine().begin() as conn:
            row = find_task(conn, task_id, body.version)
            cases = cases_for(row)
            if not cases:
                raise HTTPException(400, 'Add at least one case before publishing')
            TaskConfig.model_validate(row['config'])
            existing = conn.execute(sa.select(store.revisions.c.id).where(
                store.revisions.c.task_id == task_id, store.revisions.c.draft_version == body.version)).first()
            if existing:
                raise HTTPException(409, 'This draft version is already published')
            number = conn.execute(sa.select(sa.func.coalesce(sa.func.max(store.revisions.c.number), 0))
                                  .where(store.revisions.c.task_id == task_id)).scalar_one() + 1
            revision_id = uuid4()
            revision = conn.execute(sa.insert(store.revisions).values(id=revision_id, task_id=task_id,
                number=number, draft_version=body.version, config=row['config'], cases_key=row['cases_key'],
                case_count=len(cases)).returning(store.revisions)).mappings().one()
            identity.audit(conn, 'task_published', actor['id'],
                           detail={'task_id': str(task_id), 'revision_id': str(revision_id), 'number': number})
            return {**{key: revision[key] for key in PublishedOutput.model_fields if key != 'cases'},
                    'cases': store.case_summary(cases)}
    return await run_in_threadpool(publish)


def find_revision(conn: sa.Connection, task_id: UUID, revision_id: UUID) -> dict:
    row = conn.execute(sa.select(store.revisions).where(store.revisions.c.id == revision_id,
                      store.revisions.c.task_id == task_id)).mappings().first()
    if not row:
        raise HTTPException(404, 'Revision not found')
    return dict(row)


@router.get('/{task_id}/revisions/{revision_id}', response_model=PublishedOutput)
def get_revision(task_id: UUID, revision_id: UUID, response: Response) -> dict:
    with identity.engine().connect() as conn:
        row = find_revision(conn, task_id, revision_id)
        return {**{key: row[key] for key in PublishedOutput.model_fields if key != 'cases'},
                'cases': store.case_summary(cases_for(row))}


@router.get('/{task_id}/cases/{number}/{part}')
def download_case(task_id: UUID, number: int, part: Literal['in', 'out'], revision_id: UUID | None = None) -> Response:
    with identity.engine().connect() as conn:
        row = find_revision(conn, task_id, revision_id) if revision_id else find_task(conn, task_id)
        cases = cases_for(row)
        if not 1 <= number <= len(cases):
            raise HTTPException(404, 'Case not found')
        return Response(cases[number - 1][0 if part == 'in' else 1], media_type='application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Content-Disposition': f'attachment; filename="{number}.{part}"'})
