"""M5 gate against a disposable database; never changes real lab data."""
import json
import subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import os
from pathlib import Path
import secrets
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
import time
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
        for _ in range(2):
            key = uuid4()
            conn.execute(sa.insert(submissions.submissions).values(**(row | {'id': key, 'account_id': other_id,
                'idempotency_key': uuid4(), 'accepted_at': timestamp - timedelta(seconds=60)})))
            conn.execute(sa.insert(submissions.jobs).values(submission_id=key))
    with ThreadPoolExecutor(2) as pool:
        pending_race = list(pool.map(lambda _: upload(other_id, uuid4()), range(2)))
    assert sum(isinstance(result, tuple) for result in pending_race) == 1
    assert 'pending_limit' in pending_race
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
    with identity.engine().begin() as conn:
        short = labs.create(conn, 'Deadline durability', False, admin_id)
        labs.set_tasks(conn, short, [revision_id], admin_id)
        labs.enroll(conn, short, [student_id], admin_id)
        timestamp = labs.now(conn)
        labs.schedule(conn, labs.find(conn, short['id']), None, timestamp + timedelta(seconds=2), admin_id)
    original_save = files.save
    def delayed_save(key, source):
        original_save(key, source)
        time.sleep(.25)
    with identity.engine().begin() as conn:
        conn.execute(sa.update(labs.labs).where(labs.labs.c.id == short['id'])
                     .values(ends_at=labs.now(conn) + timedelta(seconds=.1)))
    try:
        with identity.engine().begin() as conn, patch('cjudge.submissions.files.save', side_effect=delayed_save):
            service.accept(conn, labs.find(conn, short['id'], shared=True),
                labs.enrollment(conn, short['id'], student_id), revision_id, uuid4(), 'late.c', source, '192.0.2.1')
    except labs.LabError:
        pass
    else:
        raise AssertionError('Source became durable after deadline but was accepted')
    with identity.engine().begin() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(submissions.submissions).where(
            submissions.submissions.c.lab_id == short['id'])).scalar_one() == 0
        conn.execute(sa.update(labs.labs).where(labs.labs.c.id == short['id']).values(ends_at=labs.now(conn) + timedelta(seconds=10)))
    try:
        with identity.engine().begin() as conn, patch('cjudge.submissions.files.save', side_effect=OSError('Synthetic disk full')):
            service.accept(conn, labs.find(conn, short['id'], shared=True),
                labs.enrollment(conn, short['id'], student_id), revision_id, uuid4(), 'disk.c', source, '192.0.2.1')
    except OSError:
        pass
    else:
        raise AssertionError('Failed storage accepted')
    print('PASS: durability deadline boundary and storage failure rollback')


