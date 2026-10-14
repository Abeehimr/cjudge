"""Admin test uploads and evidence; no student-facing routes."""
import hashlib
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool

from cjudge import identity, tasks, tester
from cjudge.identity.api import admin, admin_write, no_store
from cjudge.tasks.api import bounded_body, find_task, json_input
from cjudge.labs.api import ReasonInput

router = APIRouter(prefix='/api/admin/tasks/{task_id}/tester', dependencies=[Depends(admin), Depends(no_store)])


def find(conn: sa.Connection, task_id: UUID, batch_id: UUID, *, lock: bool = False,
         include_deleted: bool = False) -> dict:
    query = sa.select(tester.batches).where(tester.batches.c.id == batch_id,
        tester.batches.c.task_id == task_id)
    row = conn.execute(query.with_for_update() if lock else query).mappings().first()
    if not row or (row['deleted_at'] and not include_deleted):
        raise HTTPException(404, 'Test batch not found')
    return dict(row)


def source_view(row: dict, total: int) -> dict:
    state = row['state']
    verdict = ('Restricted source' if state == 'complete' and row['restriction'] else
        'CE' if state == 'complete' and row['progress'] == 0 else
        'AC' if state == 'complete' and row['passed'] == total else
        'Partial' if state == 'complete' and row['passed'] else
        'Failed' if state == 'complete' else state)
    return {key: row[key] for key in ('id', 'filename', 'state', 'progress', 'passed',
        'compiler_feedback', 'compiler_truncated', 'diagnostic', 'restriction')} | {'total': total, 'verdict': verdict,
        'percentage': round(row['passed'] * 100 / total, 2) if state == 'complete' else None}


def output(conn: sa.Connection, batch: dict) -> dict:
    total = conn.execute(sa.select(tasks.revisions.c.case_count).where(
        tasks.revisions.c.id == batch['revision_id'])).scalar_one()
    rows = conn.execute(sa.select(tester.sources).where(tester.sources.c.batch_id == batch['id'])
        .order_by(tester.sources.c.filename)).mappings().all()
    return {'id': batch['id'], 'revision_id': batch['revision_id'], 'created_at': batch['created_at'],
        'sources': [source_view(row, total) for row in rows]}


@router.get('')
def list_batches(task_id: UUID, revision_id: UUID | None = None):
    with identity.engine().connect() as conn:
        find_task(conn, task_id)
        query = sa.select(tester.batches).where(tester.batches.c.task_id == task_id,
            tester.batches.c.deleted_at.is_(None))
        if revision_id:
            query = query.where(tester.batches.c.revision_id == revision_id)
        rows = conn.execute(query.order_by(tester.batches.c.created_at.desc()).limit(100)).mappings()
        return [output(conn, dict(row)) for row in rows]


