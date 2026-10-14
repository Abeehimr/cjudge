"""M22 disposable-DB API, queue and optional real-isolate gate."""
from datetime import timedelta
import json
import io
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import zipfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import sqlalchemy as sa

from cjudge import authoring, identity, labs, runner, tasks, tester
from cjudge.judging import queue
from cjudge.submissions import submissions, runs
from cjudge.tasks.grading import TaskConfig

SOURCE = b'#include <stdio.h>\nint main(void){int x;scanf("%d",&x);printf("%d\\n",x*2);}'


def exercise(directory: str, sandbox: bool) -> None:
    os.environ['CJUDGE_AUTHORING_FILES'] = directory
    os.environ['CJUDGE_TASK_FILES'] = directory
    tasks.ARTIFACTS = Path(directory)
    admin, student, task_id, revision_id, generation = [uuid4() for _ in range(5)]
    token, student_token, csrf = [secrets.token_urlsafe(32) for _ in range(3)]
    with identity.engine().begin() as conn:
        for key, role in ((admin, 'admin'), (student, 'student')):
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name=role,
                password_hash='unused', roll_number=role if role == 'student' else None,
                encrypted_password=b'unused' if role == 'student' else None))
        for key, value in ((admin, token), (student, student_token)):
            conn.execute(sa.insert(identity.sessions).values(account_id=key,
                token_hash=identity.token_digest(value), csrf_token=csrf,
                expires_at=labs.now(conn) + timedelta(hours=1)))
        config = TaskConfig(title='Tester gate', checker={'kind': 'tokens'},
            languages=['c11', 'cpp17'] if '--cpp' in sys.argv else ['c11']).model_dump(mode='json')
        case_key = tasks.save_cases([(b'2\n', b'4\n'), (b'3\n', b'6\n')])
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config,
            case_count=2, cases_key=case_key))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, cases_key=case_key, case_count=2, created_at=labs.now(conn)))
        queue.register(conn, 0, generation); queue.worker_status(conn, 0, generation, 'Idle')
    base = f'/admin/tasks/{task_id}/tester'
    def call(path='', method='GET', payload=None, *, role='admin', headers=None):
        fields = {'Host': 'localhost', 'Origin': 'https://localhost:8443',
            'Cookie': f'cjudge_session={token if role == "admin" else student_token}',
            'X-CSRF-Token': csrf} | (headers or {})
        try:
            response = urlopen(Request('http://127.0.0.1:8019/api' + base + path,
                data=payload, method=method, headers=fields), timeout=20)
        except HTTPError as exc:
            response = exc
        body = response.read()
        return response.code, json.loads(body) if body and response.headers.get_content_type() == 'application/json' else body
    server = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1', '--port', '8019'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if call()[0] == 200: break
            except URLError:
                time.sleep(.1)
        else: raise AssertionError('API failed to start')
        upload = f'?revision_id={revision_id}'
        headers = {'Content-Type': 'application/octet-stream', 'X-Filename': 'correct.cpp' if '--cpp' in sys.argv else 'correct.c',
                   'Idempotency-Key': 'gate-one'}
        assert call(upload, 'POST', SOURCE, role='student', headers=headers)[0] == 403
        assert call(upload, 'POST', SOURCE, headers=headers | {'X-CSRF-Token': 'bad'})[0] == 403
        assert call(upload, 'POST', b'', headers=headers)[0] == 422
        status, batch = call(upload, 'POST', SOURCE, headers=headers)
        assert status == 201, batch
        batch_id = batch['id']; source_id = batch['sources'][0]['id']
        assert call(upload, 'POST', SOURCE, headers=headers)[1]['id'] == batch_id
        assert call(upload, 'POST', SOURCE + b' ', headers=headers)[0] == 409
        assert call(f'/{batch_id}', 'DELETE', json.dumps({'reason': 'too early'}).encode(),
            headers={'Content-Type': 'application/json'})[0] == 409
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert active['tester'] and active['id'] == UUID(source_id)
            assert queue.claim(conn, 0, generation) is None
            assert queue.heartbeat(conn, 0, generation, active['attempt_id'])
        assert call(f'/{batch_id}/sources/{source_id}', role='student')[0] == 403
        for step in range(3):
            result = (tester.run_case(active) if sandbox else
                {'kind': 'compile', 'verdict': 'OK', 'compiler_feedback': '', 'compiler_truncated': False} if step == 0 else
                {'kind': 'case', 'number': step, 'verdict': 'AC', 'cpu_seconds': 0., 'wall_seconds': 0.,
                 'memory_kib': 0, 'stdout': b'4\n' if step == 1 else b'6\n', 'stderr': b'',
                 'stdout_truncated': False, 'stderr_truncated': False})
            with identity.engine().begin() as conn:
                assert tester.checkpoint(conn, active['attempt_id'], result)
                assert not tester.checkpoint(conn, active['attempt_id'], result)
                active = queue.claim(conn, 0, generation) if step < 2 else None
            if step < 2:
                assert active['tester'] and active['progress'] == step + 1
        code, detail = call(f'/{batch_id}/sources/{source_id}')
        assert code == 200 and detail['source']['passed'] == 2 and detail['source']['verdict'] == 'AC'
        assert detail['code'] == SOURCE.decode() and len(detail['cases']) == 2
        code, case = call(f'/{batch_id}/sources/{source_id}/cases/1')
        assert code == 200 and case['stdin']['text'] == '2\n' and case['expected']['text'] == '4\n'
        assert case['stdout']['text'] == '4\n'
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(submissions)).scalar_one() == 0
            assert conn.execute(sa.select(sa.func.count()).select_from(runs)).scalar_one() == 0
        assert call(f'/{batch_id}', 'DELETE', json.dumps({'reason': 'gate cleanup'}).encode(),
            headers={'Content-Type': 'application/json'})[0] == 204
        assert call(f'/{batch_id}')[0] == 404
        assert not tester.path(UUID(batch_id), UUID(source_id), 'c').exists()
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(tester.cases)).scalar_one() == 0
            assert conn.execute(sa.select(sa.func.count()).select_from(tester.sources)).scalar_one() == 0
        # After testing, pending generation gets the next background turn.
        with identity.engine().begin() as conn:
            conn.execute(sa.insert(authoring.jobs).values(id=uuid4(), task_id=task_id, base_version=1,
                config={'language': 'python', 'reference_language': 'cpp' if '--cpp' in sys.argv else 'c', 'generator': 'print(2)', 'reference': SOURCE.decode(),
                    'seed': 1, 'count': 1}, actor_id=admin))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('one.cpp' if '--cpp' in sys.argv else 'one.c', SOURCE)
            zipped.writestr('two.c', b'int main(void){return 1;}')
        status, second = call(upload, 'POST', archive.getvalue(), headers={
            'Content-Type': 'application/zip', 'Idempotency-Key': 'gate-two'})
        assert status == 201 and len(second['sources']) == 2
        with identity.engine().begin() as conn:
            conn.execute(sa.update(tester.sources).where(tester.sources.c.id == UUID(second['sources'][1]['id']))
                .values(state='complete'))
            turn = queue.claim(conn, 0, generation)
            assert turn['authoring']
            assert authoring.fail(conn, turn['attempt_id'], 'gate', author_error=True)
            queue.worker_status(conn, 0, generation, 'Idle')
            turn = queue.claim(conn, 0, generation)
            assert turn['tester']
        # Three expired leases stop automatic retries; admin may retry explicitly.
        failed_id = turn['id']
        for fault in range(3):
            with identity.engine().begin() as conn:
                conn.execute(sa.update(tester.attempts).where(tester.attempts.c.id == turn['attempt_id'])
                    .values(lease_until=labs.now(conn) - timedelta(seconds=1)))
                tester.recover(conn)
                assert not tester.checkpoint(conn, turn['attempt_id'], {'kind': 'compile'})
                if fault < 2:
                    turn = queue.claim(conn, 0, generation)
                    assert turn['tester'] and turn['id'] == failed_id
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(tester.sources.c.state).where(tester.sources.c.id == failed_id)).scalar_one() == 'failed'
        assert call(f'/{second["id"]}/sources/{failed_id}/retry', 'POST')[0] == 204
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(tester.sources.c.state).where(tester.sources.c.id == failed_id)).scalar_one() == 'queued'
        # Admission is atomic at the global outstanding-source cap.
        with identity.engine().begin() as conn:
            filler_id = uuid4()
            conn.execute(sa.insert(tester.batches).values(id=filler_id, task_id=task_id, revision_id=revision_id,
                actor_id=admin, payload_sha256='0' * 64))
            conn.execute(sa.insert(tester.sources), [dict(id=uuid4(), batch_id=filler_id,
                filename=f'f{n}.c', size=1, sha256='0' * 64) for n in range(40)])
        assert call(upload, 'POST', SOURCE, headers=headers | {'Idempotency-Key': 'gate-full'})[0] == 429
        print('PASS: M22 admission, CSRF/authorization, idempotency, leases, case evidence, no lab records, deletion' +
              (', real isolate' if sandbox else '') + ', fairness, recovery, retry and queue cap')
    finally:
        server.terminate(); server.wait(timeout=10)


def main() -> None:
    global SOURCE
    if '--cpp' in sys.argv:
        SOURCE = b'#include <iostream>\n#include <vector>\nint main(){int n;std::cin>>n;std::vector<int> v{n,n};std::cout<<v[0]+v[1]<<"\\n";}'
    name = 'tester_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    os.environ['DATABASE_URL'] = root_url.set(database=name).render_as_string(hide_password=False)
    try:
        subprocess.run(['python', '-m', 'alembic', 'upgrade', '20261011_lab_marks'], check=True)
        with identity.engine().begin() as conn:
            conn.exec_driver_sql('ALTER TABLE judge_workers DROP COLUMN IF EXISTS last_background_kind')
        subprocess.run(['python', '-m', 'alembic', 'upgrade', 'head'], check=True)
        with tempfile.TemporaryDirectory() as directory:
            if '--sandbox' in sys.argv:
                runner.configure_box(0)
            exercise(directory, '--sandbox' in sys.argv)
    finally:
        identity.engine().dispose(); identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
