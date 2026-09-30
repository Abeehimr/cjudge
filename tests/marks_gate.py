"""M6 disposable-database gate. Optional --sandbox exercises real isolate rejudging."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from fractions import Fraction
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

from cjudge import identity, labs, tasks, submissions as store
from cjudge.judging import queue
from cjudge.submissions import files, review, service

GOOD = b'#include <stdio.h>\nint main(void){int a,b;scanf("%d%d",&a,&b);printf("%d\\n",a+b);}'


def exercise(directory: str) -> None:
    os.environ['CJUDGE_TASK_FILES'] = directory
    os.environ['CJUDGE_SUBMISSION_FILES'] = directory
    tasks.ARTIFACTS = Path(directory)
    admin_id, student_id, other_id, lab_id, task_id = [uuid4() for _ in range(5)]
    revisions = [uuid4() for _ in range(3)]
    csrf, admin_token, student_token, binding = [secrets.token_urlsafe(32) for _ in range(4)]
    generation = uuid4()
    def seed(conn, owner=student_id, score=Fraction(7, 3), seconds=0, ip='192.0.2.1', mac=None, pending=False):
        key, attempt = uuid4(), uuid4()
        digest = files.validate('main.c', GOOD); files.save(key, GOOD)
        conn.execute(sa.insert(store.submissions).values(id=key, lab_id=lab_id, account_id=owner,
            revision_id=revisions[0], idempotency_key=uuid4(), filename='main.c', size=len(GOOD), sha256=digest,
            accepted_at=timestamp + timedelta(seconds=seconds), client_ip=ip, client_mac=mac))
        conn.execute(sa.insert(store.jobs).values(submission_id=key, revision_id=revisions[0],
            state='queued' if pending else 'complete', attempt_id=None if pending else attempt))
        if not pending:
            conn.execute(sa.insert(store.attempts).values(id=attempt, submission_id=key, worker_slot=0,
                worker_generation=generation, started_at=timestamp, lease_until=timestamp + timedelta(seconds=60),
                finished_at=timestamp, outcome='complete'))
            conn.execute(sa.insert(store.runs).values(id=attempt, submission_id=key, revision_id=revisions[0],
                verdict='AC' if score == 7 else 'CE' if score == 0 else 'Failed', passed=3 if score == 7 else 0 if score == 0 else 1,
                total=3, score_numerator=str(score.numerator), score_denominator=str(score.denominator),
                compiler_feedback='error' if score == 0 else '', compiler_truncated=False, finished_at=timestamp))
        conn.execute(sa.insert(store.reviews).values(submission_id=key, run_id=None if pending else attempt))
        return key
    with identity.engine().begin() as conn:
        timestamp = labs.now(conn) - timedelta(minutes=5)
        for key, role, name in [(admin_id, 'admin', 'Admin'), (student_id, 'student', 'Ada'), (other_id, 'student', 'Other')]:
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name=name, password_hash='unused',
                roll_number=None if role == 'admin' else name, encrypted_password=None if role == 'admin' else b'unused'))
        for key, token in [(admin_id, admin_token), (student_id, student_token)]:
            conn.execute(sa.insert(identity.sessions).values(account_id=key, token_hash=identity.token_digest(token),
                csrf_token=csrf, expires_at=labs.now(conn) + timedelta(hours=1)))
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='M6 gate', version=1,
            starts_at=timestamp, ends_at=labs.now(conn) + timedelta(hours=1)))
        for key in (student_id, other_id):
            conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=key,
                binding_hash=identity.token_digest(binding) if key == student_id else None))
            conn.execute(sa.insert(store.turns).values(account_id=key))
        config = dict(title='Sum', statement='Add two integers.', maximum_marks='7', scoring='partial',
            cpu_seconds=.2, wall_seconds=1, memory_mib=32, stack_mib=8, stdout_mib=1)
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=3, config=config, case_count=3))
        for number, revision in enumerate(revisions, 1):
            pairs = [(f'{number} {i}\n'.encode(), f'{number + i}\n'.encode()) for i in range(3)]
            conn.execute(sa.insert(tasks.revisions).values(id=revision, task_id=task_id, number=number,
                draft_version=number, config=config, case_count=3, cases_key=tasks.save_cases(pairs)))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1, revision_id=revisions[0]))
        first = seed(conn, seconds=1, mac='02:00:00:00:00:01')
        tie = seed(conn, seconds=2, ip='192.0.2.2', mac='02:00:00:00:00:02')
        zero = seed(conn, score=Fraction(0), seconds=3)
        pending = seed(conn, owner=other_id, pending=True)
        deleted = seed(conn, score=Fraction(7), seconds=4)
        excluded = seed(conn, owner=other_id, score=Fraction(7), seconds=5)
        review.set_deleted(conn, labs.find(conn, lab_id), deleted, True, admin_id, 'Excluded evidence')
        review.set_deleted(conn, labs.find(conn, lab_id), excluded, True, admin_id, 'Excluded throughout correction')
        queue.register(conn, 0, generation); queue.worker_status(conn, 0, generation, 'Idle')
    # Backfill existing official results through the actual migration path.
    command.downgrade(Config('alembic.ini'), '20260930_submissions')
    subprocess.run(['python', '-m', 'alembic', 'upgrade', 'head'], check=True)
    with identity.engine().begin() as conn:
        review.set_deleted(conn, labs.find(conn, lab_id), deleted, True, admin_id, 'Reapply deletion after migration check')
        review.set_deleted(conn, labs.find(conn, lab_id), excluded, True, admin_id, 'Reapply excluded evidence')
        result = {row['id']: row for row in review.marks(conn, lab_id)}
        assert result[student_id]['tasks'][0]['best_submission_id'] == first
        assert result[student_id]['total'] == '2.33' and not result[student_id]['pending']
        assert result[other_id]['tasks'][0]['marks'] is None and result[other_id]['pending']
        savepoint = conn.begin_nested()
        review.set_deleted(conn, labs.find(conn, lab_id), pending, True, admin_id, 'No active submissions check')
        empty = next(row for row in review.marks(conn, lab_id) if row['id'] == other_id)
        assert empty['total'] == '0.00' and not empty['pending']
        savepoint.rollback()
        flags = review.network_flags(conn, lab_id)
        assert flags[student_id] == {'ip_changed': True, 'mac_changed': True}
        assert flags[other_id] == {'ip_changed': False, 'mac_changed': False}
    print('PASS: migration backfill, exact best/ties, later CE, half-up marks, deleted evidence and pending versus zero')

    def call(path, method='GET', body=None, student=False, csrf_value=csrf, authenticated=True):
        headers = {'Origin': 'https://localhost:8443', 'X-CSRF-Token': csrf_value}
        if authenticated:
            headers['Cookie'] = f'cjudge_session={student_token if student else admin_token}'
            if student:
                headers['Cookie'] += f'; cjudge_lab_{lab_id.hex}={binding}'
        payload = None
        if body is not None:
            headers['Content-Type'] = 'application/json'; payload = json.dumps(body).encode()
        try:
            response = urlopen(Request('http://127.0.0.1:8017/api' + path, method=method, data=payload, headers=headers), timeout=15)
        except HTTPError as exc:
            response = exc
        payload = response.read()
        return response.code, json.loads(payload) if payload and response.headers.get_content_type() == 'application/json' else payload
    base = f'/admin/labs/{lab_id}'
    detail = f'{base}/submissions/{first}'
    server = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1', '--port', '8017',
        '--no-proxy-headers'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if call(base + '/marks')[0] == 200: break
            except URLError:
                time.sleep(.1)
        else: raise AssertionError('M6 gate API did not start')
        assert call(base + '/marks', student=True)[0] == 403
        assert call(base + '/marks', authenticated=False)[0] == 401
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': 'x'}, csrf_value='bad')[0] == 403
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': ' '})[0] == 400
        rows = call(base + '/submissions?order=best')[1]
        assert rows[0]['id'] == str(first) and {row['id'] for row in rows[-2:]} == {str(deleted), str(excluded)}
        assert call(detail)[1]['ip_changed']
        student_path = f'/labs/{lab_id}/submissions'
        assert not {'passed', 'run_id', 'deleted_at', 'ip_changed', 'rejudge_status'} & call(student_path, student=True)[1][0].keys()
        assert call(f'{base}/submissions/{deleted}/source')[0] == 200
        assert call(student_path + f'/{deleted}', student=True)[0] == 404
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': 'Exclude'})[0] == 204
        with identity.engine().connect() as conn:
            assert review.marks(conn, lab_id)[0]['tasks'][0]['best_submission_id'] == tie
        assert call(detail + '/review', 'PUT', {'deleted': False, 'reason': 'Restore'})[0] == 204
        original = call(detail)[1]['official_run_id']
        assert call(detail + '/rejudge', 'POST', {'expected_run_id': str(uuid4()), 'reason': 'stale'})[0] == 409
        assert call(detail + '/rejudge', 'POST', {'expected_run_id': original, 'reason': 'Verify'})[0] == 204
        assert call(detail)[1]['official_run_id'] == original
        with identity.engine().begin() as conn:
            assert service.allowance(conn, labs.find(conn, lab_id, shared=True), labs.enrollment(conn, lab_id, student_id))['pending'] == 0
            live = queue.claim(conn, 0, generation)
            assert live['id'] == pending  # Live uploads precede rejudges.
            assert queue.finish(conn, 0, generation, live, dict(verdict='AC', passed=3, total=3,
                score_numerator='7', score_denominator='1', compiler_feedback='', compiler_truncated=False, cases=[]))
            active = queue.claim(conn, 0, generation)
            assert active['id'] == first
            conn.execute(sa.update(store.jobs).where(store.jobs.c.submission_id == first).values(retry_until=1))
            assert queue.fail(conn, active['attempt_id'], 'Single rejudge infrastructure fault')
        assert call(detail)[1]['official_run_id'] == original
        assert call(detail)[1]['rejudge_status'] == 'delayed'
        assert call(detail + '/retry', 'POST', {'reason': 'Repair single rejudge'})[0] == 204
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert active['id'] == first
            assert queue.finish(conn, 0, generation, active, dict(verdict='CE', passed=0, total=3,
                score_numerator='0', score_denominator='1', compiler_feedback='error', compiler_truncated=False, cases=[]))
            assert not queue.finish(conn, 0, generation, active, {})
        assert call(detail)[1]['official_run_id'] != original
        assert len(call(detail)[1]['history']) == 2
        assert call(detail + '?run_id=' + original)[1]['passed'] == 1
        assert call(detail + '?run_id=' + str(uuid4()))[0] == 404
        print('PASS: admin contracts, CSRF, deletion/restoration, student secrecy, live-job priority and retained rejudge history')

        with identity.engine().begin() as conn:
            superseded_id = seed(conn, owner=other_id, pending=True)
            stale = queue.claim(conn, 0, generation)
            assert stale['id'] == superseded_id
        version = call(base)[1]['version']
        correction = f'{base}/tasks/{task_id}/corrections'
        body = {'version': version, 'revision_id': str(revisions[1]), 'reason': 'Correct tests'}
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: call(correction, 'POST', body), range(2)))
        assert sorted(status for status, _ in responses) == [201, 409], responses
        batch_id = UUID(next(payload['id'] for status, payload in responses if status == 201))
        assert call(f'{base}/submissions/{zero}/review', 'PUT', {'deleted': True, 'reason': 'Delete during correction'})[0] == 204
        with identity.engine().begin() as conn:
            assert not queue.finish(conn, 0, generation, stale, {})
            assert conn.execute(sa.select(store.attempts.c.outcome).where(store.attempts.c.id == stale['attempt_id'])).scalar_one() == 'superseded'
        assert call(detail)[1]['official_run_id'] != original
        with identity.engine().begin() as conn:
            current = labs.find(conn, lab_id, shared=True)
            try:
                service.accept(conn, current, labs.enrollment(conn, lab_id, student_id), revisions[0], uuid4(), 'main.c', GOOD, '192.0.2.1')
            except service.SubmissionError as exc: assert exc.status == 409
            else: raise AssertionError('Stale revision accepted')
            new, _ = service.accept(conn, current, labs.enrollment(conn, lab_id, student_id), revisions[1], uuid4(), 'main.c', GOOD, '192.0.2.1')
            active = queue.claim(conn, 0, generation)
            assert active['id'] == new['id']
            assert queue.finish(conn, 0, generation, active, dict(verdict='AC', passed=3, total=3,
                score_numerator='7', score_denominator='1', compiler_feedback='', compiler_truncated=False, cases=[]))
            assert conn.execute(sa.select(store.reviews.c.run_id).where(store.reviews.c.submission_id == new['id'])).scalar_one() is None
        with identity.engine().begin() as conn:
            lab = labs.find(conn, lab_id)
            review.set_deleted(conn, lab, deleted, False, admin_id, 'Restore during correction')
            review.set_deleted(conn, lab, zero, False, admin_id, 'Restore a deleted batch member')
            assert conn.execute(sa.select(store.members.c.submission_id).where(store.members.c.batch_id == batch_id,
                store.members.c.submission_id == deleted)).first()
        originals = {}
        with identity.engine().connect() as conn:
            originals = dict(conn.execute(sa.select(store.reviews.c.submission_id, store.reviews.c.run_id)).all())
        completed = []
        while True:
            with identity.engine().begin() as conn:
                active = queue.claim(conn, 0, generation)
                if active is None: break
                # First fault must retain official marks and block publication.
                if not completed:
                    conn.execute(sa.update(store.jobs).where(store.jobs.c.submission_id == active['id']).values(retry_until=1))
                    assert queue.fail(conn, active['attempt_id'], 'Synthetic infrastructure failure')
                    blocked = active['id']; completed.append('fault'); continue
                assert queue.finish(conn, 0, generation, active, dict(verdict='AC', passed=3, total=3,
                    score_numerator='7', score_denominator='1', compiler_feedback='', compiler_truncated=False,
                    cases=[dict(number=1, verdict='AC', cpu_seconds=.1, wall_seconds=.1, memory_kib=1024,
                        stdout=b'2\n', stderr=b'', stdout_truncated=False, stderr_truncated=False)]))
            with identity.engine().begin() as conn:
                review.publish_ready(conn, lab_id)
                assert conn.execute(sa.select(store.batches.c.state).where(store.batches.c.id == batch_id)).scalar_one() == 'judging'
                assert dict(conn.execute(sa.select(store.reviews.c.submission_id, store.reviews.c.run_id)).all()) == originals
            completed.append(active['id'])
        assert call(f'{base}/submissions/{blocked}/retry', 'POST', {'reason': 'Repair'})[0] == 204
        with identity.engine().begin() as conn:
            active = queue.claim(conn, 0, generation)
            assert active['id'] == blocked
            result = dict(verdict='AC', passed=3, total=3, score_numerator='7', score_denominator='1',
                compiler_feedback='', compiler_truncated=False, cases=[])
            if '--sandbox' in sys.argv:
                from cjudge import runner
                from cjudge.judging.worker import judge
                runner.configure_box(0)
                result = judge(active, threading.Event())
                assert result['verdict'] == 'AC'
            assert queue.finish(conn, 0, generation, active, result)
        # Simulate crash after final result commit and before batch publication.
        with identity.engine().begin() as conn:
            review.publish_ready(conn, lab_id)
            assert conn.execute(sa.select(store.batches.c.state).where(store.batches.c.id == batch_id)).scalar_one() == 'published'
            scored_revisions = set(conn.execute(sa.select(store.runs.c.revision_id).join(store.reviews,
                store.reviews.c.run_id == store.runs.c.id).where(store.reviews.c.deleted_at.is_(None))).scalars())
            assert scored_revisions == {revisions[1]}
            assert all(row['total'] == '7.00' and not row['pending'] for row in review.marks(conn, lab_id))
            assert files.read(review.find_submission(conn, lab_id, first)) == GOOD
        selected = call(detail)[1]
        if selected['cases']: assert selected['cases'][0]['stdin'] == '2 0\n'
        assert all(row['revision_id'] == str(revisions[1]) for row in call(student_path, student=True)[1])
        assert len(call(student_path + '?revision_id=' + str(revisions[1]), student=True)[1]) == 5
        assert str(revisions[0]) in call(f'/labs/{lab_id}', student=True)[1]['tasks'][0]['previous_revision_ids']
        with identity.engine().begin() as conn:
            review.set_deleted(conn, labs.find(conn, lab_id), excluded, False, admin_id, 'Restore after publication')
            assert conn.execute(sa.select(store.reviews.c.run_id).where(store.reviews.c.submission_id == excluded)).scalar_one() is None
            assert conn.execute(sa.select(store.jobs.c.revision_id).where(store.jobs.c.submission_id == excluded)).scalar_one() == revisions[1]
            active = queue.claim(conn, 0, generation)
            assert active['id'] == excluded
            assert queue.finish(conn, 0, generation, active, dict(verdict='AC', passed=3, total=3,
                score_numerator='7', score_denominator='1', compiler_feedback='', compiler_truncated=False, cases=[]))
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(first_released_at=labs.now(conn), ends_at=labs.now(conn)))
            review.set_deleted(conn, labs.find(conn, lab_id), excluded, True, admin_id, 'Exclude unresolved historical rejudge')
            review.enqueue(conn, excluded, revisions[1], 'rejudge')
            conn.execute(sa.update(store.jobs).where(store.jobs.c.submission_id == excluded).values(state='delayed'))
        version = call(base)[1]['version']
        assert call(correction, 'POST', {'version': version, 'revision_id': str(revisions[2]), 'reason': 'Post-release correction'})[0] == 201
        assert call(base)[1]['phase'] == 'Results released'
        print('PASS: correction races, concurrent arrivals, restoration membership, infrastructure blocking, atomic recovery, immutable source and post-release corrections')
    finally:
        server.terminate(); server.wait(timeout=10)


def main() -> None:
    database = 'marks_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn: conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        with tempfile.TemporaryDirectory() as directory: exercise(directory)
    finally:
        identity.engine().dispose(); identity.engine.cache_clear()
        with root.connect() as conn: conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
