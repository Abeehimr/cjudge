"""Admin-only task test runs; these tables never participate in lab grading."""
from datetime import timedelta
import hashlib
import io
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4
import zipfile
import zlib

import sqlalchemy as sa

from cjudge import identity, labs, runner, tasks
from cjudge.submissions.files import SOURCE_BYTES, validate, language_for
from cjudge.tasks.grading import TaskConfig, compare_output
from cjudge.tasks.restrictions import first_banned
from cjudge.tasks.authoring import check_python

BATCH_LIMIT = 20
ZIP_LIMIT = 16 * 1024 * 1024
OUTSTANDING_LIMIT = 40

batches = sa.Table('tester_batches', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id'), nullable=False),
    sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id'), nullable=False),
    sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('accounts.id'), nullable=False),
    sa.Column('idempotency_key', sa.String(128)),
    sa.Column('payload_sha256', sa.String(64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column('deleted_at', sa.DateTime(timezone=True)),
    sa.Column('delete_reason', sa.Text()))
sa.Index('tester_idempotency', batches.c.actor_id, batches.c.idempotency_key, unique=True,
    postgresql_where=batches.c.idempotency_key.is_not(None))
sources = sa.Table('tester_sources', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('batch_id', sa.Uuid(), sa.ForeignKey('tester_batches.id'), nullable=False),
    sa.Column('filename', sa.String(160), nullable=False),
    sa.Column('language', sa.String(8), nullable=False, server_default='c11'),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(64), nullable=False),
    sa.Column('state', sa.String(16), nullable=False, server_default='queued'),
    sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('passed', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('fault_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('attempt_id', sa.Uuid()),
    sa.Column('last_claimed_at', sa.DateTime(timezone=True)),
    sa.Column('compiler_feedback', sa.Text(), nullable=False, server_default=''),
    sa.Column('compiler_truncated', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('restriction', sa.JSON()),
    sa.Column('diagnostic', sa.Text(), nullable=False, server_default=''),
    sa.CheckConstraint("state IN ('queued','testing','complete','failed')", name='tester_state'))
attempts = sa.Table('tester_attempts', identity.metadata,
    sa.Column('id', sa.Uuid(), primary_key=True),
    sa.Column('source_id', sa.Uuid(), sa.ForeignKey('tester_sources.id'), nullable=False),
    sa.Column('worker_slot', sa.Integer(), nullable=False),
    sa.Column('worker_generation', sa.Uuid(), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column('finished_at', sa.DateTime(timezone=True)),
    sa.Column('outcome', sa.String(16)))
cases = sa.Table('tester_cases', identity.metadata,
    sa.Column('source_id', sa.Uuid(), sa.ForeignKey('tester_sources.id'), primary_key=True),
    sa.Column('number', sa.Integer(), primary_key=True),
    sa.Column('verdict', sa.String(16), nullable=False),
    sa.Column('cpu_seconds', sa.Float(), nullable=False),
    sa.Column('wall_seconds', sa.Float(), nullable=False),
    sa.Column('memory_kib', sa.Integer(), nullable=False),
    sa.Column('stdout', sa.LargeBinary(), nullable=False),
    sa.Column('stderr', sa.LargeBinary(), nullable=False),
    sa.Column('stdout_truncated', sa.Boolean(), nullable=False),
    sa.Column('stderr_truncated', sa.Boolean(), nullable=False))


def parse_sources(filename: str, payload: bytes, *, archive: bool) -> list[tuple[str, bytes]]:
    if not archive:
        validate(filename, payload)
        return [(filename, payload)]
    if len(payload) > ZIP_LIMIT:
        raise ValueError('ZIP exceeds 16 MiB')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            entries = bundle.infolist()
            if not 1 <= len(entries) <= BATCH_LIMIT:
                raise ValueError('ZIP must contain 1–20 source files')
            result = []
            names = set()
            for entry in entries:
                name = entry.orig_filename
                if name in names or entry.filename != name:
                    raise ValueError('Duplicate ZIP entry')
                names.add(name)
                language_for(name)
                kind = stat.S_IFMT(entry.external_attr >> 16)
                if kind not in (0, stat.S_IFREG) or entry.flag_bits & 1:
                    raise ValueError('Only unencrypted regular files allowed')
                if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('Only stored/deflated entries allowed')
                if not 0 < entry.file_size <= SOURCE_BYTES:
                    raise ValueError('Source exceeds 64 KiB')
                with bundle.open(entry) as stream:
                    content = stream.read(SOURCE_BYTES + 1)
                if len(content) != entry.file_size:
                    raise ValueError('Invalid ZIP entry size')
                validate(name, content)
                result.append((name, content))
            return result
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, zlib.error) as exc:
        raise ValueError('Invalid ZIP archive') from exc


def path(batch_id: UUID, source_id: UUID, part: str) -> Path:
    if part not in ('c', 'bin'):
        raise ValueError('Unknown tester artifact')
    root = Path(os.getenv('CJUDGE_AUTHORING_FILES', '/var/lib/cjudge-authoring'))
    return root / 'tester' / str(UUID(str(batch_id))) / f'{UUID(str(source_id))}.{part}'


def save(batch_id: UUID, source_id: UUID, part: str, payload: bytes) -> None:
    destination = path(batch_id, source_id, part)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(destination.parent, 10001, 10001)
    temporary = destination.with_name(uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o400)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), 10001, 10001)
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(destination.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read(row: dict, part: str) -> bytes:
    maximum = SOURCE_BYTES if part == 'c' else 10 * 1024 * 1024
    descriptor = os.open(path(row['batch_id'], row['id'], part), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise OSError('Invalid tester artifact')
        data = stream.read(maximum + 1)
    if part == 'c' and (len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']):
        raise OSError('Tester source integrity failed')
    return data


def signal(conn: sa.Connection) -> None:
    from cjudge.judging.queue import notify
    notify(conn)
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))


def valid(conn: sa.Connection, key: UUID) -> dict | None:
    from cjudge.submissions import workers
    return conn.execute(sa.select(sources, attempts.c.worker_slot, attempts.c.worker_generation)
        .join(attempts, attempts.c.id == sources.c.attempt_id)
        .join(workers, sa.and_(workers.c.slot == attempts.c.worker_slot,
            workers.c.generation == attempts.c.worker_generation, workers.c.attempt_id == key))
        .where(attempts.c.id == key, attempts.c.lease_until > labs.now(conn), sources.c.state == 'testing')
        .with_for_update(of=(sources, workers))).mappings().first()


def claim(conn: sa.Connection, slot: int, generation: UUID) -> dict | None:
    from cjudge.submissions import workers
    row = conn.execute(sa.select(sources, batches.c.revision_id).join(batches, batches.c.id == sources.c.batch_id)
        .where(sources.c.state == 'queued', batches.c.deleted_at.is_(None))
        .order_by(sources.c.last_claimed_at.asc().nulls_first(), batches.c.created_at, sources.c.id)
        .limit(1).with_for_update(of=sources, skip_locked=True)).mappings().first()
    if not row:
        return None
    key, timestamp = uuid4(), labs.now(conn)
    conn.execute(sa.insert(attempts).values(id=key, source_id=row['id'], worker_slot=slot,
        worker_generation=generation, lease_until=timestamp + timedelta(seconds=60)))
    conn.execute(sa.update(sources).where(sources.c.id == row['id']).values(
        state='testing', attempt_id=key, last_claimed_at=timestamp))
    conn.execute(sa.update(workers).where(workers.c.slot == slot, workers.c.generation == generation)
        .values(state='Testing', attempt_id=key, heartbeat_at=timestamp, fault=None))
    signal(conn)
    return dict(row) | {'attempt_id': key, 'tester': True}


def heartbeat(conn: sa.Connection, key: UUID, slot: int, generation: UUID) -> bool:
    from cjudge.submissions import workers
    row = valid(conn, key)
    if not row or row['worker_slot'] != slot or row['worker_generation'] != generation:
        return False
    timestamp = labs.now(conn)
    conn.execute(sa.update(attempts).where(attempts.c.id == key).values(lease_until=timestamp + timedelta(seconds=60)))
    conn.execute(sa.update(workers).where(workers.c.slot == slot,
        workers.c.generation == generation).values(heartbeat_at=timestamp))
    signal(conn)
    return True


def fail(conn: sa.Connection, key: UUID, diagnostic: str, *, expired: bool = False) -> bool:
    row = conn.execute(sa.select(sources, attempts.c.lease_until).join(attempts, attempts.c.id == sources.c.attempt_id)
        .where(attempts.c.id == key, sources.c.state == 'testing').with_for_update(of=sources)).mappings().first()
    if not row or (row['lease_until'] > labs.now(conn)) == expired:
        return False
    faults = row['fault_count'] + 1
    conn.execute(sa.update(sources).where(sources.c.id == row['id']).values(
        state='failed' if faults >= 3 else 'queued', fault_count=faults, diagnostic=diagnostic[:1024]))
    conn.execute(sa.update(attempts).where(attempts.c.id == key).values(finished_at=labs.now(conn), outcome='fault'))
    signal(conn)
    return True


def recover(conn: sa.Connection) -> None:
    expired = conn.execute(sa.select(attempts.c.id).join(sources, sources.c.attempt_id == attempts.c.id)
        .where(sources.c.state == 'testing', attempts.c.lease_until <= labs.now(conn))).scalars().all()
    for key in expired:
        fail(conn, key, 'Worker lease expired', expired=True)


def run_case(job: dict) -> dict:
    with identity.engine().connect() as conn:
        revision = conn.execute(sa.select(tasks.revisions).where(tasks.revisions.c.id == job['revision_id'])).mappings().one()
    config = TaskConfig.model_validate(revision['config'])
    pairs = tasks.load_cases(revision['cases_key'])
    if not pairs or len(pairs) != revision['case_count']:
        raise runner.SandboxError('Invalid test artifacts')
    if job['progress'] == 0:
        source = read(job, 'c')
        restriction = first_banned(source, config.banned_identifiers, job.get('language', 'c11'))
        if restriction:
            return dict(kind='compile', verdict='Restricted', compiler_feedback='',
                compiler_truncated=False, restriction={'identifier': restriction[0], 'line': restriction[1]})
        compiled = runner.compile_source(source, job.get('language', 'c11'))
        result = dict(kind='compile', verdict=compiled.verdict,
            compiler_feedback=compiled.stderr.decode('utf-8', errors='replace')[:65536],
            compiler_truncated=compiled.stderr_truncated)
        if compiled.verdict == 'OK':
            try:
                save(job['batch_id'], job['id'], 'bin', compiled.executable)
            except FileExistsError:
                pass  # A previous lease may have published the same source binary.
        return result
    number = job['progress']
    input_bytes, answer = pairs[number - 1]
    limits = runner.Limits(cpu_seconds=config.cpu_seconds, wall_seconds=config.wall_seconds,
        memory_kib=config.memory_mib * 1024, stack_kib=config.stack_mib * 1024,
        stdout_bytes=config.stdout_mib * 1024 * 1024)
    execution = runner.execute(read(job, 'bin'), input_bytes, limits)
    verdict = execution.verdict
    if verdict == 'OK':
        accepted = (check_python(config.checker.source, input_bytes, execution.stdout, answer)
            if config.checker.kind == 'python' else compare_output(execution.stdout, answer, config.checker))
        verdict = 'AC' if accepted else 'WA'
    return dict(kind='case', number=number, verdict=verdict, cpu_seconds=execution.cpu_seconds,
        wall_seconds=execution.wall_seconds, memory_kib=execution.memory_kib,
        stdout=execution.stdout_preview, stderr=execution.stderr,
        stdout_truncated=execution.stdout_truncated, stderr_truncated=execution.stderr_truncated)


def checkpoint(conn: sa.Connection, key: UUID, result: dict) -> bool:
    from cjudge.submissions import workers
    row = valid(conn, key)
    if not row:
        return False
    total = conn.execute(sa.select(tasks.revisions.c.case_count).join(batches,
        batches.c.revision_id == tasks.revisions.c.id).where(batches.c.id == row['batch_id'])).scalar_one()
    timestamp = labs.now(conn)
    if result['kind'] == 'compile' and row['progress'] == 0:
        finished = result['verdict'] in ('CE', 'Restricted')
        conn.execute(sa.update(sources).where(sources.c.id == row['id']).values(
            progress=0 if finished else 1, state='complete' if finished else 'queued',
            compiler_feedback=result['compiler_feedback'], compiler_truncated=result['compiler_truncated'],
            restriction=result.get('restriction'), diagnostic=''))
    elif result['kind'] == 'case' and result['number'] == row['progress']:
        conn.execute(sa.insert(cases).values(source_id=row['id'], **{k: v for k, v in result.items() if k != 'kind'}))
        conn.execute(sa.update(sources).where(sources.c.id == row['id']).values(
            progress=row['progress'] + 1, passed=row['passed'] + int(result['verdict'] == 'AC'),
            state='complete' if row['progress'] == total else 'queued', diagnostic=''))
    else:
        return False
    conn.execute(sa.update(attempts).where(attempts.c.id == key).values(finished_at=timestamp, outcome='checkpoint'))
    conn.execute(sa.update(workers).where(workers.c.slot == row['worker_slot'], workers.c.generation == row['worker_generation'])
        .values(state='Idle', attempt_id=None, heartbeat_at=timestamp, completed=workers.c.completed + 1))
    signal(conn)
    return True
