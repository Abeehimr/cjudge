"""M3 gate in a disposable database. Run in an API container with tests mounted."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
import zipfile

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from cjudge import identity, tasks


def main() -> None:
    database = 'task_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    service = None
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        with tempfile.TemporaryDirectory() as directory:
            os.environ['CJUDGE_TASK_FILES'] = directory
            tasks.ARTIFACTS = Path(directory)
            admin_id, student_id = uuid4(), uuid4()
            cookies = {'admin': secrets.token_urlsafe(32), 'student': secrets.token_urlsafe(32)}
            csrf = secrets.token_hex(32)
            with identity.engine().begin() as conn:
                for role, account_id in [('admin', admin_id), ('student', student_id)]:
                    conn.execute(sa.insert(identity.accounts).values(id=account_id, role=role,
                        roll_number='GATE' if role == 'student' else None, name='Gate', password_hash='unused',
                        encrypted_password=b'unused' if role == 'student' else None))
                    conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(cookies[role]),
                        account_id=account_id, csrf_token=csrf, expires_at=identity.now() + timedelta(hours=1)))
            service = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1',
                                        '--port', '8011'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            def call(path='', method='GET', body=None, role='admin', token=csrf, content_type='application/json', origin='https://localhost:8443'):
                data = json.dumps(body).encode() if body is not None and content_type == 'application/json' else body
                headers = {'Origin': origin, 'X-CSRF-Token': token, 'Content-Type': content_type}
                if role:
                    headers['Cookie'] = 'cjudge_session=' + cookies[role]
                request = Request('http://127.0.0.1:8011/api/admin/tasks' + path, method=method, data=data, headers=headers)
                try:
                    response = urlopen(request, timeout=10)
                except HTTPError as error:
                    return error.code, None, error.headers
                payload = response.read()
                result = json.loads(payload) if response.headers.get_content_type() == 'application/json' else payload
                return response.status, result, response.headers

            for _ in range(100):
                try:
                    if call()[0] == 200:
                        break
                except URLError:
                    time.sleep(.1)
            else:
                raise AssertionError('Test API did not start')
            assert call(role=None)[0] == 401
            assert call(role='student')[0] == 403
            assert call(method='POST', body={'title': 'x'}, token='wrong')[0] == 403
            assert call(method='POST', body={'title': 'x'}, origin='https://evil.example')[0] == 403
            assert call(method='POST', body={'title': ' '})[0] == 422
            status, draft, _ = call(method='POST', body={'title': 'Sum'})
            assert status == 201 and draft['config']['statement'] == ''
            path = '/' + draft['id']
            assert call(path + '/publish', 'POST', {'version': 1})[0] == 400
            status, draft, _ = call(path + '/cases', 'POST', {'version': 1, 'input': '1 2\n', 'answer': '3\n'})
            assert status == 200 and draft['version'] == 2 and draft['case_count'] == 1
            assert call(path, 'PUT', {'version': 1, 'config': {'title': 'stale'}})[0] == 409
            assert call(path + '/cases/1/out', role='student')[0] == 403
            status, data, headers = call(path + '/cases/1/out')
            assert status == 200 and data == b'3\n' and headers['Cache-Control'] == 'no-store'
            assert headers['X-Content-Type-Options'] == 'nosniff'
            assert call(path + '/cases/1/out', role=None)[0] == 401
            assert call(path + '/cases/1/../out')[0] in (404, 422)
            assert call(path + '/cases?version=2', 'PUT', b'bad', content_type='application/zip')[0] == 400
            assert call(path)[1]['version'] == 2
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda _: call(path + '/publish', 'POST', {'version': 2}), range(2)))
            assert sorted(result[0] for result in results) == [201, 409]
            revision = next(result[1] for result in results if result[0] == 201)
            revision_path = path + '/revisions/' + revision['id']
            assert call(revision_path)[1]['case_count'] == 1
            assert call(revision_path, role='student')[0] == 403
            assert call(revision_path, 'PUT', {'config': {'title': 'bad'}})[0] == 405
            with identity.engine().connect() as conn:
                try:
                    conn.execute(sa.update(tasks.revisions).values(config={}).where(tasks.revisions.c.id == revision['id']))
                except DBAPIError:
                    conn.rollback()
                else:
                    raise AssertionError('Published revision changed')
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda title: call(path, 'PUT', {'version': 2, 'config': {'title': title}}), ['A', 'B']))
            assert sorted(result[0] for result in results) == [200, 409]
            zip_data = io.BytesIO()
            with zipfile.ZipFile(zip_data, 'w') as archive:
                archive.writestr('1.in', b'2 3\n')
                archive.writestr('1.out', b'5\n')
            status, draft, _ = call(path + '/cases?version=3', 'PUT', zip_data.getvalue(), content_type='application/zip')
            assert status == 200 and draft['version'] == 4
            assert call(path + '/cases/1/out')[1] == b'5\n'
            assert call(path + '/cases/1/out?revision_id=' + revision['id'])[1] == b'3\n'
            assert call(revision_path)[1]['config']['title'] == 'Sum'
            status, second, _ = call(path + '/publish', 'POST', {'version': 4})
            assert status == 201 and second['number'] == 2
            assert len(call(path)[1]['revisions']) == 2
            assert call(path + '/cases/1?version=4', 'DELETE')[1]['case_count'] == 0
            assert call(path + '/publish', 'POST', {'version': 5})[0] == 400
            assert call(path + '/cases?version=5', 'PUT', b'x' * (17 * 1024 * 1024 + 1), content_type='application/zip')[0] == 413
            assert call(path + '/cases', 'POST', {'version': 5, 'input': 'é' * (1024 * 1024), 'answer': ''})[0] == 400
            # Missing protected files are infrastructure failures, not publishable empty cases.
            with identity.engine().connect() as conn:
                key = conn.execute(sa.select(tasks.revisions.c.cases_key).where(tasks.revisions.c.id == revision['id'])).scalar_one()
            (Path(directory) / f'{key}.zip').unlink()
            assert call(revision_path)[0] == 503
            print('PASS: task drafts, ZIP/paste, limits, auth/CSRF, files, edit races, publish races, immutable revisions')
    finally:
        if service:
            service.terminate()
            service.wait(timeout=10)
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