def history_checks() -> None:
    from cjudge.api import app
    from cjudge.labs.binding import cookie_name
    admin_id, student_id, other_id, lab_id, task_id, revision_a, revision_b = [uuid4() for _ in range(7)]
    admin_token, student_token, binding = [secrets.token_urlsafe(32) for _ in range(3)]
    with identity.engine().begin() as conn:
        timestamp = labs.now(conn)
        admin_id = conn.execute(sa.select(identity.accounts.c.id).where(identity.accounts.c.role == 'admin')).scalar_one()
        conn.execute(sa.update(labs.labs).where(labs.labs.c.ends_at > timestamp).values(ends_at=timestamp))
        for role, key in [('student', student_id), ('student', other_id)]:
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name='History gate', password_hash='unused',
                roll_number=str(key) if role == 'student' else None, encrypted_password=b'unused' if role == 'student' else None))
        for key, token in [(admin_id, admin_token), (student_id, student_token)]:
            conn.execute(sa.insert(identity.sessions).values(account_id=key, token_hash=identity.token_digest(token),
                csrf_token='unused', expires_at=timestamp + timedelta(hours=1)))
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='History gate', version=1, starts_at=timestamp,
            ends_at=timestamp + timedelta(hours=1)))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student_id, binding_hash=identity.token_digest(binding)))
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config={'title': 'History'}, case_count=1))
        for number, revision in enumerate([revision_a, revision_b], 1):
            conn.execute(sa.insert(tasks.revisions).values(id=revision, task_id=task_id, number=number,
                draft_version=number, config={'title': 'History'}, case_count=1, cases_key=uuid4()))
        for index in range(106):
            key = uuid4()
            source = b'<script>alert(1)</script>\xff'
            digest = files.validate('main.c', source)
            if index == 0:
                detail_id = key
                files.save(key, source)
            conn.execute(sa.insert(submissions.submissions).values(id=key, lab_id=lab_id,
                account_id=other_id if index == 105 else student_id, revision_id=revision_a if index < 103 or index == 105 else revision_b,
                idempotency_key=uuid4(), filename='main.c', sha256=digest, size=len(source),
                accepted_at=timestamp + timedelta(microseconds=index), client_ip='192.0.2.1'))
            conn.execute(sa.insert(submissions.jobs).values(submission_id=key))
        attempt_id = uuid4()
        conn.execute(sa.insert(submissions.attempts).values(id=attempt_id, submission_id=detail_id,
            worker_slot=0, worker_generation=uuid4(), started_at=timestamp, lease_until=timestamp + timedelta(seconds=60)))
        conn.execute(sa.insert(submissions.runs).values(id=attempt_id, submission_id=detail_id, revision_id=revision_a,
            verdict='WA', passed=0, total=1, score_numerator='0', score_denominator='1',
            compiler_feedback='', compiler_truncated=False, finished_at=timestamp))
        conn.execute(sa.insert(submissions.cases).values(run_id=attempt_id, number=1, verdict='WA',
            cpu_seconds=.1, wall_seconds=.2, memory_kib=1024, stdout=b'<img src=x>\xff', stderr=b'diagnostic',
            stdout_truncated=True, stderr_truncated=False))
        conn.execute(sa.update(submissions.jobs).where(submissions.jobs.c.submission_id == detail_id)
            .values(state='complete', attempt_id=attempt_id, attempt_count=1))
    def get(path, headers=None):
        try:
            response = urlopen(Request('http://127.0.0.1:8016' + path, headers=headers or {}), timeout=10)
        except HTTPError as exc:
            response = exc
        return response.code, json.loads(response.read())
    server = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1',
        '--port', '8016', '--no-proxy-headers'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if get('/api/auth/session')[0] == 401:
                    break
            except URLError:
                time.sleep(.1)
        else:
            raise AssertionError('History gate API failed to start')
        student_headers = {'Cookie': f'cjudge_session={student_token}; {cookie_name(lab_id)}={binding}'}
        admin_headers = {'Cookie': f'cjudge_session={admin_token}'}
        path = f'/api/labs/{lab_id}/submissions?revision_id={revision_a}'
        status, rows = get(path, student_headers)
        assert status == 200, rows
        assert len(rows) == 100 and all(row['revision_id'] == str(revision_a) for row in rows)
        assert rows == sorted(rows, key=lambda row: row['accepted_at'], reverse=True)
        assert not {'client_ip', 'client_mac', 'account_id', 'passed'} & rows[0].keys()
        assert len(get(path + '&offset=100', student_headers)[1]) == 3
        assert get(path + '&account_id=' + str(other_id), student_headers)[1] == rows
        admin_path = f'/api/admin/labs/{lab_id}/submissions?revision_id={revision_a}&account_id={student_id}'
        assert len(get(admin_path + '&offset=100', admin_headers)[1]) == 3
        assert len(get(admin_path.replace(str(student_id), str(other_id)), admin_headers)[1]) == 1
        assert get(admin_path, student_headers)[0] == 403
        detail_path = f'/api/admin/labs/{lab_id}/submissions/{detail_id}'
        status, detail = get(detail_path, admin_headers)
        assert status == 200 and detail['source'] == source.decode('utf-8', errors='replace'), detail
        assert detail['client_ip'] == '192.0.2.1' and detail['status'] == 'Failed'
        assert len(detail['cases']) == 1 and detail['cases'][0]['stdout'] == '<img src=x>\ufffd'
        assert detail['cases'][0]['stdout_truncated'] and detail['cases'][0]['verdict'] == 'WA'
        assert get(detail_path, student_headers)[0] == 403
        assert get(detail_path)[0] == 401
        assert get(detail_path.replace(str(lab_id), str(uuid4())), admin_headers)[0] == 404
        assert get(detail_path.replace(str(detail_id), str(uuid4())), admin_headers)[0] == 404
        student_detail = get(f'/api/labs/{lab_id}/submissions/{detail_id}', student_headers)[1]
        assert not {'source', 'cases', 'passed', 'client_ip'} & student_detail.keys()
        assert get(path)[0] == 401
        assert get(path.replace(str(revision_a), 'invalid'), student_headers)[0] == 422
        assert get(path.replace(str(lab_id), str(uuid4())), student_headers)[0] == 404
        assert get(path, {'Cookie': f'cjudge_session={student_token}'})[0] == 423
    finally:
        server.terminate()
        server.wait(timeout=10)
    print('PASS: history filters, admin source/case details, student secrecy, ownership and binding')


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
            history_checks()
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