@router.post('', status_code=201)
async def create(task_id: UUID, request: Request, revision_id: UUID,
                 actor: dict = Depends(admin_write)):
    media = request.headers.get('content-type', '').split(';')[0]
    if media not in ('text/x-c', 'application/octet-stream', 'application/zip'):
        raise HTTPException(415, 'C source or ZIP required')
    payload = await bounded_body(request, tester.ZIP_LIMIT if media == 'application/zip' else tester.SOURCE_BYTES)
    filename = request.headers.get('x-filename', '')
    try:
        items = tester.parse_sources(filename, payload, archive=media == 'application/zip')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    key = request.headers.get('idempotency-key')
    if key is not None and (not 1 <= len(key) <= 128 or not key.isascii() or not key.isprintable()):
        raise HTTPException(422, 'Invalid idempotency key')
    digest = hashlib.sha256((b'' if media == 'application/zip' else filename.encode() + b'\0') + payload).hexdigest()
    def perform():
        with identity.engine().begin() as conn:
            conn.execute(sa.select(sa.func.pg_advisory_xact_lock(51003)))
            find_task(conn, task_id)
            revision = conn.execute(sa.select(tasks.revisions).where(tasks.revisions.c.id == revision_id,
                tasks.revisions.c.task_id == task_id)).mappings().first()
            if not revision or not revision['case_count']:
                raise HTTPException(404, 'Published revision not found')
            if key:
                previous = conn.execute(sa.select(tester.batches).where(tester.batches.c.actor_id == actor['id'],
                    tester.batches.c.idempotency_key == key)).mappings().first()
                if previous:
                    if previous['task_id'] != task_id or previous['revision_id'] != revision_id or previous['payload_sha256'] != digest:
                        raise HTTPException(409, 'Idempotency key already used for different upload')
                    if previous['deleted_at']:
                        raise HTTPException(409, 'Idempotency key belongs to a deleted batch')
                    return output(conn, dict(previous))
            outstanding = conn.execute(sa.select(sa.func.count()).select_from(tester.sources)
                .where(tester.sources.c.state.in_(['queued', 'testing']))).scalar_one()
            if outstanding + len(items) > tester.OUTSTANDING_LIMIT:
                raise HTTPException(429, 'Tester queue full; try again after jobs finish')
            batch_id = uuid4()
            conn.execute(sa.insert(tester.batches).values(id=batch_id, task_id=task_id,
                revision_id=revision_id, actor_id=actor['id'], idempotency_key=key, payload_sha256=digest))
            for name, source in items:
                source_id = uuid4()
                tester.save(batch_id, source_id, 'c', source)
                conn.execute(sa.insert(tester.sources).values(id=source_id, batch_id=batch_id,
                    filename=name, size=len(source), sha256=hashlib.sha256(source).hexdigest()))
            identity.audit(conn, 'tester_created', actor['id'], detail={'task_id': str(task_id), 'batch_id': str(batch_id), 'count': len(items)})
            tester.signal(conn)
            return output(conn, find(conn, task_id, batch_id))
    return await run_in_threadpool(perform)


@router.get('/{batch_id}')
def status(task_id: UUID, batch_id: UUID):
    with identity.engine().connect() as conn:
        return output(conn, find(conn, task_id, batch_id))


@router.get('/{batch_id}/sources/{source_id}')
def source(task_id: UUID, batch_id: UUID, source_id: UUID):
    with identity.engine().connect() as conn:
        find(conn, task_id, batch_id)
        row = conn.execute(sa.select(tester.sources).where(tester.sources.c.id == source_id,
            tester.sources.c.batch_id == batch_id)).mappings().first()
        if not row:
            raise HTTPException(404, 'Source not found')
        try:
            content = tester.read(dict(row), 'c')
        except OSError as exc:
            raise HTTPException(503, 'Tester source unavailable') from exc
        total = conn.execute(sa.select(tasks.revisions.c.case_count).join(tester.batches,
            tester.batches.c.revision_id == tasks.revisions.c.id).where(tester.batches.c.id == batch_id)).scalar_one()
        case_rows = conn.execute(sa.select(tester.cases).where(tester.cases.c.source_id == source_id)
            .order_by(tester.cases.c.number)).mappings()
        return {'source': source_view(dict(row), total), 'code': content.decode('utf-8', errors='replace'),
            'cases': [{'number': case['number'], 'verdict': case['verdict'],
                'cpu_seconds': case['cpu_seconds'], 'wall_seconds': case['wall_seconds'],
                'memory_kib': case['memory_kib']} for case in case_rows]}


def preview(data: bytes) -> dict:
    return {'text': data[:65536].decode('utf-8', errors='replace'), 'truncated': len(data) > 65536}


