"""M26 admission, rejudge provenance and archive contracts in disposable PostgreSQL."""
from datetime import datetime, timedelta, timezone
import io
import os
import threading
from uuid import uuid4
import zipfile
from alembic import command
from alembic.config import Config

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa

from cjudge import identity, labs, runner, submissions, tasks, tester
from cjudge.api import app
from cjudge.judging import worker
from cjudge.labs import archive
from cjudge.submissions import service, review, files
from cjudge.tasks.grading import TaskConfig
from test_ta_gate import ta_database, login, ORIGIN

pytestmark = pytest.mark.skipif(not os.getenv('CJUDGE_TA_GATE_URL'), reason='requires disposable PostgreSQL')


def test_legacy_upgrade_preserves_archive_digest(ta_database, monkeypatch, tmp_path):
    key = tmp_path / 'credentials.key'
    key.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(identity, 'KEY_FILE', key)
    lab_id, task_id, revision_id = [uuid4() for _ in range(3)]
    with identity.engine().begin() as conn:
        student = identity.add_student(conn, 'LEGACY-001', 'Legacy')
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Legacy', version=1, strict_ip=False))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student))
        config = {'title': 'Legacy'}
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, case_count=1, cases_key=uuid4()))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1, revision_id=revision_id, maximum_marks=5))
        conn.execute(sa.insert(submissions.submissions).values(id=uuid4(), lab_id=lab_id, account_id=student,
            revision_id=revision_id, idempotency_key=uuid4(), filename='legacy.c', size=1, sha256='0' * 64,
            accepted_at=datetime.now(timezone.utc), client_ip='192.0.2.1'))
        before = archive.digest(archive.snapshot(conn, labs.find(conn, lab_id), 4))
    command.downgrade(Config('alembic.ini'), '20261014_source_restrictions')
    command.upgrade(Config('alembic.ini'), 'head')
    with identity.engine().connect() as conn:
        assert conn.execute(sa.select(submissions.submissions.c.language)).scalar_one() == 'c11'
        assert archive.digest(archive.snapshot(conn, labs.find(conn, lab_id), 4)) == before


def test_cpp_admission_correction_tester_and_archive(ta_database, monkeypatch, tmp_path):
    key = tmp_path / 'credentials.key'
    key.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(identity, 'KEY_FILE', key)
    monkeypatch.setenv('CJUDGE_SUBMISSION_FILES', str(tmp_path))
    monkeypatch.setenv('CJUDGE_AUTHORING_FILES', str(tmp_path))
    monkeypatch.setattr(tasks, 'ARTIFACTS', tmp_path)
    identity.create_admin('M26-admin-password')
    lab_id, task_id, c_revision, both_revision = [uuid4() for _ in range(4)]
    timestamp = datetime.now(timezone.utc)
    source = b'int main(){}'
    with identity.engine().begin() as conn:
        student = identity.add_student(conn, 'M26-001', 'Ada')
        actor = conn.execute(sa.select(identity.accounts.c.id).where(identity.accounts.c.role == 'admin')).scalar_one()
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='C++', version=1, strict_ip=False,
            starts_at=timestamp - timedelta(minutes=1), ends_at=timestamp + timedelta(hours=1)))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student))
        config = TaskConfig(title='C++').model_dump(mode='json')
        cases_key = tasks.save_cases([(b'', b'')])
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1, cases_key=cases_key))
        for number, revision, languages in ((1, c_revision, ['c11']), (2, both_revision, ['c11', 'cpp17'])):
            conn.execute(sa.insert(tasks.revisions).values(id=revision, task_id=task_id, number=number,
                draft_version=number, config=config | {'languages': languages}, case_count=1, cases_key=cases_key))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1, revision_id=c_revision, maximum_marks=5))
        lab, enrollment = labs.find(conn, lab_id), labs.enrollment(conn, lab_id, student, lock=False)
        with pytest.raises(service.SubmissionError, match='does not allow'):
            service.accept(conn, lab, enrollment, c_revision, uuid4(), 'main.cpp', source, '192.0.2.1')
        assert conn.execute(sa.select(sa.func.count()).select_from(submissions.submissions)).scalar_one() == 0
        conn.execute(sa.update(labs.assignments).where(labs.assignments.c.lab_id == lab_id).values(revision_id=both_revision))
        retry_key = uuid4()
        row, created = service.accept(conn, lab, enrollment, both_revision, retry_key, 'main.cpp', source, '192.0.2.1')
        assert created and row['language'] == 'cpp17'
        assert service.accept(conn, lab, enrollment, both_revision, retry_key, 'main.cpp', source, '192.0.2.1')[1] is False
        with pytest.raises(labs.LabError, match='retained submissions'):
            review.correct(conn, lab, task_id, c_revision, actor, 'Narrow policy')
        current = archive.snapshot(conn, lab)
        old = archive.snapshot(conn, lab, 4)
        assert current['submissions'][0]['language'] == 'cpp17'
        assert 'language' not in old['submissions'][0]
    compiled = []
    monkeypatch.setattr(runner, 'compile_cpp', lambda data: compiled.append(data) or runner.Result('OK', b'', b'', 0, 0, 0, b'binary'))
    monkeypatch.setattr(runner, 'execute', lambda *a, **kw: runner.Result('OK', b'', b'', 0, 0, 0))
    assert worker.judge(row, threading.Event())['verdict'] == 'AC'
    assert compiled == [source]
    with TestClient(app, base_url=ORIGIN) as admin:
        csrf = login(admin, 'admin', 'M26-admin-password')['csrf_token']
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as bundle:
            bundle.writestr('main.c', source)
            bundle.writestr('main.cpp', source)
        base = f'/api/admin/tasks/{task_id}/tester'
        headers = {'Origin': ORIGIN, 'X-CSRF-Token': csrf, 'Content-Type': 'application/zip'}
        rejected = admin.post(f'{base}?revision_id={c_revision}', content=data.getvalue(), headers=headers)
        assert rejected.status_code == 422, rejected.text
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(sa.func.count()).select_from(tester.batches)).scalar_one() == 0
        accepted = admin.post(f'{base}?revision_id={both_revision}', content=data.getvalue(), headers=headers)
        assert accepted.status_code == 201, accepted.text
        assert {item['language'] for item in accepted.json()['sources']} == {'c11', 'cpp17'}
        downloaded = admin.get(f'/api/admin/labs/{lab_id}/submissions/{row["id"]}/source')
        assert downloaded.status_code == 200 and '.cpp"' in downloaded.headers['content-disposition']
