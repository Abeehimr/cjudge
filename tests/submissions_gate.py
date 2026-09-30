"""M5 gate against a disposable database; never changes real lab data."""
import os
from pathlib import Path
import secrets
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from sqlalchemy.exc import DBAPIError

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import identity, labs, tasks, submissions
from cjudge.submissions import files, service
from cjudge.judging import queue


def checks() -> None:
    with identity.engine().connect() as conn:
        names = sa.inspect(conn).get_table_names()
        assert all(table.name in names for table in submissions.TABLES)
        assert 'compiler_feedback' in {column['name'] for column in sa.inspect(conn).get_columns('labs')}
    print('PASS: M5 schema and migrations')
    admin_id, student_id, other_id, revision_id, task_id = [uuid4() for _ in range(5)]
    source = b'int main(void) { return 0; }'
    with identity.engine().begin() as conn:
        for role, key in [('admin', admin_id), ('student', student_id), ('student', other_id)]:
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name='Gate', password_hash='unused',
                roll_number=str(key) if role == 'student' else None, encrypted_password=b'unused' if role == 'student' else None))
        config = {'title': 'Gate', 'statement': 'Return zero.'}
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, case_count=1, cases_key=uuid4()))
        lab = labs.create(conn, 'Gate', False, admin_id)
        labs.set_tasks(conn, lab, [revision_id], admin_id)
        labs.enroll(conn, lab, [student_id, other_id], admin_id)
        timestamp = labs.now(conn)
        labs.schedule(conn, labs.find(conn, lab['id']), None, timestamp + timedelta(hours=1), admin_id)
    def upload(student, key, payload=source):
        try:
            with identity.engine().begin() as conn:
                current = labs.find(conn, lab['id'], shared=True)
                enrollment = labs.enrollment(conn, lab['id'], student)
                return service.accept(conn, current, enrollment, revision_id, key, 'main.c', payload, '192.0.2.1')
        except service.SubmissionError as exc:
            return exc.code
    retry_key = uuid4()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: upload(student_id, retry_key), range(2)))
    assert sorted(result[1] for result in results) == [False, True]
    row = results[0][0]
    assert files.read(row) == source and row['client_mac'] is None
    assert upload(student_id, retry_key, b'changed') == 'idempotency_conflict'
    assert upload(student_id, uuid4()) == 'cooldown'
    with identity.engine().begin() as conn:
        for _ in range(3):
            key = uuid4()
            conn.execute(sa.insert(submissions.submissions).values(**(row | {'id': key, 'account_id': other_id,
                'idempotency_key': uuid4(), 'accepted_at': timestamp - timedelta(seconds=60)})))
            conn.execute(sa.insert(submissions.jobs).values(submission_id=key))
    assert upload(other_id, uuid4()) == 'pending_limit'
    with identity.engine().begin() as conn:
        current = labs.find(conn, lab['id'], shared=True)
        labs.freeze(conn, current, student_id, True, 'Gate', admin_id)
    assert upload(student_id, uuid4()) == 'frozen'
    # Existing acceptance recovers while frozen; it is not another upload.
    assert upload(student_id, retry_key)[1] is False
    with identity.engine().begin() as conn:
        conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(ends_at=labs.now(conn)))
    assert upload(student_id, uuid4()) == 'lab_closed'
    assert upload(student_id, retry_key)[1] is False
    with identity.engine().connect() as conn:
        try:
            conn.execute(sa.update(submissions.submissions).where(submissions.submissions.c.id == row['id']).values(client_ip='192.0.2.2'))
        except DBAPIError:
            conn.rollback()
        else:
            raise AssertionError('Accepted evidence changed')
    orphan = uuid4()
    files.save(orphan, source)
    assert files.cleanup() == 1 and files.read(row) == source
    print('PASS: atomic admission, duplicate retries, cooldown, pending limit, freeze, deadline, immutable IP, orphan cleanup')
    with identity.engine().begin() as conn:
        conn.execute(sa.insert(submissions.turns).values(account_id=other_id))
        generation_a, generation_b = uuid4(), uuid4()
        for slot, generation in [(0, generation_a), (1, generation_b)]:
            queue.register(conn, slot, generation)
            queue.worker_status(conn, slot, generation, 'Idle')
        a = queue.claim(conn, 0, generation_a)
        b = queue.claim(conn, 1, generation_b)
        assert a['id'] != b['id'] and a['account_id'] != b['account_id']
        assert queue.heartbeat(conn, 0, generation_a, a['attempt_id'])
        assert not queue.heartbeat(conn, 0, uuid4(), a['attempt_id'])
        conn.execute(sa.update(submissions.attempts).where(submissions.attempts.c.id == a['attempt_id'])
                     .values(lease_until=labs.now(conn) - timedelta(seconds=1)))
        assert not queue.heartbeat(conn, 0, generation_a, a['attempt_id'])
        queue.recover(conn)
        assert not queue.finish(conn, 0, generation_a, a, {})
        assert queue.fail(conn, b['attempt_id'], 'Synthetic infrastructure failure')
        assert not queue.fail(conn, b['attempt_id'], 'Duplicate failure')
    # Exhaust the live job's retry budget without inventing a student zero.
    with identity.engine().begin() as conn:
        conn.execute(sa.update(submissions.jobs).where(submissions.jobs.c.submission_id == a['id'])
                     .values(attempt_count=2, retry_until=3))
        conn.execute(sa.update(submissions.jobs).where(submissions.jobs.c.submission_id != a['id'])
                     .values(ready_at=labs.now(conn) + timedelta(hours=1)))
        active = queue.claim(conn, 0, generation_a)
        assert active['id'] == a['id']
        assert queue.fail(conn, active['attempt_id'], 'Synthetic infrastructure failure')
        assert conn.execute(sa.select(submissions.jobs.c.state).where(
            submissions.jobs.c.submission_id == a['id'])).scalar_one() == 'delayed'
        assert conn.execute(sa.select(sa.func.count()).select_from(submissions.runs)).scalar_one() == 0
        queue.retry(conn, lab['id'], a['id'], admin_id, 'Infrastructure repaired')
        active = queue.claim(conn, 0, generation_a)
        result = dict(verdict='AC', passed=1, total=1, score_numerator='100', score_denominator='1',
                      compiler_feedback='', compiler_truncated=False, cases=[])
        assert queue.finish(conn, 0, generation_a, active, result)
        assert not queue.finish(conn, 0, generation_a, active, {})
    print('PASS: fair distinct claims, lease fencing, stale writes, retry exhaustion, admin retry, atomic publication')


def main() -> None:
    database = 'submission_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        with tempfile.TemporaryDirectory() as directory:
            os.environ['CJUDGE_SUBMISSION_FILES'] = directory
            checks()
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
