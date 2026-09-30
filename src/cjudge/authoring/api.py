"""Admin-only staged generation. Applying cases never publishes a revision."""
import hashlib
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool

from cjudge import authoring as store, identity, runner
from cjudge.identity.api import admin, admin_write, no_store
from cjudge.tasks.api import VersionInput, find_task, json_input, update_cases
from cjudge.tasks.authoring import GenerationConfig

router = APIRouter(prefix='/api/admin/tasks', dependencies=[Depends(admin), Depends(no_store)])


class GenerateInput(VersionInput):
    config: GenerationConfig


def find(conn: sa.Connection, task_id: UUID, job_id: UUID, *, lock: bool = False) -> dict:
    query = sa.select(store.jobs).where(store.jobs.c.id == job_id, store.jobs.c.task_id == task_id)
    row = conn.execute(query.with_for_update() if lock else query).mappings().first()
    if not row:
        raise HTTPException(404, 'Generation job not found')
    return dict(row)


def output(conn: sa.Connection, row: dict) -> dict:
    entries = conn.execute(sa.select(store.cases).where(store.cases.c.job_id == row['id'])
                           .order_by(store.cases.c.number)).mappings().all()
    return dict(row) | {'config': row['config'] | {'seed': str(row['config']['seed'])},
                        'cases': [dict(entry) | {'seed': str(entry['seed'])} for entry in entries],
                        'source_sha256': {part: hashlib.sha256(row['config'][part].encode()).hexdigest()
                                          for part in ('generator', 'reference')}}


@router.get('/{task_id}/generation')
def latest(task_id: UUID):
    with identity.engine().connect() as conn:
        find_task(conn, task_id)
        row = conn.execute(sa.select(store.jobs).where(store.jobs.c.task_id == task_id)
            .order_by(store.jobs.c.created_at.desc(), store.jobs.c.id).limit(1)).mappings().first()
        return output(conn, dict(row)) if row else None


@router.post('/{task_id}/generation', status_code=201)
async def create(task_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, GenerateInput)
    def perform():
        with identity.engine().begin() as conn:
            find_task(conn, task_id, body.version)
            if conn.execute(sa.select(store.jobs.c.id).where(store.jobs.c.task_id == task_id,
                    store.jobs.c.state.not_in(['applied', 'discarded']))).first():
                raise HTTPException(409, 'Apply or discard the existing generation job first')
            key = uuid4()
            conn.execute(sa.insert(store.jobs).values(id=key, task_id=task_id, base_version=body.version,
                config=body.config.model_dump(mode='json'), actor_id=actor['id']))
            identity.audit(conn, 'generation_created', actor['id'], detail={'task_id': str(task_id), 'job_id': str(key)})
            store.signal(conn)
            return output(conn, find(conn, task_id, key))
    return await run_in_threadpool(perform)


@router.get('/{task_id}/generation/{job_id}')
def status(task_id: UUID, job_id: UUID):
    with identity.engine().connect() as conn:
        return output(conn, find(conn, task_id, job_id))


@router.get('/{task_id}/generation/{job_id}/cases/{number}/{part}')
def preview(task_id: UUID, job_id: UUID, number: int, part: str):
    if part not in ('in', 'out'):
        raise HTTPException(404, 'Case part not found')
    with identity.engine().connect() as conn:
        find(conn, task_id, job_id)
        row = conn.execute(sa.select(store.cases).where(store.cases.c.job_id == job_id,
            store.cases.c.number == number)).mappings().first()
        if not row:
            raise HTTPException(404, 'Case not found')
        try:
            payload = store.read(job_id, row['artifact_id'], part)
        except (OSError, runner.SandboxError) as exc:
            raise HTTPException(503, 'Generation artifacts unavailable') from exc
    return Response(payload, media_type='application/octet-stream', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'attachment; filename="{number}.{part}"'})


@router.post('/{task_id}/generation/{job_id}/{action}')
async def change(task_id: UUID, job_id: UUID, action: str, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, VersionInput)
    if action not in ('apply', 'retry', 'discard'):
        raise HTTPException(404, 'Unknown action')
    def perform():
        with identity.engine().begin() as conn:
            task = find_task(conn, task_id, body.version)
            row = find(conn, task_id, job_id, lock=True)
            if action == 'apply':
                if row['state'] != 'complete' or row['base_version'] != task['version']:
                    raise HTTPException(409, 'Apply requires a complete job and unchanged draft')
                try:
                    pairs = store.staged_cases(conn, job_id)
                except (OSError, runner.SandboxError) as exc:
                    raise HTTPException(503, 'Generation artifacts unavailable') from exc
                if len(pairs) != row['config']['count']:
                    raise HTTPException(409, 'Generation is incomplete')
                result = update_cases(conn, task, pairs, actor)
                state = 'applied'
            elif action == 'retry':
                if row['state'] != 'failed':
                    raise HTTPException(409, 'Only failed generation can be retried')
                state = 'queued'; result = None
            else:
                if row['state'] not in ('complete', 'failed'):
                    raise HTTPException(409, 'Wait for generation to finish before discarding')
                state = 'discarded'; result = None
            conn.execute(sa.update(store.jobs).where(store.jobs.c.id == job_id).values(
                state=state, **({'fault_count': 0, 'diagnostic': ''} if action == 'retry' else {})))
            identity.audit(conn, 'generation_' + action, actor['id'], detail={'task_id': str(task_id), 'job_id': str(job_id)})
            store.signal(conn)
            return result or output(conn, find(conn, task_id, job_id))
    return await run_in_threadpool(perform)
