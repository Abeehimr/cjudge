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
    other_lab = uuid4()
    with identity.engine().begin() as conn:
        student_id = identity.add_student(conn, 'M24-001', 'Ada')
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='M24 test', version=1,
            strict_ip=False, compiler_feedback='short', first_released_at=datetime.now(timezone.utc),
            starts_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ends_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        conn.execute(sa.insert(labs.labs).values(id=other_lab, title='Unassigned lab', version=1, strict_ip=False))
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
        staff_path = f'/api/admin/labs/{lab_id}/marks'
        ta_marks_path = f'/api/ta/labs/{lab_id}/students/{student_id}/marks'
        missing = admin.get(staff_path).json()[0]
        assert missing['tasks'][0]['ta_marks'] is None
        assert missing['tasks'][0]['maximum_marks'] == '5.00'
        assert missing['tasks'][0]['ta_maximum'] == '10.00'
        assert missing['ta_review']['provisional'] and missing['ta_review']['owner_name'] is None
        assert first.get(ta_marks_path).json() == [missing]
        assert first.get(staff_path).status_code == 403
        assert first.get(f'/api/ta/labs/{other_lab}/students/{student_id}/marks').status_code == 403
        assert first.get(f'/api/ta/labs/{lab_id}/students/{uuid4()}/marks').status_code == 403
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
        pending = first.get(ta_marks_path).json()[0]
        assert pending['pending'] and pending['tasks'][0]['best_submission_id'] == str(submission_id)
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
        partial = admin.get(staff_path).json()[0]
        assert partial['ta_total'] == '2.50' and partial['combined_total'] == '6.50'
        assert partial['ta_review']['owner_name'] == 'helper1' and partial['ta_review']['provisional']
        assert write(first, base + '/finalize', {'version': 1}, first_csrf).status_code == 409
        finalized = write(first, base + '/finalize', {'version': 2}, first_csrf)
        assert finalized.status_code == 200 and finalized.json()['finalized']
        finished = first.get(ta_marks_path).json()[0]
        assert finished['ta_review']['reviewer_name'] == 'helper1' and not finished['ta_review']['provisional']
        with identity.engine().begin() as conn:
            password = identity.cipher().decrypt(conn.execute(sa.select(identity.accounts.c.encrypted_password)
                .where(identity.accounts.c.id == student_id)).scalar_one()).decode()
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(scoreboard_visible=True))
        with TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000)) as participant:
            student_csrf = login(participant, 'M24-001', password)['csrf_token']
            assert participant.get(staff_path).status_code == 403
            assert participant.get(ta_marks_path).status_code == 403
            entered = write(participant, f'/api/labs/{lab_id}/enter', {}, student_csrf)
            assert entered.status_code == 200, entered.text
            for path in (f'/api/labs/{lab_id}', f'/api/labs/{lab_id}/scoreboard'):
                response = participant.get(path)
                assert response.status_code == 200, response.text
                assert all(key not in response.text for key in ('ta_marks', 'ta_total', 'ta_review', 'ta_maximum', 'helper1'))
        overview = admin.get(f'/api/admin/labs/{lab_id}/ta-reviews')
        assert overview.status_code == 200 and overview.json()['students'][0]['combined_total'] == '6.50'
        assert write(second, base + '/reopen', {'version': 3}, second_csrf).status_code == 403
        reopened = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/reopen',
            {'version': 3, 'reason': 'Second review'}, admin_csrf)
        assert reopened.status_code == 200 and reopened.json()['tasks'][0]['done']
        assert admin.get(staff_path).json()[0]['ta_review']['provisional']
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        assert write(admin, f'/api/admin/labs/{lab_id}/tas',
            {'version': version, 'ids': [ta_ids[1]]}, admin_csrf, 'put').status_code == 409
        transferred = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/release',
            {'version': reopened.json()['version'], 'owner_id': ta_ids[1], 'reason': 'Hand off'}, admin_csrf)
        assert transferred.status_code == 200 and transferred.json()['owner_id'] == ta_ids[1]
        assert admin.get(staff_path).json()[0]['ta_review']['owner_name'] == 'helper2'
        completed = write(second, base + '/finalize',
            {'version': transferred.json()['version']}, second_csrf)
        assert completed.status_code == 200 and completed.json()['reviewer_name'] == 'helper2'
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        maximum = write(admin, f'/api/admin/labs/{lab_id}/tasks/{task_id}/ta-maximum',
            {'version': version, 'ta_maximum': '20.00', 'reason': 'Scale rubric'}, admin_csrf, 'put')
        assert maximum.status_code == 200, maximum.text
        assert first.get(base).json()['total'] == '5.00'
        scaled = admin.get(staff_path).json()[0]
        assert scaled['ta_total'] == '5.00' and scaled['combined_total'] == '9.00'
        assert scaled['tasks'][0]['ta_marks'] == '5.00' and scaled['tasks'][0]['ta_maximum'] == '20.00'
        with identity.engine().begin() as conn:
            ta_reviews.flag(conn, lab_id, student_id)
        flagged = admin.get(f'/api/admin/labs/{lab_id}/ta-reviews').json()['students'][0]['review']
        assert flagged['needs_recheck'] and flagged['total'] == '5.00'
        assert admin.get(staff_path).json()[0]['ta_review']['needs_recheck']
        acknowledged = write(admin, f'/api/admin/labs/{lab_id}/ta-reviews/{student_id}/acknowledge',
            {'version': flagged['version'], 'reason': 'Checked code'}, admin_csrf)
        assert acknowledged.status_code == 200 and not acknowledged.json()['needs_recheck']
        version = admin.get(f'/api/admin/labs/{lab_id}').json()['version']
        cancelled = write(admin, f'/api/admin/labs/{lab_id}/students/{student_id}/cancellation',
            {'version': version, 'cancelled': True, 'reason': 'Disqualified'}, admin_csrf, 'put')
        assert cancelled.status_code == 204
        excluded = admin.get(staff_path).json()[0]
        assert excluded['total'] is None and excluded['ta_total'] is None and excluded['combined_total'] is None
        assert excluded['tasks'][0]['ta_marks'] == '5.00'
        assert admin.get(f'/api/admin/labs/{lab_id}/ta-reviews').json()['students'][0]['combined_total'] is None
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id)
                .values(archived_at=datetime.now(timezone.utc)))
        assert first.get(base).status_code == 200
        assert write(second, base + '/reopen',
            {'version': acknowledged.json()['version']}, second_csrf).status_code == 409


