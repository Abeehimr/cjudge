"""M25 worker and API contract against disposable PostgreSQL."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet

from cjudge import identity, labs, submissions, tasks, tester
from cjudge.judging import worker
from cjudge.labs import archive
from cjudge.labs.api import snapshot
from cjudge.submissions.api import output, query
from cjudge.tasks.grading import TaskConfig
from cjudge.tester.api import source_view
from test_ta_gate import ta_database


def test_restricted_source_never_compiles_and_is_visible(ta_database, monkeypatch, tmp_path):
    key_file = tmp_path / 'credentials.key'
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(identity, 'KEY_FILE', key_file)
    lab_id, task_id, revision_id, submission_id, attempt_id = [uuid4() for _ in range(5)]
    config = TaskConfig(title='No printf', banned_identifiers=['printf']).model_dump(mode='json')
    timestamp = datetime.now(timezone.utc)
    with identity.engine().begin() as conn:
        student_id = identity.add_student(conn, 'M25-001', 'Ada')
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Restrictions', version=1, strict_ip=False))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student_id))
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
            draft_version=1, config=config, cases_key=uuid4(), case_count=1))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1,
            revision_id=revision_id, maximum_marks=5))
        conn.execute(sa.insert(submissions.submissions).values(id=submission_id, lab_id=lab_id,
            account_id=student_id, revision_id=revision_id, idempotency_key=uuid4(), filename='main.c',
            sha256='0' * 64, size=16, accepted_at=timestamp, client_ip='192.0.2.1'))
        conn.execute(sa.insert(submissions.jobs).values(submission_id=submission_id, revision_id=revision_id,
            state='complete', attempt_id=attempt_id))
        conn.execute(sa.insert(submissions.attempts).values(id=attempt_id, submission_id=submission_id,
            worker_slot=0, worker_generation=uuid4(), started_at=timestamp,
            lease_until=timestamp + timedelta(seconds=60), finished_at=timestamp, outcome='complete'))
    monkeypatch.setattr(worker.files, 'read', lambda row: b'// printf\nprintf("x");')
    monkeypatch.setattr(tester, 'read', lambda job, part: b'printf("x");')
    monkeypatch.setattr(tester.tasks, 'load_cases', lambda key: [(b'', b'')])
    monkeypatch.setattr(worker.runner, 'compile_c', lambda source: (_ for _ in ()).throw(AssertionError('compiled')))
    result = worker.judge({'revision_id': revision_id, 'lab_id': lab_id, 'id': submission_id}, None)
    assert result['verdict'] == 'Restricted' and result['restriction'] == {'identifier': 'printf', 'line': 2}
    assert result['score_numerator'] == '0' and result['cases'] == []
    tested = tester.run_case({'revision_id': revision_id, 'progress': 0})
    assert tested['verdict'] == 'Restricted' and tested['restriction']['line'] == 1
    batch_id, source_id, tester_attempt, generation, admin_id = [uuid4() for _ in range(5)]
    with identity.engine().begin() as conn:
        conn.execute(sa.insert(identity.accounts).values(id=admin_id, role='admin', username='ADMIN',
            name='Admin', password_hash='unused'))
        conn.execute(sa.insert(tester.batches).values(id=batch_id, task_id=task_id,
            revision_id=revision_id, actor_id=admin_id, payload_sha256='0' * 64))
        conn.execute(sa.insert(tester.sources).values(id=source_id, batch_id=batch_id, filename='main.c',
            size=12, sha256='0' * 64, state='testing', attempt_id=tester_attempt))
        conn.execute(sa.insert(tester.attempts).values(id=tester_attempt, source_id=source_id,
            worker_slot=0, worker_generation=generation, lease_until=timestamp + timedelta(minutes=5)))
        conn.execute(sa.insert(submissions.workers).values(slot=0, generation=generation, state='Testing',
            heartbeat_at=timestamp, started_at=timestamp, attempt_id=tester_attempt))
        assert tester.checkpoint(conn, tester_attempt, tested)
        source = dict(conn.execute(sa.select(tester.sources).where(tester.sources.c.id == source_id)).mappings().one())
        assert source['state'] == 'complete' and source['progress'] == 0
        assert source_view(source, 1)['verdict'] == 'Restricted source'
        assert source_view(source, 1)['restriction'] == {'identifier': 'printf', 'line': 1}
        conn.execute(sa.insert(submissions.runs).values(id=attempt_id, submission_id=submission_id,
            revision_id=revision_id, verdict=result['verdict'], passed=0, total=1,
            score_numerator='0', score_denominator='1', compiler_feedback='', compiler_truncated=False,
            restriction=result['restriction'], finished_at=timestamp))
        conn.execute(sa.insert(submissions.reviews).values(submission_id=submission_id, run_id=attempt_id))
        row = conn.execute(query(lab_id).where(submissions.submissions.c.id == submission_id)).mappings().one()
        response = output(row, 'none')
        assert response['status'] == 'Restricted source' and response['restriction'] == result['restriction']
        public = snapshot(conn, labs.find(conn, lab_id), labs.enrollment(conn, lab_id, student_id, lock=False))
        assert public['tasks'][0]['banned_identifiers'] == ['printf']
        current = archive.snapshot(conn, labs.find(conn, lab_id))
        previous = archive.snapshot(conn, labs.find(conn, lab_id), 3)
        assert current['runs'][0]['restriction'] == result['restriction']
        assert 'restriction' not in previous['runs'][0]
