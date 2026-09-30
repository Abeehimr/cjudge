"""Durable teacher generation jobs, isolated from student execution artifacts."""
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4

import sqlalchemy as sa

from cjudge import identity, labs, runner
from cjudge.tasks.authoring import GenerationConfig, AuthoringError, compile_source, generate_case

jobs = sa.Table('authoring_jobs', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('base_version', sa.Integer(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(16), nullable=False, server_default='queued'),
    sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('fault_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('attempt_id', sa.Uuid()),
    sa.Column('diagnostic', sa.Text(), nullable=False, server_default=''),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('accounts.id'), nullable=False),
    sa.CheckConstraint("state IN ('queued','generating','complete','failed','applied','discarded')", name='authoring_state'))
sa.Index('one_open_generation', jobs.c.task_id, unique=True,
         postgresql_where=jobs.c.state.in_(['queued', 'generating', 'complete', 'failed']))
attempts = sa.Table('authoring_attempts', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('job_id', sa.Uuid(), sa.ForeignKey('authoring_jobs.id'), nullable=False),
    sa.Column('worker_slot', sa.Integer(), nullable=False),
    sa.Column('worker_generation', sa.Uuid(), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column('finished_at', sa.DateTime(timezone=True)),
    sa.Column('outcome', sa.String(16)),
    sa.Column('diagnostic', sa.Text()))
cases = sa.Table('authoring_cases', identity.metadata,
    sa.Column('job_id', sa.Uuid(), sa.ForeignKey('authoring_jobs.id'), primary_key=True),
    sa.Column('number', sa.Integer(), primary_key=True),
    sa.Column('seed', sa.BigInteger(), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('input_size', sa.Integer(), nullable=False),
    sa.Column('answer_size', sa.Integer(), nullable=False),
    sa.Column('input_sha256', sa.String(64), nullable=False),
    sa.Column('answer_sha256', sa.String(64), nullable=False))


def artifact_path(job_id: UUID, key: UUID, part: str) -> Path:
    if part not in ('in', 'out', 'reference', 'generator'):
        raise ValueError('Unknown artifact')
    return Path(os.getenv('CJUDGE_AUTHORING_FILES', '/var/lib/cjudge-authoring')) / str(UUID(str(job_id))) / f'{UUID(str(key))}.{part}'


def save(job_id: UUID, key: UUID, part: str, payload: bytes) -> None:
    path = artifact_path(job_id, key, part)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(path.parent, 10001, 10001)
    temporary = path.with_name(uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o400)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), 10001, 10001)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Publish complete bytes without replacing prior artifacts.
    finally:
        temporary.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(job_id: UUID, key: UUID, part: str, maximum: int = 1024 * 1024) -> bytes:
    fd = os.open(artifact_path(job_id, key, part), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise runner.SandboxError('Invalid generation artifact')
        return stream.read(maximum + 1)


def signal(conn: sa.Connection) -> None:
    from cjudge.judging.queue import notify
    notify(conn)
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))


def recover(conn: sa.Connection) -> None:
    expired = conn.execute(sa.select(attempts.c.id).join(jobs, jobs.c.attempt_id == attempts.c.id)
        .where(jobs.c.state == 'generating', attempts.c.lease_until <= labs.now(conn))).scalars().all()
    for key in expired:
        fail(conn, key, 'Worker lease expired', expired=True)


def claim(conn: sa.Connection, slot: int, generation: UUID) -> dict | None:
    from cjudge.submissions import workers
    row = conn.execute(sa.select(jobs).where(jobs.c.state == 'queued').order_by(jobs.c.created_at, jobs.c.id)
                       .limit(1).with_for_update(skip_locked=True)).mappings().first()
    if not row:
        return None
    key = uuid4(); timestamp = labs.now(conn)
    conn.execute(sa.insert(attempts).values(id=key, job_id=row['id'], worker_slot=slot,
        worker_generation=generation, lease_until=timestamp + timedelta(seconds=60)))
    conn.execute(sa.update(jobs).where(jobs.c.id == row['id']).values(state='generating', attempt_id=key))
    conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation)
        .values(state='Generating', attempt_id=key, heartbeat_at=timestamp, fault=None))
    signal(conn)
    return dict(row) | {'attempt_id': key, 'authoring': True}


def valid(conn: sa.Connection, key: UUID) -> dict | None:
    from cjudge.submissions import workers
    return conn.execute(sa.select(jobs, attempts.c.worker_slot, attempts.c.worker_generation)
        .join(attempts, attempts.c.id == jobs.c.attempt_id)
        .join(workers, sa.and_(workers.c.slot == attempts.c.worker_slot,
                              workers.c.generation == attempts.c.worker_generation,
                              workers.c.attempt_id == attempts.c.id))
        .where(attempts.c.id == key, attempts.c.lease_until > labs.now(conn), jobs.c.state == 'generating')
        .with_for_update(of=(jobs, workers))).mappings().first()


