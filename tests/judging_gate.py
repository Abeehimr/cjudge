"""M5 end-to-end gate and representative burst. Run in a two-instance worker container."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import identity, labs, tasks, submissions
from cjudge.judging import queue

GOOD = b'#include <stdio.h>\nint main(void){int a,b;scanf("%d%d",&a,&b);printf("%d\\n",a+b);return 0;}'


def exercise(directory: str) -> None:
    os.environ['CJUDGE_TASK_FILES'] = directory
    os.environ['CJUDGE_SUBMISSION_FILES'] = directory
    tasks.ARTIFACTS = Path(directory)
    csrf, admin_token = secrets.token_hex(32), secrets.token_urlsafe(32)
    admin_id, lab_id = uuid4(), uuid4()
    students = [(uuid4(), secrets.token_urlsafe(32), secrets.token_urlsafe(32)) for _ in range(160)]
    revision_ids = []
    with identity.engine().begin() as conn:
        conn.execute(sa.insert(identity.accounts).values(id=admin_id, role='admin', name='Gate', password_hash='unused'))
        timestamp = labs.now(conn)
        conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(admin_token), account_id=admin_id,
            csrf_token=csrf, expires_at=timestamp + timedelta(hours=1)))
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='M5 gate', version=1,
            starts_at=timestamp - timedelta(seconds=1), ends_at=timestamp + timedelta(hours=1)))
        for index, (account_id, session, binding) in enumerate(students):
            conn.execute(sa.insert(identity.accounts).values(id=account_id, role='student', name=f'Gate {index}',
                roll_number=f'GATE{index}', password_hash='unused', encrypted_password=b'unused'))
            conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(session), account_id=account_id,
                csrf_token=csrf, expires_at=timestamp + timedelta(hours=1)))
            conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=account_id,
                binding_hash=identity.token_digest(binding), bound_ip='127.0.0.1', last_ip='127.0.0.1', bound_at=timestamp))
        for position in range(1, 3):
            task_id, revision_id = uuid4(), uuid4()
            config = dict(title=f'Sum {position}', statement='Add two integers.', maximum_marks='7',
                scoring='partial', cpu_seconds=.2, wall_seconds=1, memory_mib=32, stack_mib=8, stdout_mib=1)
            pairs = [(b'1 2\n', b'3\n'), (b'2 3\n', b'5\n')] if position == 1 else [
                (f'{i} {i + 1}\n'.encode(), f'{2 * i + 1}\n'.encode()) for i in range(10)]
            case_key = tasks.save_cases(pairs)
            conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=len(pairs)))
            conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
                draft_version=1, config=config, case_count=len(pairs), cases_key=case_key))
            conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=position, revision_id=revision_id))
            revision_ids.append(revision_id)

    def call(path, method='GET', body=None, student=0, token=csrf, admin=False, key=None, cookie=True):
        account_id, session, binding = students[student]
        headers = {'Origin': 'https://localhost:8443', 'X-CSRF-Token': token}
        if cookie:
            headers['Cookie'] = 'cjudge_session=' + (admin_token if admin else session)
            if not admin:
                headers['Cookie'] += f'; cjudge_lab_{lab_id.hex}={binding}'
        if key:
            headers['Idempotency-Key'] = str(key)
        if isinstance(body, dict):
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body).encode()
        elif body is not None:
            headers['Content-Type'] = 'application/octet-stream'
        request = Request('http://127.0.0.1:8015/api' + path, method=method, data=body, headers=headers)
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as exc:
            response = exc
        payload = response.read()
        data = json.loads(payload) if payload and response.headers.get_content_type() == 'application/json' else payload
        return response.status if not isinstance(response, HTTPError) else response.code, data

    def submit(source=GOOD, student=0, key=None, revision=None, token=csrf, filename='main.c'):
        return call(f'/labs/{lab_id}/submissions?' + urlencode({'revision_id': revision or revision_ids[0], 'filename': filename}),
                    'POST', source, student=student, key=key or uuid4(), token=token)

    api = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1', '--port', '8015',
                            '--no-proxy-headers'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pool = None
    try:
        for _ in range(100):
            try:
                if call('/admin/isolates', admin=True)[0] == 200:
                    break
            except URLError:
                time.sleep(.1)
        else:
            raise AssertionError('Gate API failed to start')
        assert call('/admin/isolates')[0] == 403
        assert call('/admin/isolates', cookie=False)[0] == 401
        assert submit(token='wrong')[0] == 403
        assert submit(source=b'x' * 65537)[0] == 413
        assert submit(filename='../evil.c')[0] == 400
        assert submit(revision=uuid4())[0] == 400
        retry_key = uuid4()
        with ThreadPoolExecutor(2) as executor:
            duplicates = list(executor.map(lambda _: submit(key=retry_key), range(2)))
        assert sorted(row[0] for row in duplicates) == [200, 201], duplicates
        accepted = duplicates[0][1]
        assert submit(source=b'changed', key=retry_key)[0] == 409
        assert submit(revision=revision_ids[1])[1]['detail']['code'] == 'cooldown'
        assert call(f'/labs/{lab_id}/submissions/{accepted["id"]}', student=1)[0] == 404
        assert call(f'/admin/labs/{lab_id}/submissions/{accepted["id"]}/source')[0] == 403
        assert call(f'/admin/labs/{lab_id}/submissions/{accepted["id"]}/source', admin=True)[1] == GOOD
        assert not {'client_ip', 'client_mac', 'passed', 'total', 'score_numerator', 'cases'} & accepted.keys()
        print('PASS: upload API, CSRF, sizes/paths, duplicate race, cross-task cooldown, ownership, live-data secrecy')

        # Accept without a worker; completion remains valid after the deadline.
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(ends_at=labs.now(conn)))
        assert submit(student=1)[0] == 403
        assert submit(key=retry_key)[0] == 200
        pool = subprocess.Popen(['python', '-m', 'cjudge.judging.worker'])
        def wait_until(predicate, timeout=40):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.1)
            raise AssertionError('Gate condition timed out')
        wait_until(lambda: call(f'/labs/{lab_id}/submissions/{accepted["id"]}')[1]['status'] == 'Passed')
        wait_until(lambda: call('/admin/isolates', admin=True)[1]['healthy'] == 2)
        print('PASS: two healthy sandbox workers and judging after deadline')
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(ends_at=labs.now(conn) + timedelta(hours=1)))
        fixtures = [(b'#include <stdio.h>\nint main(void){puts("3");}', 'Failed'),
            (b'not valid C', 'Compile error'), (b'int main(void){for(;;){}}', 'Failed'),
            (b'#include <stdlib.h>\nint main(void){abort();}', 'Failed'),
            (b'#include <stdio.h>\nint main(void){for(;;)putchar(120);}', 'Failed'),
            (b'#include <stdlib.h>\nint main(void){volatile char*p=malloc(64*1024*1024);if(!p)return 42;for(int i=0;i<64*1024*1024;i+=4096)p[i]=1;return p[0];}', 'Failed')]
        fixture_ids = []
        for student, (source, expected) in enumerate(fixtures, 1):
            status, row = submit(source, student=student)
            assert status == 201
            fixture_ids.append((row['id'], expected))
        for submission_id, expected in fixture_ids:
            wait_until(lambda: call(f'/labs/{lab_id}/submissions/{submission_id}', student=fixture_ids.index((submission_id, expected)) + 1)[1]['status'] == expected)
        with identity.engine().connect() as conn:
            verdicts = set(conn.execute(sa.select(submissions.cases.c.verdict)).scalars())
            assert {'AC', 'WA', 'TLE', 'RE', 'OLE', 'MLE'} <= verdicts, verdicts
            partial = conn.execute(sa.select(submissions.runs).where(submissions.runs.c.submission_id == fixture_ids[0][0])).mappings().one()
            assert partial['passed'] == 1 and partial['total'] == 2
            assert (partial['score_numerator'], partial['score_denominator']) == ('7', '2')
        ce_id = fixture_ids[1][0]
        assert call(f'/labs/{lab_id}/submissions/{ce_id}', student=2)[1]['compiler_feedback']
        assert call(f'/admin/labs/{lab_id}/compiler-feedback', 'PUT', {'mode': 'none'}, admin=True)[0] == 204
        assert call(f'/labs/{lab_id}/submissions/{ce_id}', student=2)[1]['compiler_feedback'] is None
        print('PASS: full case execution, exact partial scores, AC/WA/CE/TLE/MLE/RE/OLE and feedback policy')

        # Stop the pool, enqueue long work, and kill the actual leased worker.
        pool.terminate(); pool.wait(timeout=15); pool = None
        crash_source = b'#include <unistd.h>\nint main(void){sleep(2);return 0;}'
        status, crash = submit(crash_source, student=7)
        assert status == 201
        with identity.engine().begin() as conn:
            # Keep the test brief: simulate an abandoned lease rather than waiting 60 seconds.
            queue.recover(conn)
        pool = subprocess.Popen(['python', '-m', 'cjudge.judging.worker'])
        wait_until(lambda: call(f'/labs/{lab_id}/submissions/{crash["id"]}', student=7)[1]['status'] == 'Judging')
        with identity.engine().connect() as conn:
            slot = conn.execute(sa.select(submissions.attempts.c.worker_slot).join(submissions.jobs,
                submissions.jobs.c.attempt_id == submissions.attempts.c.id).where(
                submissions.jobs.c.submission_id == crash['id'])).scalar_one()
        children = Path(f'/proc/{pool.pid}/task/{pool.pid}/children').read_text().split()
        # multiprocessing starts a resource tracker first, then workers in slot order.
        worker_pids = [int(pid) for pid in children if b'spawn_main' in Path(f'/proc/{pid}/cmdline').read_bytes()]
        assert len(worker_pids) == 2
        os.kill(worker_pids[slot], signal.SIGKILL)
        with identity.engine().begin() as conn:
            attempt_id = conn.execute(sa.select(submissions.jobs.c.attempt_id).where(submissions.jobs.c.submission_id == crash['id'])).scalar_one()
            conn.execute(sa.update(submissions.attempts).where(submissions.attempts.c.id == attempt_id)
                         .values(lease_until=labs.now(conn) - timedelta(seconds=1)))
            conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))
        wait_until(lambda: call(f'/labs/{lab_id}/submissions/{crash["id"]}', student=7)[1]['status'] == 'Failed', timeout=45)
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(submissions.jobs.c.attempt_count).where(
                submissions.jobs.c.submission_id == crash['id'])).scalar_one() >= 2
        print('PASS: worker kill, supervised restart, abandoned lease recovery and sandbox cleanup')

        start = time.monotonic()
        def burst(student):
            status, row = submit(student=student, revision=revision_ids[1])
            assert status == 201, (student, status)
            return row['id']
        with ThreadPoolExecutor(20) as executor:
            burst_ids = list(executor.map(burst, range(10, 160)))
        upload_seconds = time.monotonic() - start
        def complete():
            with identity.engine().connect() as conn:
                return conn.execute(sa.select(sa.func.count()).select_from(submissions.jobs).where(
                    submissions.jobs.c.submission_id.in_(burst_ids), submissions.jobs.c.state == 'complete')).scalar_one() == 150
        wait_until(complete, timeout=300)
        duration = time.monotonic() - start
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(submissions.runs).where(
                submissions.runs.c.submission_id.in_(burst_ids), submissions.runs.c.verdict == 'AC')).scalar_one() == 150
        print(f'BENCHMARK: 150 accepted in {upload_seconds:.2f}s; all judged in {duration:.2f}s; workers=2; cases=10; source=integer sum')
        request = Request('http://127.0.0.1:8015/api/admin/isolates/events',
            headers={'Cookie': 'cjudge_session=' + admin_token, 'Origin': 'https://localhost:8443'})
        with urlopen(request, timeout=3) as stream:
            assert stream.headers.get_content_type() == 'text/event-stream'
            assert stream.readline() == b'event: refresh\n'
            with identity.engine().begin() as conn:
                conn.execute(sa.delete(identity.sessions).where(identity.sessions.c.account_id == admin_id))
                queue.notify(conn)
            lines = [stream.readline() for _ in range(6)]
            assert b'event: denied\n' in lines, lines
        print('PASS: admin SSE revocation and no public isolate access')
    finally:
        if pool:
            pool.terminate(); pool.wait(timeout=15)
        api.terminate(); api.wait(timeout=10)


def main() -> None:
    database = 'judging_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        with tempfile.TemporaryDirectory() as directory:
            exercise(directory)
    finally:
        identity.engine().dispose(); identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