@router.get('/{batch_id}/sources/{source_id}/cases/{number}')
def case_detail(task_id: UUID, batch_id: UUID, source_id: UUID, number: int):
    with identity.engine().connect() as conn:
        batch = find(conn, task_id, batch_id)
        row = conn.execute(sa.select(tester.cases).join(tester.sources,
            tester.sources.c.id == tester.cases.c.source_id).where(tester.sources.c.batch_id == batch_id,
            tester.cases.c.source_id == source_id, tester.cases.c.number == number)).mappings().first()
        if not row:
            raise HTTPException(404, 'Case result not found')
        revision = conn.execute(sa.select(tasks.revisions).where(
            tasks.revisions.c.id == batch['revision_id'])).mappings().one()
        try:
            pairs = tasks.load_cases(revision['cases_key'])
            stdin, answer = pairs[number - 1]
        except (OSError, ValueError, IndexError) as exc:
            raise HTTPException(503, 'Test artifacts unavailable') from exc
        return {'number': number, 'verdict': row['verdict'], 'cpu_seconds': row['cpu_seconds'],
            'wall_seconds': row['wall_seconds'], 'memory_kib': row['memory_kib'],
            'stdin': preview(stdin), 'expected': preview(answer), 'stdout': preview(row['stdout']),
            'stderr': preview(row['stderr']), 'stdout_truncated': row['stdout_truncated'],
            'stderr_truncated': row['stderr_truncated']}


@router.post('/{batch_id}/sources/{source_id}/retry', status_code=204)
def retry(task_id: UUID, batch_id: UUID, source_id: UUID, actor: dict = Depends(admin_write)):
    with identity.engine().begin() as conn:
        find(conn, task_id, batch_id, lock=True)
        row = conn.execute(sa.select(tester.sources).where(tester.sources.c.id == source_id,
            tester.sources.c.batch_id == batch_id).with_for_update()).mappings().first()
        if not row or row['state'] != 'failed':
            raise HTTPException(409, 'Only failed sources can be retried')
        conn.execute(sa.update(tester.sources).where(tester.sources.c.id == source_id).values(state='queued', fault_count=0, diagnostic=''))
        identity.audit(conn, 'tester_retried', actor['id'], detail={'batch_id': str(batch_id), 'source_id': str(source_id)})
        tester.signal(conn)
    return Response(status_code=204)


@router.delete('/{batch_id}', status_code=204)
async def delete(task_id: UUID, batch_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, ReasonInput)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, 'Reason required')
    def perform():
        with identity.engine().begin() as conn:
            batch = find(conn, task_id, batch_id, lock=True, include_deleted=True)
            rows = conn.execute(sa.select(tester.sources).where(tester.sources.c.batch_id == batch_id).with_for_update()).mappings().all()
            if any(row['state'] not in ('complete', 'failed') for row in rows):
                raise HTTPException(409, 'Wait for every source to finish')
            if not batch['deleted_at']:
                conn.execute(sa.update(tester.batches).where(tester.batches.c.id == batch_id).values(
                    deleted_at=sa.func.now(), delete_reason=reason))
                identity.audit(conn, 'tester_deleted', actor['id'], detail={'task_id': str(task_id),
                    'batch_id': str(batch_id), 'reason': reason})
                tester.signal(conn)
        for row in rows:
            for part in ('c', 'bin'):
                tester.path(batch_id, row['id'], part).unlink(missing_ok=True)
        if rows:
            directory = tester.path(batch_id, rows[0]['id'], 'c').parent
            if directory.exists():
                for temporary in directory.glob('*.tmp'):
                    if re.fullmatch(r'[0-9a-f]{32}\.tmp', temporary.name):
                        temporary.unlink()
                directory.rmdir()
        with identity.engine().begin() as conn:
            conn.execute(sa.select(tester.batches.c.id).where(tester.batches.c.id == batch_id).with_for_update())
            source_ids = [row['id'] for row in rows]
            conn.execute(sa.delete(tester.cases).where(tester.cases.c.source_id.in_(source_ids)))
            conn.execute(sa.delete(tester.attempts).where(tester.attempts.c.source_id.in_(source_ids)))
            conn.execute(sa.delete(tester.sources).where(tester.sources.c.batch_id == batch_id))
            conn.execute(sa.delete(tester.batches).where(tester.batches.c.id == batch_id))
    await run_in_threadpool(perform)
    return Response(status_code=204)
