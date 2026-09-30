"""Short leased queue transactions. No transaction spans sandbox execution."""
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from cjudge import authoring, events, identity, labs
from cjudge.submissions import submissions, jobs, attempts, workers, turns, runs, cases, reviews, members

SCHEDULER_LOCK = 51002
ADMIN_CHANNEL = UUID(int=0)
LEASE_SECONDS = 60


def scheduler_lock(conn: sa.Connection) -> None:
    # Claim serialization provides deterministic round-robin ordering across workers.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(SCHEDULER_LOCK)))


def notify(conn: sa.Connection, account_id: UUID | None = None) -> None:
    events.publish(conn, lab_id=ADMIN_CHANNEL)
    if account_id:
        events.publish(conn, account_id=account_id)


def register(conn: sa.Connection, slot: int, generation: UUID) -> None:
    scheduler_lock(conn)
    timestamp = labs.now(conn)
    values = dict(slot=slot, generation=generation, state='Starting', heartbeat_at=timestamp,
                  started_at=timestamp, attempt_id=None, completed=0, fault=None)
    conn.execute(insert(workers).values(**values).on_conflict_do_update(index_elements=['slot'], set_=values))
    notify(conn)


def worker_status(conn: sa.Connection, slot: int, generation: UUID, state: str, fault: str | None = None) -> bool:
    result = conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation)
        .values(state=state, heartbeat_at=labs.now(conn), fault=fault, attempt_id=None))
    if result.rowcount:
        notify(conn)
    return bool(result.rowcount)


def fail(conn: sa.Connection, attempt_id: UUID, fault: str, *, expired: bool = False) -> bool:
    row = conn.execute(sa.select(jobs, submissions.c.account_id).join(submissions,
        jobs.c.submission_id == submissions.c.id).where(jobs.c.attempt_id == attempt_id,
        jobs.c.state == 'judging').with_for_update(of=jobs)).mappings().first()
    if not row:
        return False
    attempt = conn.execute(sa.select(attempts).where(attempts.c.id == attempt_id)).mappings().one()
    timestamp = labs.now(conn)
    if expired and attempt['lease_until'] > timestamp:
        return False
    if not expired and attempt['lease_until'] <= timestamp:
        return False
    conn.execute(sa.update(attempts).where(attempts.c.id == attempt_id).values(
        finished_at=timestamp, outcome='expired' if expired else 'fault', fault=fault))
    conn.execute(sa.update(jobs).where(jobs.c.submission_id == row['submission_id']).values(
        state='delayed' if row['attempt_count'] >= row['retry_until'] else 'queued', ready_at=timestamp))
    notify(conn, row['account_id'])
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))
    return True


def recover(conn: sa.Connection) -> None:
    expired = conn.execute(sa.select(attempts.c.id).join(jobs, jobs.c.attempt_id == attempts.c.id)
        .where(jobs.c.state == 'judging', attempts.c.lease_until <= labs.now(conn))
        .with_for_update(of=jobs, skip_locked=True)).scalars().all()
    for attempt_id in expired:
        fail(conn, attempt_id, 'Worker lease expired', expired=True)


def claim(conn: sa.Connection, slot: int, generation: UUID) -> dict | None:
    scheduler_lock(conn)
    worker = conn.execute(sa.select(workers).where(workers.c.slot == slot,
        workers.c.generation == generation)).mappings().first()
    if not worker or worker['state'] not in ('Idle', 'Judging', 'Generating'):
        return None
    recover(conn)
    authoring.recover(conn)
    if worker['attempt_id'] and conn.execute(sa.select(jobs.c.submission_id).where(
            jobs.c.attempt_id == worker['attempt_id'], jobs.c.state == 'judging')).first():
        return None
    if worker['attempt_id'] and authoring.valid(conn, worker['attempt_id']):
        return None
    row = conn.execute(sa.select(submissions, jobs.c.attempt_count, jobs.c.revision_id.label('judge_revision_id')).join(jobs,
        jobs.c.submission_id == submissions.c.id).join(turns, turns.c.account_id == submissions.c.account_id)
        .where(jobs.c.state == 'queued', jobs.c.ready_at <= labs.now(conn))
        .order_by(sa.case((jobs.c.kind == 'initial', 0), else_=1), turns.c.claimed_at.asc().nulls_first(), submissions.c.accepted_at, submissions.c.id)
        .limit(1).with_for_update(of=jobs, skip_locked=True)).mappings().first()
    timestamp = labs.now(conn)
    if not row:
        generated = authoring.claim(conn, slot, generation)
        if generated:
            return generated
        if worker['state'] != 'Idle' or (timestamp - worker['heartbeat_at']).total_seconds() >= 30:
            worker_status(conn, slot, generation, 'Idle')
        return None
    attempt_id = uuid4()
    conn.execute(sa.insert(attempts).values(id=attempt_id, submission_id=row['id'], worker_slot=slot,
        worker_generation=generation, started_at=timestamp, lease_until=timestamp + timedelta(seconds=LEASE_SECONDS)))
    conn.execute(sa.update(jobs).where(jobs.c.submission_id == row['id']).values(
        state='judging', attempt_id=attempt_id, attempt_count=row['attempt_count'] + 1))
    conn.execute(sa.update(turns).where(turns.c.account_id == row['account_id']).values(claimed_at=timestamp))
    conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation).values(
        state='Judging', attempt_id=attempt_id, heartbeat_at=timestamp, fault=None))
    notify(conn, row['account_id'])
    return dict(row) | {'attempt_id': attempt_id, 'revision_id': row['judge_revision_id'] or row['revision_id']}


