"""M6 disposable-database gate. Optional --sandbox exercises real isolate rejudging."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from fractions import Fraction
import csv
import io
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
from cjudge.labs import exports, release
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

    def call(path, method='GET', body=None, student=False, csrf_value=csrf, authenticated=True, bound=True):
        headers = {'Origin': os.getenv('CJUDGE_PUBLIC_ORIGIN', 'https://localhost:8443'), 'X-CSRF-Token': csrf_value}
        if authenticated:
            headers['Cookie'] = f'cjudge_session={student_token if student else admin_token}'
            if student and bound:
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
        board_path = base + '/scoreboard'
        public_board = f'/labs/{lab_id}/scoreboard'
        visibility = board_path + '/visibility'
        board = call(board_path)[1]
        assert [row['roll_number'] for row in board['students']] == ['Ada', 'Other']
        assert board['students'][0]['total'] == '2.33'
        assert board['students'][0]['elapsed_us'] == 1_000_000
        assert board['students'][0]['tasks'][0]['submission_id'] == str(first)
        assert board['students'][1]['tasks'][0]['state'] == 'judging'
        assert not call(base)[1]['scoreboard_visible']
        assert call(board_path, authenticated=False)[0] == 401
        assert call(board_path, student=True)[0] == 403
        assert call(public_board, student=True)[0] == 403
        version = call(base)[1]['version']
        setting = {'version': version, 'visible': True}
        assert call(visibility, 'PUT', setting, csrf_value='bad')[0] == 403
        assert call(visibility, 'PUT', setting, student=True)[0] == 403
        stale_setting = call(visibility, 'PUT', {**setting, 'version': version + 1})
        assert stale_setting[0] == 409, stale_setting
        assert call(visibility, 'PUT', setting)[0] == 200
        assert call(public_board, student=True, bound=False)[0] == 423
        stream_request = Request(f'http://127.0.0.1:8017/api/labs/{lab_id}/events', headers={
            'Cookie': f'cjudge_session={student_token}; cjudge_lab_{lab_id.hex}={binding}'})
        with urlopen(stream_request, timeout=5) as stream:
            assert stream.readline().strip() == b'event: refresh'
            assert stream.readline().strip() == b'data: {}'
            assert stream.readline().strip() == b''
            with identity.engine().begin() as conn:
                queue.notify(conn, other_id, lab_id=lab_id)
            assert stream.readline().strip() == b'event: refresh'
            assert stream.readline().strip() == b'data: {}'
        student_board = call(public_board, student=True)[1]
        assert student_board['students'][0]['tasks'][0]['submission_id'] == str(first)
        assert student_board['students'][1]['tasks'][0]['submission_id'] is None
        assert not {'source', 'compiler_feedback', 'client_ip', 'client_mac', 'cases', 'run_id'} & set(student_board['students'][0]['tasks'][0])
        assert call(f'/labs/{lab_id}/submissions/{first}/details', student=True)[0] == 403
        with identity.engine().begin() as conn:
            labs.freeze(conn, labs.find(conn, lab_id), student_id, True, 'Freeze test', admin_id)
        assert call(public_board, student=True)[1]['students'][0]['total'] == '2.33'
        with identity.engine().begin() as conn:
            labs.freeze(conn, labs.find(conn, lab_id), student_id, False, 'Resume test', admin_id)
        version = call(base)[1]['version']
        assert call(visibility, 'PUT', {'version': version, 'visible': False})[0] == 200
        assert call(public_board, student=True)[0] == 403
        assert any('Scoreboard hidden' in notice['body'] for notice in call(base)[1]['announcements'])
        print('PASS: scoreboard migration default, ranking, elapsed time, frozen marks, visibility/CSRF/version/binding gates and pre-release secrecy')
        assert call(base + '/marks', student=True)[0] == 403
        assert call(base + '/marks', authenticated=False)[0] == 401
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': 'x'}, csrf_value='bad')[0] == 403
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': ' '})[0] == 400
        rows = call(base + '/submissions?order=best')[1]
        assert rows[0]['id'] == str(first) and {row['id'] for row in rows[-2:]} == {str(deleted), str(excluded)}
        assert call(detail)[1]['ip_changed']
        student_path = f'/labs/{lab_id}/submissions'
        assert not {'passed', 'run_id', 'ip_changed', 'rejudge_status'} & call(student_path, student=True)[1][0].keys()
        assert call(f'{base}/submissions/{deleted}/source')[0] == 200
        assert call(student_path + f'/{deleted}', student=True)[1]['deleted_at'] is not None
        assert call(detail + '/review', 'PUT', {'deleted': True, 'reason': 'Exclude'})[0] == 204
        with identity.engine().connect() as conn:
            assert review.marks(conn, lab_id)[0]['tasks'][0]['best_submission_id'] == tie
        assert call(detail + '/review', 'PUT', {'deleted': False, 'reason': 'Restore'})[0] == 204
        original = call(detail)[1]['official_run_id']
        assert call(detail + '/rejudge', 'POST', {'expected_run_id': str(uuid4()), 'reason': 'stale'})[0] == 409
        assert call(detail + '/rejudge', 'POST', {'expected_run_id': original, 'reason': 'Verify'})[0] == 204
        notices = call(base)[1]['announcements']
        assert any(str(first) in row['body'] and 'Verify' in row['body'] and row['audience'].startswith('Only ') for row in notices)
        assert not any('stale' in row['body'] for row in notices)
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
        staged_board = call(board_path)[1]
        staged_marks = call(base + '/marks')[1]
        assert {row['roll_number']: row['total'] for row in staged_board['students']} == {row['roll_number']: row['total'] for row in staged_marks}
        assert all(row['pending'] for row in staged_board['students'])
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
            review.publish_ready(conn, lab_id)
            assert conn.execute(sa.select(sa.func.count()).select_from(labs.announcements).where(
                labs.announcements.c.lab_id == lab_id, labs.announcements.c.recipient_id.is_(None),
                labs.announcements.c.body.contains('rejudge completed'))).scalar_one() == 1
            scored_revisions = set(conn.execute(sa.select(store.runs.c.revision_id).join(store.reviews,
                store.reviews.c.run_id == store.runs.c.id).where(store.reviews.c.deleted_at.is_(None))).scalars())
            assert scored_revisions == {revisions[1]}
            assert all(row['total'] == '7.00' and not row['pending'] for row in review.marks(conn, lab_id))
            assert files.read(review.find_submission(conn, lab_id, first)) == GOOD
        published_board = call(board_path)[1]
        assert all(row['total'] == '7.00' and not row['pending'] for row in published_board['students'])
        assert sum(cell['state'] == 'first_solve' for row in published_board['students'] for cell in row['tasks']) == 1
        cancellation = f'{base}/students/{student_id}/cancellation'
        version = call(base)[1]['version']
        cancel = {'version': version, 'cancelled': True, 'reason': 'Attendance violation'}
        assert call(cancellation, 'PUT', cancel, csrf_value='bad')[0] == 403
        assert call(cancellation, 'PUT', cancel, student=True)[0] == 403
        assert call(cancellation, 'PUT', {**cancel, 'version': version + 1})[0] == 409
        assert call(cancellation, 'PUT', {**cancel, 'reason': ' '})[0] == 400
        with ThreadPoolExecutor(2) as pool:
            attempts = list(pool.map(lambda _: call(cancellation, 'PUT', cancel)[0], range(2)))
        assert sorted(attempts) == [204, 409]
        assert call(cancellation, 'PUT', {**cancel, 'version': version + 1})[0] == 409
        own = call(f'/labs/{lab_id}', student=True)[1]
        assert own['cancelled'] and own['cancel_reason'] == 'Attendance violation'
        assert own['admission']['code'] == 'cancelled'
        assert any('Attendance violation' in row['body'] and row['audience'] == 'Only you' for row in own['announcements'])
        assert next(row for row in call(base)[1]['students'] if row['id'] == str(student_id))['cancelled']
        board = call(board_path)[1]
        assert board['students'][-1]['roll_number'] == 'Ada' and board['students'][-1]['rank'] is None
        assert board['students'][-1]['total'] is None and board['students'][-1]['tasks'][0]['submission_id'] is None
        assert board['students'][0]['tasks'][0]['state'] == 'first_solve'
        with identity.engine().begin() as conn:
            current = labs.find(conn, lab_id, shared=True)
            assert next(row for row in review.marks(conn, lab_id) if row['id'] == student_id)['total'] is None
            sheet = list(csv.reader(io.StringIO(exports.sheet(conn, current).decode('utf-8-sig'))))
            ada = next(row for row in sheet if row[0] == 'Ada')
            assert ada[2:6] == ['Cancelled', '', '', '']
            release.resolved(conn, lab_id)
            existing = conn.execute(sa.select(store.submissions).where(store.submissions.c.id == first)).mappings().one()
            recovered, created = service.accept(conn, current, labs.enrollment(conn, lab_id, student_id),
                existing['revision_id'], existing['idempotency_key'], 'main.c', GOOD, '192.0.2.1')
            assert recovered['id'] == first and not created
            try:
                service.accept(conn, current, labs.enrollment(conn, lab_id, student_id),
                    revisions[1], uuid4(), 'new.c', GOOD, '192.0.2.1')
            except service.SubmissionError as exc: assert exc.code == 'cancelled'
            else: raise AssertionError('Cancelled student uploaded')
        restore = {'version': call(base)[1]['version'], 'cancelled': False, 'reason': 'Appeal accepted'}
        assert call(cancellation, 'PUT', restore)[0] == 204
        assert call(f'/labs/{lab_id}', student=True)[1]['cancelled'] is False
        assert call(board_path)[1]['students'] == published_board['students']
        with identity.engine().begin() as conn:
            savepoint = conn.begin_nested()
            labs.set_cancelled(conn, labs.find(conn, lab_id), student_id, True, 'Temporary test', admin_id)
            extra = seed(conn, owner=student_id, pending=True)
            release.resolved(conn, lab_id)
            next_batch = review.correct(conn, labs.find(conn, lab_id), task_id, revisions[2], admin_id,
                'Correction while student is cancelled')
            assert conn.execute(sa.select(store.batches.c.state).where(store.batches.c.id == next_batch)).scalar_one() == 'judging'
            labs.set_cancelled(conn, labs.find(conn, lab_id), other_id, True, 'Cancel remaining participant', admin_id)
            assert conn.execute(sa.select(store.batches.c.state).where(store.batches.c.id == next_batch)).scalar_one() == 'published'
            release.resolved(conn, lab_id)
            labs.set_cancelled(conn, labs.find(conn, lab_id), student_id, False, 'Reconcile test', admin_id)
            job = conn.execute(sa.select(store.jobs).where(store.jobs.c.submission_id == extra)).mappings().one()
            assert job['revision_id'] == revisions[2] and job['state'] == 'queued'
            assert conn.execute(sa.select(store.reviews.c.run_id).where(store.reviews.c.submission_id == first)).scalar_one() is None
            try: release.resolved(conn, lab_id)
            except labs.LabError: pass
            else: raise AssertionError('Reinstated pending work was released')
            savepoint.rollback()
        selected = call(detail)[1]
        if selected['cases']: assert selected['cases'][0]['stdin'] == '2 0\n'
        assert all(row['revision_id'] == str(revisions[1]) for row in call(student_path, student=True)[1])
        assert len([row for row in call(student_path + '?revision_id=' + str(revisions[1]), student=True)[1] if not row['deleted_at']]) == 5
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
        with identity.engine().connect() as conn:
            actions = set(conn.execute(sa.select(identity.audit_events.c.action).where(
                identity.audit_events.c.detail['lab_id'].as_string() == str(lab_id))).scalars())
            assert {'submission_deleted', 'submission_restored', 'submission_rejudge', 'submission_retry',
                'task_correction', 'task_correction_published', 'lab_announcement_posted'} <= actions
        with identity.engine().begin() as conn:
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab_id).values(archived_at=labs.now(conn)))
        version = call(base)[1]['version']
        assert call(visibility, 'PUT', {'version': version, 'visible': True})[0] == 409
        assert call(board_path)[0] == 200
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