def heartbeat(conn: sa.Connection, key: UUID, slot: int, generation: UUID) -> bool:
    from cjudge.submissions import workers
    row = valid(conn, key)
    if not row or row['worker_slot'] != slot or row['worker_generation'] != generation:
        return False
    timestamp = labs.now(conn)
    conn.execute(sa.update(attempts).where(attempts.c.id == key).values(lease_until=timestamp + timedelta(seconds=60)))
    conn.execute(sa.update(workers).where(workers.c.slot == row['worker_slot'],
        workers.c.generation == row['worker_generation']).values(heartbeat_at=timestamp))
    signal(conn)
    return True


def fail(conn: sa.Connection, key: UUID, diagnostic: str, *, expired: bool = False, author_error: bool = False) -> bool:
    row = conn.execute(sa.select(jobs, attempts.c.lease_until).join(attempts, attempts.c.id == jobs.c.attempt_id)
        .where(attempts.c.id == key, jobs.c.state == 'generating').with_for_update(of=jobs)).mappings().first()
    if not row or (row['lease_until'] > labs.now(conn)) == expired:
        return False
    faults = row['fault_count'] + int(not author_error)
    diagnostic = diagnostic[:65536]
    conn.execute(sa.update(jobs).where(jobs.c.id == row['id']).values(
        state='failed' if author_error or faults >= 3 else 'queued', fault_count=faults, diagnostic=diagnostic))
    conn.execute(sa.update(attempts).where(attempts.c.id == key).values(
        finished_at=labs.now(conn), outcome='error' if author_error else 'fault', diagnostic=diagnostic))
    signal(conn)
    return True


def run_case(job: dict) -> dict:
    config = GenerationConfig.model_validate(job['config'])
    # Protected compile cache survives case-level yielding and worker restarts.
    def binary(part: str, source: str) -> bytes:
        path = artifact_path(job['id'], job['id'], part)
        if path.exists():
            return read(job['id'], job['id'], part, 10 * 1024 * 1024)
        content = compile_source(source, part)
        try:
            save(job['id'], job['id'], part, content)
        except FileExistsError:
            return read(job['id'], job['id'], part, 10 * 1024 * 1024)
        return content
    reference = binary('reference', config.reference)
    generator = binary('generator', config.generator) if config.language == 'c' else None
    seed = config.seed + job['progress']
    input_bytes, answer = generate_case(config, seed, reference, generator)
    key = uuid4()
    save(job['id'], key, 'in', input_bytes); save(job['id'], key, 'out', answer)
    return dict(job_id=job['id'], number=job['progress'] + 1, seed=seed, artifact_id=key,
        input_size=len(input_bytes), answer_size=len(answer),
        input_sha256=hashlib.sha256(input_bytes).hexdigest(), answer_sha256=hashlib.sha256(answer).hexdigest())


def checkpoint(conn: sa.Connection, key: UUID, case: dict) -> bool:
    from cjudge.submissions import workers
    row = valid(conn, key)
    if not row or case['job_id'] != row['id'] or case['number'] != row['progress'] + 1:
        return False
    size = conn.execute(sa.select(sa.func.coalesce(sa.func.sum(cases.c.input_size + cases.c.answer_size), 0))
                        .where(cases.c.job_id == row['id'])).scalar_one()
    if size + case['input_size'] + case['answer_size'] > 16 * 1024 * 1024:
        fail(conn, key, 'Generated cases exceed 16 MiB', author_error=True)
    else:
        conn.execute(sa.insert(cases).values(**case))
        conn.execute(sa.update(jobs).where(jobs.c.id == row['id']).values(progress=case['number'], diagnostic='',
            state='complete' if case['number'] == row['config']['count'] else 'queued'))
        conn.execute(sa.update(attempts).where(attempts.c.id == key).values(finished_at=labs.now(conn), outcome='checkpoint'))
    conn.execute(sa.update(workers).where(workers.c.slot == row['worker_slot'], workers.c.generation == row['worker_generation'])
        .values(state='Idle', attempt_id=None, heartbeat_at=labs.now(conn), completed=workers.c.completed + 1))
    signal(conn)
    return True


def staged_cases(conn: sa.Connection, job_id: UUID) -> list[tuple[bytes, bytes]]:
    pairs = []
    for row in conn.execute(sa.select(cases).where(cases.c.job_id == job_id).order_by(cases.c.number)).mappings():
        pair = tuple(read(job_id, row['artifact_id'], part) for part in ('in', 'out'))
        for payload, part in zip(pair, ('input', 'answer')):
            if len(payload) != row[f'{part}_size'] or hashlib.sha256(payload).hexdigest() != row[f'{part}_sha256']:
                raise runner.SandboxError('Generation artifact integrity failed')
        pairs.append(pair)
    return pairs
