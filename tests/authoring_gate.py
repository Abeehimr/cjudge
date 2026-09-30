"""M7 disposable database and optional real-isolate protocol/recovery gate."""
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import authoring, identity, labs, runner, tasks
from cjudge.authoring import jobs, attempts, cases
from cjudge.judging import queue
from cjudge.submissions import workers
from cjudge.tasks.authoring import check_python, GenerationConfig, generate_case, compile_source, AuthoringError

REFERENCE = '#include <stdio.h>\nint main(){long x;scanf("%ld",&x);printf("%ld\\n",x*2);}'
GENERATOR = 'import random\nprint(random.randrange(100000))'


def exercise(directory: str) -> None:
    os.environ['CJUDGE_AUTHORING_FILES'] = directory
    os.environ['CJUDGE_TASK_FILES'] = directory
    tasks.ARTIFACTS = Path(directory)
    admin, student, task = [uuid4() for _ in range(3)]
    token, student_token, csrf = [secrets.token_urlsafe(32) for _ in range(3)]
    generation = uuid4()
    with identity.engine().begin() as conn:
        for key, role in ((admin, 'admin'), (student, 'student')):
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name=role, password_hash='unused',
                roll_number=role if role == 'student' else None, encrypted_password=b'unused' if role == 'student' else None))
        for key, value in ((admin, token), (student, student_token)):
            conn.execute(sa.insert(identity.sessions).values(account_id=key, token_hash=identity.token_digest(value),
                csrf_token=csrf, expires_at=labs.now(conn) + timedelta(hours=1)))
        conn.execute(sa.insert(tasks.tasks).values(id=task, version=1, config={'title': 'Generated'}, case_count=0))
        queue.register(conn, 0, generation); queue.worker_status(conn, 0, generation, 'Idle')
    def call(path='', method='GET', body=None, role='admin', csrf_value=csrf):
        headers = {'Origin': 'https://localhost:8443', 'X-CSRF-Token': csrf_value,
                   'Cookie': f'cjudge_session={token if role == "admin" else student_token}'}
        payload = None
        if body is not None:
            headers['Content-Type'] = 'application/json'; payload = json.dumps(body).encode()
        try:
            response = urlopen(Request('http://127.0.0.1:8018/api' + path, data=payload, method=method, headers=headers), timeout=15)
        except HTTPError as exc:
            response = exc
        payload = response.read()
        return response.code, json.loads(payload) if payload and response.headers.get_content_type() == 'application/json' else payload
    base = f'/admin/tasks/{task}'
    server = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1', '--port', '8018'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if call(base)[0] == 200: break
            except URLError:
                time.sleep(.1)
        else: raise AssertionError('API failed to start')
        config = dict(generator=GENERATOR, reference=REFERENCE, language='python', seed=7, count=2)
        assert call(base + '/generation', role='student')[0] == 403
        assert call(base + '/generation', 'POST', {'version': 1, 'config': config}, csrf_value='bad')[0] == 403
        status, job = call(base + '/generation', 'POST', {'version': 1, 'config': config})
        assert status == 201, job
        key = job['id']; path = base + '/generation/' + key
        assert call(base + '/generation', 'POST', {'version': 1, 'config': config})[0] == 409
        assert call(path + '/apply', 'POST', {'version': 1})[0] == 409
        if '--sandbox' in sys.argv:
            runner.configure_box(0)
            assert check_python('assert read_input() == b"\\x00\\xff"\nassert len(read_output()) == 10485760\naccept()',
                                b'\x00\xff', b'x' * 10485760, b'hidden')
            assert not check_python('reject()', b'', b'', b'')
            for source in ('pass', 'raise Exception("bad")', 'print("AC")', 'while True: pass', 'accept()\nprint("ignored")'):
                if source.startswith('accept()'):
                    assert check_python(source, b'', b'', b'')
                else:
                    try: check_python(source, b'', b'', b'')
                    except runner.SandboxError: pass
                    else: raise AssertionError('Invalid checker accepted')
            reference = compile_source(REFERENCE, 'reference')
            model = GenerationConfig(**config)
            assert generate_case(model, 7, reference) == generate_case(model, 7, reference)
            c = GenerationConfig(language='c', generator='#include <stdio.h>\n#include <stdlib.h>\nint main(int c,char**v){srand(strtoul(v[1],0,10));printf("%d\\n",rand()%1000);}', reference=REFERENCE)
            compiled = compile_source(c.generator, 'generator')
            assert generate_case(c, 3, reference, compiled) == generate_case(c, 3, reference, compiled)
            for bad in ('int main(){bad syntax}', 'int main(){return 1;}'):
                try:
                    binary = compile_source(bad, 'reference')
                    generate_case(model, 7, binary)
                except AuthoringError: pass
                else: raise AssertionError('Reference error accepted')
            print('PASS: real isolate byte helpers, explicit verdicts, checker timeout, full output, reproducible Python/C and reference failures')
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert active['authoring'] and str(active['id']) == key
            assert queue.claim(conn, 0, generation) is None
            assert not queue.heartbeat(conn, 1, generation, active['attempt_id'])
            assert not queue.heartbeat(conn, 0, uuid4(), active['attempt_id'])
            assert queue.heartbeat(conn, 0, generation, active['attempt_id'])
        isolate = call('/admin/isolates')[1]
        assert isolate['workers'][0]['state'] == 'Generating' and isolate['workers'][0]['healthy']
        assert isolate['workers'][0]['generation_job_id'] == key
        def case_result(active):
            if '--sandbox' in sys.argv: return authoring.run_case(active)
            artifact = uuid4(); pair = (b'3\n', b'6\n')
            import hashlib
            for part, data in zip(('in', 'out'), pair): authoring.save(active['id'], artifact, part, data)
            return dict(job_id=active['id'], number=active['progress'] + 1, seed=7 + active['progress'], artifact_id=artifact,
                input_size=2, answer_size=2, input_sha256=hashlib.sha256(pair[0]).hexdigest(), answer_sha256=hashlib.sha256(pair[1]).hexdigest())
        result = case_result(active)
        with identity.engine().begin() as conn:
            assert authoring.checkpoint(conn, active['attempt_id'], result)
            assert not authoring.checkpoint(conn, active['attempt_id'], result)
            active = queue.claim(conn, 0, generation)
            assert active['progress'] == 1
            old = active['attempt_id']
            conn.execute(sa.update(attempts).where(attempts.c.id == old).values(lease_until=labs.now(conn) - timedelta(seconds=1)))
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert active['progress'] == 1 and active['attempt_id'] != old
            assert not queue.heartbeat(conn, 0, generation, old)
            assert not authoring.checkpoint(conn, old, result)
        result = case_result(active)
        with identity.engine().begin() as conn: assert authoring.checkpoint(conn, active['attempt_id'], result)
        assert call(path + '/cases/1/in', role='student')[0] == 403
        assert call(path + '/cases/1/in')[0] == 200
        assert call(base)[1]['case_count'] == 0  # Staging does not mutate drafts.
        assert call(path + '/apply', 'POST', {'version': 1})[0] == 200
        assert call(base)[1]['case_count'] == 2 and not call(base)[1]['revisions']
        assert call(base + '/publish', 'POST', {'version': 2})[0] == 201
        status, job = call(base + '/generation', 'POST', {'version': 2, 'config': config})
        assert status == 201
        path = base + '/generation/' + job['id']
        with identity.engine().begin() as conn:
            for i in range(3):
                active = queue.claim(conn, 0, generation)
                assert authoring.fail(conn, active['attempt_id'], 'Storage unavailable')
                queue.worker_status(conn, 0, generation, 'Idle')
            assert queue.claim(conn, 0, generation) is None
        assert call(path)[1]['state'] == 'failed'
        assert call(path + '/retry', 'POST', {'version': 2})[0] == 200
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert authoring.fail(conn, active['attempt_id'], '<script>teacher error</script>', author_error=True)
            queue.worker_status(conn, 0, generation, 'Idle')
        assert call(path)[1]['state'] == 'failed'
        assert call(path + '/apply', 'POST', {'version': 2})[0] == 409
        assert call(path + '/discard', 'POST', {'version': 2})[0] == 200
        if '--sandbox' in sys.argv:
            live_config = config | {'generator': 'import time, random\ntime.sleep(.4)\nprint(random.randrange(1000))', 'count': 6}
            status, live_job = call(base + '/generation', 'POST', {'version': 2, 'config': live_config})
            assert status == 201
            # Existing reviewed cases remain publishable while independent generation runs.
            checker_config = {'title': 'Edited during generation', 'checker': {'kind': 'python',
                'source': 'if read_output() == read_answer(): accept()\nreject()'}}
            assert call(base, 'PUT', {'version': 2, 'config': checker_config})[0] == 200
            status, published = call(base + '/publish', 'POST', {'version': 3})
            assert status == 201
            from cjudge.submissions import files
            from cjudge.judging.worker import judge
            os.environ['CJUDGE_SUBMISSION_FILES'] = directory
            for source, verdict in ((REFERENCE.encode(), 'AC'), (b'int main(){}', 'Failed')):
                source_id = uuid4(); files.save(source_id, source)
                accepted = {'id': source_id, 'revision_id': UUID(published['id']), 'size': len(source),
                            'sha256': files.validate('main.c', source)}
                assert judge(accepted, threading.Event())['verdict'] == verdict
            process = subprocess.Popen(['python', '-c', 'from cjudge.judging.worker import work; work(0)'],
                                       stdout=subprocess.DEVNULL)
            try:
                for _ in range(300):
                    current = call(base + '/generation/' + live_job['id'])[1]
                    if current['progress'] >= 1: break
                    assert process.poll() is None, 'Generation worker crashed'
                    time.sleep(.05)
                else: raise AssertionError('Worker did not checkpoint')
                process.kill(); process.wait(timeout=10)
                saved = current['progress']
                with identity.engine().begin() as conn:
                    # Wait for the killed worker's last transaction before expiring its current lease.
                    stopped_job = conn.execute(sa.select(jobs).where(jobs.c.id == UUID(live_job['id']))
                        .with_for_update()).mappings().one()
                    conn.execute(sa.update(attempts).where(attempts.c.id == stopped_job['attempt_id']).values(
                        lease_until=labs.now(conn) - timedelta(seconds=1)))
                process = subprocess.Popen(['python', '-c', 'from cjudge.judging.worker import work; work(0)'],
                                           stdout=subprocess.DEVNULL)
                for _ in range(400):
                    current = call(base + '/generation/' + live_job['id'])[1]
                    if current['state'] == 'complete': break
                    assert process.poll() is None, 'Recovery worker crashed'
                    time.sleep(.05)
                else: raise AssertionError(f'Worker did not resume generation: {current["state"]}, progress={current["progress"]}, diagnostic={current["diagnostic"]}')
                assert current['progress'] == 6 and len(current['cases']) == 6 and saved >= 1
                assert call(base + '/generation/' + live_job['id'] + '/apply', 'POST', {'version': 3})[0] == 409
                cache = list((Path(directory) / live_job['id']).glob('*.reference'))
                assert len(cache) == 1 and cache[0].stat().st_mode & 0o777 == 0o400
                print('PASS: live worker generation, kill/restart checkpoint recovery, protected compile cache, pending publication and stale draft rejection')
            finally:
                process.terminate(); process.wait(timeout=10)
        print('PASS: admin/CSRF, staged review/apply/publish, single job, generation health, case checkpoints, stale leases, crash resume and three-fault retries')
    finally:
        server.terminate(); server.wait(timeout=10)


def main() -> None:
    database = 'authoring_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn: conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        # Existing installations upgrade in a fresh process, without schema-import side effects.
        subprocess.run(['python', '-m', 'alembic', 'upgrade', '20261001_marks'], check=True)
        subprocess.run(['python', '-m', 'alembic', 'upgrade', 'head'], check=True)
        with tempfile.TemporaryDirectory() as directory: exercise(directory)
    finally:
        identity.engine().dispose(); identity.engine.cache_clear()
        with root.connect() as conn: conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
