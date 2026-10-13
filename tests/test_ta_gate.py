"""M23 API gate. Run only against a disposable, migrated PostgreSQL database."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from cjudge import identity, labs
from cjudge.api import app


pytestmark = pytest.mark.skipif(not os.getenv('CJUDGE_TA_GATE_URL'), reason='requires local PostgreSQL for disposable M23 database')
ORIGIN = 'https://localhost:8443'


@pytest.fixture
def ta_database(monkeypatch):
    name = 'm23_' + uuid4().hex[:12]
    base = sa.engine.make_url(os.environ['CJUDGE_TA_GATE_URL'])
    server = sa.create_engine(base, isolation_level='AUTOCOMMIT')
    with server.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE {name}'))
    url = base.set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv('DATABASE_URL', url)
    identity.engine.cache_clear()
    try:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True,
            env={**os.environ, 'DATABASE_URL': url}, capture_output=True)
        yield
    finally:
        identity.engine.cache_clear()
        with server.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE {name} WITH (FORCE)'))
        server.dispose()


def write(client: TestClient, path: str, body: dict, csrf: str, method: str = 'post'):
    return getattr(client, method)(path, json=body, headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf})


def login(client: TestClient, username: str, password: str, path: str = '/api/auth/login') -> dict:
    response = client.post(path, json={'identifier': username, 'password': password}, headers={'Origin': ORIGIN})
    assert response.status_code == 200, response.text
    return response.json()


def test_ta_accounts_lab_scope_ownership_and_archive(ta_database, tmp_path, monkeypatch) -> None:
    identity.engine.cache_clear()
    key_file = tmp_path / 'credentials.key'
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(identity, 'KEY_FILE', key_file)
    admin_password = 'M23-admin-password'
    identity.create_admin(admin_password)
    with identity.engine().begin() as conn:
        student_id = identity.add_student(conn, 'M23-001', 'Ada Student')
        other_student_id = identity.add_student(conn, 'M23-002', 'Other Student')
        lab_id, other_lab = uuid4(), uuid4()
        for id, title in ((lab_id, 'TA gate lab'), (other_lab, 'Other lab')):
            conn.execute(sa.insert(labs.labs).values(id=id, title=title, version=1,
                strict_ip=False, compiler_feedback='short', starts_at=None, ends_at=None))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student_id))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=other_student_id))
        old_student_password = identity.cipher().decrypt(conn.execute(sa.select(
            identity.accounts.c.encrypted_password).where(identity.accounts.c.id == student_id)).scalar_one()).decode()
    with TestClient(app, base_url=ORIGIN) as admin, TestClient(app, base_url=ORIGIN) as ta_one, TestClient(app, base_url=ORIGIN) as ta_two, TestClient(app, base_url=ORIGIN) as student_client:
        admin_session = login(admin, 'aDmIn', admin_password)
        login(student_client, 'M23-001', old_student_password)
        assert admin_session['role'] == 'admin' and admin_session['username'] == 'ADMIN'
        csrf = admin_session['csrf_token']
        created = []
        for username in ('helper1', 'helper2'):
            response = write(admin, '/api/admin/tas', {'username': username, 'name': username,
                'password': 'M23-ta-password'}, csrf)
            assert response.status_code == 201, response.text
            created.append(response.json()['id'])
        with pytest.raises(IntegrityError), identity.engine().begin() as conn:
            conn.execute(sa.insert(identity.accounts).values(id=uuid4(), role='ta',
                username='helper1', name='Collision', password_hash='unused'))
        assert write(admin, '/api/admin/students', {'roll_number': 'HELPER1', 'name': 'Collision'}, csrf).status_code == 409
        assert ta_one.post('/api/auth/student/login', json={'identifier': 'helper1',
            'password': 'M23-ta-password'}, headers={'Origin': ORIGIN}).status_code == 401
        one = login(ta_one, 'HeLpEr1', 'M23-ta-password')
        two = login(ta_two, 'helper2', 'M23-ta-password')
        assert one['role'] == 'ta' and two['role'] == 'ta'
        assert ta_one.get('/api/admin/tas').status_code == 403
        assert ta_one.get(f'/api/ta/labs/{other_lab}').status_code == 403
        assert write(ta_one, f'/api/ta/labs/{other_lab}/students/{student_id}/password',
            {'confirm': True}, one['csrf_token']).status_code == 403
        assignment = write(admin, f'/api/admin/labs/{lab_id}/tas', {'version': 1, 'ids': created}, csrf, 'put')
        assert assignment.status_code == 200, assignment.text
        assert len(assignment.json()['tas']) == 2
        assert len(ta_one.get('/api/ta/labs').json()) == 1
        assert ta_one.get(f'/api/ta/labs/{lab_id}/students').json() == []
        assert ta_one.get(f'/api/ta/labs/{other_lab}/students').status_code == 403
        found = ta_one.get(f'/api/ta/labs/{lab_id}/students?search=ada')
        assert found.status_code == 200 and len(found.json()) == 1
        student = ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}').json()
        assert student['submission_count'] == 0 and 'password' not in student and 'marks' not in student
        assert ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}/submissions').json() == []
        marks = ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}/marks')
        assert marks.status_code == 200 and len(marks.json()) == 1 and marks.json()[0]['id'] == str(student_id)
        assert ta_one.get(f'/api/ta/labs/{other_lab}/students/{student_id}/marks').status_code == 403
        detail = admin.get(f'/api/admin/labs/{lab_id}/tas/{created[0]}')
        assert detail.status_code == 200 and detail.json()['ta']['username'] == 'HELPER1'
        assert ta_one.get(f'/api/admin/labs/{lab_id}/tas/{created[0]}').status_code == 403
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/freeze',
            {'frozen': True, 'reason': 'Exam rule'}, one['csrf_token']).status_code == 204
        assert write(ta_two, f'/api/ta/labs/{lab_id}/students/{student_id}/freeze',
            {'frozen': False, 'reason': 'Attempt'}, two['csrf_token']).status_code == 403
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/freeze',
            {'frozen': False, 'reason': 'Resolved'}, one['csrf_token']).status_code == 204
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/cancellation',
            {'cancelled': True, 'reason': 'Exam rule'}, one['csrf_token'], 'put').status_code == 204
        assert write(ta_two, f'/api/ta/labs/{lab_id}/students/{student_id}/cancellation',
            {'cancelled': False, 'reason': 'Attempt'}, two['csrf_token'], 'put').status_code == 403
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/cancellation',
            {'cancelled': False, 'reason': 'Resolved'}, one['csrf_token'], 'put').status_code == 204
        activity = admin.get(f'/api/admin/labs/{lab_id}/tas/{created[0]}').json()
        assert any(item['action'] == 'lab_student_frozen' and item['student_id'] == str(student_id)
                   and item['detail']['reason'] == 'Exam rule' for item in activity['activity'])
        assert activity['penalties'] == []
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/password',
            {}, 'wrong').status_code == 403
        password = write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/password',
            {}, one['csrf_token'])
        assert password.status_code == 200 and password.headers['cache-control'] == 'no-store'
        assert len(password.json()['password']) == 6
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.enrollments).where(labs.enrollments.c.lab_id == lab_id,
                labs.enrollments.c.account_id == student_id).values(binding_hash='bound', bound_ip='192.0.2.1'))
        reset = write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/release',
            {'reason': 'New browser'}, one['csrf_token'])
        assert reset.status_code == 200 and reset.json()['password'] != old_student_password
        assert student_client.get('/api/auth/session').status_code == 401
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(labs.enrollments.c.binding_hash).where(
                labs.enrollments.c.lab_id == lab_id, labs.enrollments.c.account_id == student_id)).scalar_one() is None
        with identity.engine().connect() as conn:
            audit = conn.execute(sa.select(identity.audit_events.c.detail).where(
                identity.audit_events.c.action == 'ta_student_password_accessed')).scalar_one()
            assert 'password' not in str(audit)
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(
                first_released_at=datetime.now(timezone.utc), reveal_results=True))
        assert ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}/submissions').json() == []
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(
                archived_at=datetime.now(timezone.utc)))
        assert ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}/submissions').status_code == 200
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/password',
            {}, one['csrf_token']).status_code == 409
        assert write(ta_one, f'/api/ta/labs/{lab_id}/students/{student_id}/freeze',
            {'frozen': True, 'reason': 'Too late'}, one['csrf_token']).status_code == 409
        # Removal is versioned and revokes all assigned-lab reads immediately.
        fresh = admin.get(f'/api/admin/labs/{lab_id}').json()
        assert write(admin, f'/api/admin/labs/{lab_id}/tas', {'version': fresh['version'], 'ids': []}, csrf, 'put').status_code == 409
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(archived_at=None))
        fresh = admin.get(f'/api/admin/labs/{lab_id}').json()
        assert write(admin, f'/api/admin/labs/{lab_id}/tas', {'version': fresh['version'], 'ids': []}, csrf, 'put').status_code == 200
        assert ta_one.get(f'/api/ta/labs/{lab_id}').status_code == 403
        assert ta_one.get(f'/api/ta/labs/{lab_id}/students/{student_id}/submissions').status_code == 403
        assert write(admin, f'/api/admin/tas/{created[1]}/password',
            {'password': 'M23-new-ta-password'}, csrf).status_code == 200
        assert ta_two.get('/api/auth/session').status_code == 401
        with TestClient(app, base_url=ORIGIN) as fresh_ta:
            assert fresh_ta.post('/api/auth/login', json={'identifier': 'helper2',
                'password': 'M23-ta-password'}, headers={'Origin': ORIGIN}).status_code == 401
            for index in range(4):
                path = '/api/auth/student/login' if index % 2 else '/api/auth/login'
                assert fresh_ta.post(path, json={'identifier': 'helper2', 'password': 'wrong'},
                    headers={'Origin': ORIGIN}).status_code == 401
            assert fresh_ta.post('/api/auth/login', json={'identifier': 'helper2',
                'password': 'M23-new-ta-password'}, headers={'Origin': ORIGIN}).status_code == 401
            with identity.engine().begin() as conn:
                conn.execute(sa.delete(identity.login_attempts).where(identity.login_attempts.c.identifier == 'HELPER2'))
            assert login(fresh_ta, 'helper2', 'M23-new-ta-password')['role'] == 'ta'
        assert write(admin, f'/api/admin/tas/{created[0]}/state', {'active': False}, csrf, 'put').status_code == 200
        assert ta_one.get('/api/auth/session').status_code == 401
