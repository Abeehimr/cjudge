"""Admin-only worker visibility; heartbeat freshness is not a synthetic probe."""
import asyncio
from datetime import datetime
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from cjudge import identity, labs
from cjudge.events import hub
from cjudge.identity.api import admin, admin_write, COOKIE, no_store, same_origin, StrictModel
from cjudge.judging import queue
from cjudge.judging.worker import pool_size
from cjudge.labs.api import ReasonInput
from cjudge.submissions import workers, attempts, jobs
from cjudge.submissions.api import transaction
from cjudge.tasks.api import json_input

router = APIRouter(prefix='/api/admin', dependencies=[Depends(admin), Depends(no_store)])


class IsolateOutput(StrictModel):
    slot: int
    state: str
    healthy: bool
    heartbeat_at: datetime | None
    started_at: datetime | None
    lease_until: datetime | None
    submission_id: UUID | None
    completed: int
    fault: str | None


class IsolatesOutput(StrictModel):
    configured: int
    healthy: int
    working: int
    server_time: datetime
    workers: list[IsolateOutput]


class FeedbackInput(StrictModel):
    mode: Literal['short', 'full', 'none']


@router.get('/isolates', response_model=IsolatesOutput)
def isolates():
    count = pool_size()
    with transaction() as conn:
        timestamp = labs.now(conn)
        rows = {row['slot']: row for row in conn.execute(sa.select(workers, attempts.c.lease_until,
            attempts.c.submission_id, jobs.c.state.label('job_state')).outerjoin(attempts,
            attempts.c.id == workers.c.attempt_id).outerjoin(jobs, jobs.c.attempt_id == attempts.c.id)
            .where(workers.c.slot < count)).mappings()}
    result = []
    for slot in range(count):
        row = rows.get(slot)
        value = dict(slot=slot, state='Offline', healthy=False, heartbeat_at=None, started_at=None,
                     lease_until=None, submission_id=None, completed=0, fault=None)
        if row:
            value.update({key: row[key] for key in value if key not in ('healthy',)})
            stale = (timestamp - row['heartbeat_at']).total_seconds() >= 90
            stale_job = row['state'] == 'Judging' and (row['job_state'] != 'judging' or not row['lease_until'] or row['lease_until'] <= timestamp)
            if stale or stale_job:
                value.update(state='Offline', submission_id=None)
            value['healthy'] = value['state'] in ('Idle', 'Judging')
        result.append(value)
    return dict(configured=count, healthy=sum(row['healthy'] for row in result),
                working=sum(row['state'] == 'Judging' for row in result), server_time=timestamp, workers=result)


@router.post('/labs/{lab_id}/submissions/{submission_id}/retry', status_code=204)
async def retry(lab_id: UUID, submission_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, ReasonInput)
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    def perform():
        with transaction() as conn:
            labs.find(conn, lab_id, shared=True)
            queue.retry(conn, lab_id, submission_id, actor['id'], body.reason.strip())
    await run_in_threadpool(perform)


@router.put('/labs/{lab_id}/compiler-feedback', status_code=204)
async def feedback(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, FeedbackInput)
    def perform():
        with transaction() as conn:
            lab = labs.find(conn, lab_id)
            labs.changed(conn, lab, actor['id'], 'lab_compiler_feedback', compiler_feedback=body.mode)
    await run_in_threadpool(perform)


@router.get('/isolates/events')
async def isolate_events(request: Request, account: dict = Depends(admin)):
    if request.headers.get('origin') is not None:
        same_origin(request)
    def authorize():
        with identity.engine().connect() as conn:
            return conn.execute(sa.select(identity.sessions.c.expires_at).where(
                identity.sessions.c.token_hash == identity.token_digest(request.cookies.get(COOKIE, '')),
                identity.sessions.c.account_id == account['id'], identity.sessions.c.expires_at > labs.now(conn))).scalar_one_or_none()
    expires = await run_in_threadpool(authorize)
    if not expires:
        raise HTTPException(401, 'Login required')
    if not hub.available:
        raise HTTPException(503, 'Live connection unavailable')
    if len(hub.clients) >= 512 or sum(member == str(account['id']) for _, member in hub.clients.values()) >= 5:
        raise HTTPException(429, 'Too many live connections')
    deadline = time.monotonic() + max(0, (expires - identity.now()).total_seconds())
    async def stream():
        try:
            async with hub.subscribe(queue.ADMIN_CHANNEL, account['id']) as pending:
                yield 'event: refresh\ndata: {}\n\n'
                while not await request.is_disconnected():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        yield 'event: denied\ndata: {}\n\n'
                        return
                    try:
                        await asyncio.wait_for(pending.get(), timeout=min(25, remaining))
                    except TimeoutError:
                        yield ': keepalive\n\n'
                        continue
                    if not hub.available:
                        yield 'event: reconnect\ndata: {}\n\n'
                        return
                    if not await run_in_threadpool(authorize):
                        yield 'event: denied\ndata: {}\n\n'
                        return
                    yield 'event: refresh\ndata: {}\n\n'
        except (RuntimeError, sa.exc.SQLAlchemyError):
            yield 'event: reconnect\ndata: {}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no', 'X-Content-Type-Options': 'nosniff'})