def heartbeat(conn: sa.Connection, slot: int, generation: UUID, attempt_id: UUID) -> bool:
    row = conn.execute(sa.select(jobs).where(jobs.c.attempt_id == attempt_id, jobs.c.state == 'judging')
                       .with_for_update()).mappings().first()
    if not row:
        return authoring.heartbeat(conn, attempt_id, slot, generation)
    timestamp = labs.now(conn)
    result = conn.execute(sa.update(attempts).where(attempts.c.id == attempt_id,
        attempts.c.worker_slot == slot, attempts.c.worker_generation == generation,
        attempts.c.lease_until > timestamp).values(lease_until=timestamp + timedelta(seconds=LEASE_SECONDS)))
    if not result.rowcount:
        return False
    result = conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation)
                         .values(heartbeat_at=timestamp))
    if not result.rowcount:
        raise RuntimeError('Worker generation replaced')  # Roll back lease renewal too.
    notify(conn)
    return True


def finish(conn: sa.Connection, slot: int, generation: UUID, submission: dict, result: dict) -> bool:
    # Lab-before-job ordering agrees with admin corrections and admission.
    labs.find(conn, submission['lab_id'], shared=True)
    attempt_id = submission['attempt_id']
    job = conn.execute(sa.select(jobs).where(jobs.c.submission_id == submission['id'])
                       .with_for_update()).mappings().one()
    timestamp = labs.now(conn)
    valid = conn.execute(sa.select(attempts.c.id).where(attempts.c.id == attempt_id,
        attempts.c.worker_generation == generation, attempts.c.worker_slot == slot,
        attempts.c.lease_until > timestamp)).first()
    worker = conn.execute(sa.select(workers.c.slot).where(workers.c.slot == slot,
        workers.c.generation == generation).with_for_update()).first()
    if job['state'] != 'judging' or job['attempt_id'] != attempt_id or not valid or not worker:
        return False
    case_rows = result.pop('cases')
    conn.execute(sa.insert(runs).values(id=attempt_id, submission_id=submission['id'],
        revision_id=submission['revision_id'], finished_at=timestamp, **result))
    if case_rows:
        conn.execute(sa.insert(cases), [row | {'run_id': attempt_id} for row in case_rows])
    conn.execute(sa.update(attempts).where(attempts.c.id == attempt_id).values(finished_at=timestamp, outcome='complete'))
    conn.execute(sa.update(jobs).where(jobs.c.submission_id == submission['id']).values(state='complete'))
    if job['batch_id']:
        conn.execute(sa.update(members).where(members.c.batch_id == job['batch_id'],
            members.c.submission_id == submission['id']).values(run_id=attempt_id))
    else:
        conn.execute(insert(reviews).values(submission_id=submission['id'], run_id=attempt_id)
            .on_conflict_do_update(index_elements=['submission_id'], set_={'run_id': attempt_id}))
    conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation).values(
        state='Idle', attempt_id=None, completed=workers.c.completed + 1, heartbeat_at=timestamp, fault=None))
    notify(conn, submission['account_id'])
    return True


def retry(conn: sa.Connection, lab_id: UUID, submission_id: UUID, actor: UUID, reason: str) -> None:
    row = conn.execute(sa.select(jobs, submissions.c.account_id).join(submissions,
        jobs.c.submission_id == submissions.c.id).where(submissions.c.lab_id == lab_id,
        submissions.c.id == submission_id).with_for_update(of=jobs)).mappings().first()
    if not row:
        raise labs.LabError(404, 'Submission not found')
    if row['state'] != 'delayed':
        raise labs.LabError(409, 'Only delayed submissions can be retried')
    conn.execute(sa.update(jobs).where(jobs.c.submission_id == submission_id).values(
        state='queued', retry_until=row['attempt_count'] + 3, ready_at=labs.now(conn)))
    identity.audit(conn, 'submission_retry', actor, row['account_id'],
                   detail={'lab_id': str(lab_id), 'submission_id': str(submission_id), 'reason': reason})
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))
    labs.announce(conn, lab_id, f'Submission {submission_id} judging retry queued. Reason: {reason}', actor, row['account_id'])
    notify(conn, row['account_id'])