def test_staff_marks_batching_zero_rounding_and_inactive_reviewer(ta_database) -> None:
    lab_id, task_id, revision_id, reviewer_id = [uuid4() for _ in range(4)]
    students = [uuid4() for _ in range(150)]
    config = TaskConfig(title='Sum').model_dump(mode='json')
    with identity.engine().begin() as conn:
        conn.execute(sa.insert(identity.accounts).values(id=reviewer_id, role='ta', username='OLDTA',
            name='Former TA', active=False, password_hash='unused'))
        conn.execute(sa.insert(identity.accounts), [dict(id=id, role='student', roll_number=f'M31-{i:03}',
            name=f'Student {i}', password_hash='unused', encrypted_password=b'unused') for i, id in enumerate(students)])
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Batch gate', version=1, strict_ip=False))
        conn.execute(sa.insert(labs.enrollments), [dict(lab_id=lab_id, account_id=id,
            cancelled=i == 2, frozen=i == 3) for i, id in enumerate(students)])
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, cases_key=uuid4(), case_count=1))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1,
            revision_id=revision_id, maximum_marks=5, ta_maximum=1))
        conn.execute(sa.insert(ta_reviews.reviews), [dict(lab_id=lab_id, student_id=id, version=1,
            reviewer_id=reviewer_id, finalized_at=datetime.now(timezone.utc), needs_recheck=False) for id in students[:4]])
        conn.execute(sa.insert(ta_reviews.marks), [dict(lab_id=lab_id, student_id=id, task_id=task_id,
            earned_numerator=0 if i == 0 else 1, earned_denominator=200 if i == 3 else 3,
            done=True) for i, id in enumerate(students[:4])])
        queries = []
        def count(*args):
            queries.append(1)
        sa.event.listen(conn, 'before_cursor_execute', count)
        try:
            one = ta_reviews.staff_marks(conn, lab_id, students[0])
            single_count = len(queries)
            queries.clear()
            rows = ta_reviews.staff_marks(conn, lab_id)
            assert len(rows) == 150 and len(queries) == single_count
        finally:
            sa.event.remove(conn, 'before_cursor_execute', count)
        assert one[0]['tasks'][0]['ta_marks'] == '0.00'
        assert rows[1]['ta_total'] == '0.33' and rows[1]['combined_total'] == '0.33'
        assert rows[1]['ta_review']['reviewer_name'] == 'Former TA'
        assert rows[2]['combined_total'] is None and rows[2]['tasks'][0]['ta_marks'] == '0.33'
        assert rows[3]['combined_total'] == '0.01'
        assert rows[4]['tasks'][0]['ta_marks'] is None and rows[4]['ta_review']['provisional']
        assert ta_reviews.staff_marks(conn, uuid4()) == []
        from cjudge.submissions import review
        assert 'ta_review' not in review.marks(conn, lab_id, students[0])[0]
        conn.execute(sa.update(labs.assignments).where(labs.assignments.c.lab_id == lab_id).values(ta_maximum=0))
        disabled = ta_reviews.staff_marks(conn, lab_id, students[4])[0]
        assert not disabled['ta_review']['provisional'] and disabled['tasks'][0]['ta_marks'] is None
