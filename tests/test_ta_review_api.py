"""M24 API contract against disposable PostgreSQL."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import sqlalchemy as sa

from cjudge import identity, labs, tasks
from cjudge.labs import ta_reviews
from cjudge import submissions
from cjudge.api import app
from cjudge.tasks.grading import TaskConfig
from test_ta_gate import ORIGIN, login, ta_database, write


def test_new_task_accepts_ta_maximum_and_existing_changes_need_reason(ta_database) -> None:
    identity.create_admin('M24-admin-password')
    config = TaskConfig(title='Sum').model_dump(mode='json')
    lab_id, task_id, revision_id = uuid4(), uuid4(), uuid4()
    with identity.engine().begin() as conn:
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Draft', version=1, strict_ip=False))
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, cases_key=uuid4(), case_count=1))
    with TestClient(app, base_url=ORIGIN) as admin:
        csrf = login(admin, 'admin', 'M24-admin-password')['csrf_token']
        endpoint = f'/api/admin/labs/{lab_id}/tasks'
        assignment = {'revision_id': str(revision_id), 'maximum_marks': '5.00', 'ta_maximum': '10.00'}
        added = write(admin, endpoint, {'version': 1, 'assignments': [assignment]}, csrf, 'put')
        assert added.status_code == 200, added.text
        assert added.json()['tasks'][0]['ta_maximum'] == '10.00'
        assignment['ta_maximum'] = '20.00'
        assert write(admin, endpoint, {'version': 2, 'assignments': [assignment]}, csrf, 'put').status_code == 409


def test_claim_mark_finalize_scope_and_admin_controls(ta_database, tmp_path, monkeypatch) -> None:
    key_file = tmp_path / 'credentials.key'
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(identity, 'KEY_FILE', key_file)
    identity.create_admin('M24-admin-password')
    config = TaskConfig(title='Sum').model_dump(mode='json')
    lab_id, task_id, revision_id = uuid4(), uuid4(), uuid4()
    with identity.engine().begin() as conn:
        student_id = identity.add_student(conn, 'M24-001', 'Ada')
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='M24 test', version=1,
            strict_ip=False, compiler_feedback='short', first_released_at=datetime.now(timezone.utc)))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student_id))
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, cases_key=uuid4(), case_count=1))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1,
            revision_id=revision_id, maximum_marks=5, ta_maximum=10))
    base = f'/api/ta/labs/{lab_id}/students/{student_id}/ta-review'
    with TestClient(app, base_url=ORIGIN) as admin, TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        admin_csrf = login(admin, 'admin', 'M24-admin-password')['csrf_token']
        ta_ids = []
        for name in ('helper1', 'helper2'):
            created = write(admin, '/api/admin/tas', {'username': name, 'name': name,
                'password': 'M24-ta-password'}, admin_csrf)
            assert created.status_code == 201, created.text
            ta_ids.append(created.json()['id'])
        first_csrf = login(first, 'helper1', 'M24-ta-password')['csrf_token']
        second_csrf = login(second, 'helper2', 'M24-ta-password')['csrf_token']
        assert write(admin, f'/api/admin/labs/{lab_id}/tas',
            {'version': 1, 'ids': ta_ids}, admin_csrf, 'put').status_code == 200
        assert first.get(base).status_code == 200
        assert write(first, base + '/claim', {'version': 0}, 'bad').status_code == 403
        claimed = write(first, base + '/claim', {'version': 0}, first_csrf)
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()['tasks'][0]['suggested_marks'] == '0.00'
        submission_id, attempt_id = uuid4(), uuid4()
        timestamp = datetime.now(timezone.utc)
        with identity.engine().begin() as conn:
            conn.execute(sa.insert(submissions.submissions).values(id=submission_id, lab_id=lab_id,
                account_id=student_id, revision_id=revision_id, idempotency_key=uuid4(), filename='answer.c',
                sha256='0' * 64, size=1, accepted_at=timestamp, client_ip='192.0.2.1'))
            conn.execute(sa.insert(submissions.jobs).values(submission_id=submission_id, revision_id=revision_id,
                state='complete', attempt_id=attempt_id))
            conn.execute(sa.insert(submissions.attempts).values(id=attempt_id, submission_id=submission_id,
                worker_slot=0, worker_generation=uuid4(), started_at=timestamp,
                lease_until=timestamp + timedelta(seconds=60), finished_at=timestamp, outcome='complete'))
            conn.execute(sa.insert(submissions.runs).values(id=attempt_id, submission_id=submission_id,
                revision_id=revision_id, verdict='Partial', passed=4, total=5, score_numerator='4',
                score_denominator='1', compiler_feedback='', compiler_truncated=False, finished_at=timestamp))
            conn.execute(sa.insert(submissions.reviews).values(submission_id=submission_id, run_id=attempt_id))
        assert first.get(base).json()['tasks'][0]['suggested_marks'] == '8.00'
        with identity.engine().begin() as conn:
            conn.execute(sa.update(submissions.jobs).where(submissions.jobs.c.submission_id == submission_id)
                .values(state='queued'))
        assert first.get(base).json()['tasks'][0]['suggested_marks'] is None
        with identity.engine().begin() as conn:
            conn.execute(sa.update(submissions.jobs).where(submissions.jobs.c.submission_id == submission_id)
                .values(state='complete'))
        assert write(second, base + '/claim', {'version': 0}, second_csrf).status_code == 409
        assert write(second, base + f'/tasks/{task_id}',
            {'version': 1, 'marks': '2.50', 'done': True}, second_csrf, 'put').status_code == 403
        assert write(first, base + '/marks', {'version': 1, 'marks': [
            {'task_id': str(task_id), 'marks': '2.50'}, {'task_id': str(task_id), 'marks': '1.00'}]}, first_csrf, 'put').status_code == 400
        assert write(first, base + '/marks', {'version': 1, 'marks': [
            {'task_id': str(task_id), 'marks': '10.01'}]}, first_csrf, 'put').status_code == 400
        saved = write(first, base + '/marks', {'version': 1, 'marks': [
            {'task_id': str(task_id), 'marks': '2.50'}]}, first_csrf, 'put')
        assert saved.status_code == 200, saved.text
        assert saved.json()['total'] == '2.50'
        assert saved.json()['tasks'][0]['done']
        assert write(first, base + '/finalize', {'version': 1}, first_csrf).status_code == 409
        finalized = write(first, base + '/finalize', {'version': 2}, first_csrf)
        assert finalized.status_code == 200 and finalized.json()['finalized']
        overview = admin.get(f'/api/admin/labs/{lab_id}/ta-reviews')
        assert overview.status_code == 200 and overview.json()['students'][0]['combined_total'] == '6.50'
        assert write(second, base + '/reopen', {'version': 3}, second_csrf).status_code == 403
        reopened = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/reopen',
            {'version': 3, 'reason': 'Second review'}, admin_csrf)
        assert reopened.status_code == 200 and reopened.json()['tasks'][0]['done']
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        assert write(admin, f'/api/admin/labs/{lab_id}/tas',
            {'version': version, 'ids': [ta_ids[1]]}, admin_csrf, 'put').status_code == 409
        transferred = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/release',
            {'version': reopened.json()['version'], 'owner_id': ta_ids[1], 'reason': 'Hand off'}, admin_csrf)
        assert transferred.status_code == 200 and transferred.json()['owner_id'] == ta_ids[1]
        completed = write(second, base + '/finalize',
            {'version': transferred.json()['version']}, second_csrf)
        assert completed.status_code == 200 and completed.json()['reviewer_name'] == 'helper2'
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        maximum = write(admin, f'/api/admin/labs/{lab_id}/tasks/{task_id}/ta-maximum',
            {'version': version, 'ta_maximum': '20.00', 'reason': 'Scale rubric'}, admin_csrf, 'put')
        assert maximum.status_code == 200, maximum.text
        assert first.get(base).json()['total'] == '5.00'
        with identity.engine().begin() as conn:
            ta_reviews.flag(conn, lab_id, student_id)
        flagged = admin.get(f'/api/admin/labs/{lab_id}/ta-reviews').json()['students'][0]['review']
        assert flagged['needs_recheck'] and flagged['total'] == '5.00'
        acknowledged = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/acknowledge',
            {'version': flagged['version'], 'reason': 'Checked code'}, admin_csrf)
        assert acknowledged.status_code == 200 and not acknowledged.json()['needs_recheck']
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        cancelled = write(admin, f'/api/admin/labs/{lab_id}/students/{student_id}/cancellation',
            {'version': version, 'cancelled': True, 'reason': 'Disqualified'}, admin_csrf, 'put')
        assert cancelled.status_code == 204
        assert admin.get(f'/api/admin/labs/{lab_id}/ta-reviews').json()['students'][0]['combined_total'] is None
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id)
                .values(archived_at=datetime.now(timezone.utc)))
        assert first.get(base).status_code == 200
        assert write(second, base + '/reopen',
            {'version': acknowledged.json()['version']}, second_csrf).status_code == 409
