"""M8 disposable database gate; never executes submitted source on the host."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import csv
import hashlib
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
from uuid import UUID, uuid4
import zipfile
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import identity, labs, tasks, submissions as store
from cjudge.labs import archive, files as pdf_files
from cjudge.submissions import files, service, review


def exercise(directory):
    for name in ('TASK', 'SUBMISSION', 'EXPORT', 'LAB'):
        os.environ[f'CJUDGE_{name}_FILES'] = directory
    tasks.ARTIFACTS = pdf_files.FILES = Path(directory)
    admin, student, other, lab_id, scheduled, task_id, revision = [uuid4() for _ in range(7)]
    token, student_token, binding, csrf, other_token, other_binding = [secrets.token_urlsafe(32) for _ in range(6)]
    source = b'int main(void){return 0;}'
    config = dict(title='=Task', statement='Optional **statement**', maximum_marks='10', scoring='partial',
        cpu_seconds=1, wall_seconds=2, memory_mib=64, stack_mib=8, stdout_mib=1)
    def seed(conn, owner, pending=False):
        key, attempt = uuid4(), uuid4()
        files.save(key, source)
        timestamp = labs.now(conn) - timedelta(minutes=1)
        conn.execute(sa.insert(store.submissions).values(id=key, lab_id=lab_id, account_id=owner,
            revision_id=revision, idempotency_key=uuid4(), filename='main.c', size=len(source),
            sha256=hashlib.sha256(source).hexdigest(), accepted_at=timestamp, client_ip='192.0.2.1'))
        conn.execute(sa.insert(store.jobs).values(submission_id=key, revision_id=revision,
            state='queued' if pending else 'complete', attempt_id=None if pending else attempt))
        if not pending:
            conn.execute(sa.insert(store.attempts).values(id=attempt, submission_id=key, worker_slot=0,
                worker_generation=uuid4(), started_at=timestamp, lease_until=timestamp,
                finished_at=timestamp, outcome='complete'))
            conn.execute(sa.insert(store.runs).values(id=attempt, submission_id=key, revision_id=revision,
                verdict='Failed', passed=1, total=2, score_numerator='5', score_denominator='1',
                compiler_feedback='', compiler_truncated=False, finished_at=timestamp))
            for number, verdict in ((1, 'WA'), (2, 'AC')):
                conn.execute(sa.insert(store.cases).values(run_id=attempt, number=number, verdict=verdict,
                    cpu_seconds=.01, wall_seconds=.02, memory_kib=100, stdout=b'wrong' if number == 1 else b'accepted',
                    stderr=b'', stdout_truncated=False, stderr_truncated=False))
        conn.execute(sa.insert(store.reviews).values(submission_id=key, run_id=None if pending else attempt))
        return key, attempt
    with identity.engine().begin() as conn:
        timestamp = labs.now(conn)
        for key, role, name in ((admin, 'admin', 'Admin'), (student, 'student', '=Ada'), (other, 'student', 'Other')):
            conn.execute(sa.insert(identity.accounts).values(id=key, role=role, name=name, password_hash='unused',
                roll_number=None if role == 'admin' else name, encrypted_password=None if role == 'admin' else b'private'))
        for key, value in ((admin, token), (student, student_token), (other, other_token)):
            conn.execute(sa.insert(identity.sessions).values(account_id=key, token_hash=identity.token_digest(value),
                csrf_token=csrf, expires_at=timestamp + timedelta(hours=1)))
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=2))
        pairs = [(b'x' * 65537, b'y' * 65537), (b'2', b'2')]
        conn.execute(sa.insert(tasks.revisions).values(id=revision, task_id=task_id, number=1, draft_version=1,
            config=config, cases_key=tasks.save_cases(pairs), case_count=2))
        for key, start, end in ((lab_id, timestamp - timedelta(hours=1), timestamp + timedelta(hours=1)),
                               (scheduled, timestamp + timedelta(days=1), timestamp + timedelta(days=1, hours=1))):
            conn.execute(sa.insert(labs.labs).values(id=key, title='M8 gate' if key == lab_id else 'Reused tests',
                version=1, starts_at=start, ends_at=end))
            conn.execute(sa.insert(labs.assignments).values(lab_id=key, revision_id=revision, position=1))
        for key in (student, other):
            conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=key,
                binding_hash=identity.token_digest(binding if key == student else other_binding)))
        submission, run = seed(conn, student)
        excluded, _ = seed(conn, other, True)
        alien, _ = seed(conn, other)
        pdf = pdf_files.save(b'%PDF-1.7\nlab tasks\n%%EOF')
        conn.execute(sa.insert(labs.pdfs).values(id=pdf, lab_id=lab_id, name='tasks.pdf', size=24, active=True))
        conn.execute(sa.update(labs.pdfs).where(labs.pdfs.c.id == pdf).values(size=(Path(directory) / f'{pdf}.pdf').stat().st_size))
    def call(path, method='GET', body=None, student_view=False, bad_csrf=False, bound=True, other_view=False):
        cookie = f'cjudge_session={other_token if other_view else student_token if student_view else token}'
        if (student_view or other_view) and bound: cookie += f'; cjudge_lab_{lab_id.hex}={other_binding if other_view else binding}'
        headers = {'Cookie': cookie, 'Origin': 'https://localhost:8443', 'X-CSRF-Token': 'bad' if bad_csrf else csrf}
        payload = None
        if body is not None: headers['Content-Type'] = 'application/json'; payload = json.dumps(body).encode()
        try: response = urlopen(Request('http://127.0.0.1:8019/api' + path, method=method, data=payload, headers=headers), timeout=30)
        except HTTPError as exc: response = exc
        value = response.read()
        return response.code, json.loads(value) if value and response.headers.get_content_type() == 'application/json' else value
    base = f'/admin/labs/{lab_id}'
    private = f'/labs/{lab_id}/submissions/{submission}'
    server = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1', '--port', '8019'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if call(base)[0] == 200: break
            except URLError: time.sleep(.1)
        else: raise AssertionError('API did not start')
        assert call(private + '/details', student_view=True)[0] == 403
        assert call(private + '/source', student_view=True)[0] == 403
        assert 'marks' not in call(private, student_view=True)[1]
        assert not any(row['best_for_review'] for row in call(f'/labs/{lab_id}/submissions', student_view=True)[1])
        assert call(base + '/stop', 'POST', {'version': 1, 'reason': 'Finished'}, bad_csrf=True)[0] == 403
        assert call(base + '/stop', 'POST', {'version': 1, 'reason': 'Finished'}, student_view=True)[0] == 403
        with ThreadPoolExecutor(2) as pool:
            stops = list(pool.map(lambda _: call(base + '/stop', 'POST', {'version': 1, 'reason': 'Finished'})[0], range(2)))
        assert sorted(stops) == [200, 409], stops
        assert call(base)[1]['phase'] == 'Ended'
        with identity.engine().begin() as conn:
            lab = labs.find(conn, lab_id)
            with conn.begin_nested() as savepoint:
                try: service.accept(conn, lab, labs.enrollment(conn, lab_id, student), revision, uuid4(), 'new.c', source, '192.0.2.1')
                except service.SubmissionError as exc: assert exc.code == 'lab_closed'
                else: raise AssertionError('New upload accepted after stop')
                savepoint.rollback()
            original = conn.execute(sa.select(store.submissions).where(store.submissions.c.id == submission)).mappings().one()
            recovered, created = service.accept(conn, lab, labs.enrollment(conn, lab_id, student), revision, original['idempotency_key'], 'main.c', source, '192.0.2.2')
            assert recovered['id'] == submission and not created
        def results(enabled=True, ack=True):
            return call(base + '/results', 'POST', {'version': call(base)[1]['version'], 'reason': 'Review complete',
                'enabled': enabled, 'acknowledge_reuse': ack})
        assert results()[0] == 409
        assert call(base + '/marks.csv')[0] == 409
        assert call(base + f'/submissions/{excluded}/review', 'PUT', {'reason': 'Excluded failed infrastructure', 'deleted': True})[0] == 204
        assert results(ack=False)[0] == 409
        assert call(base + '/release-warnings')[1][0]['title'] == 'Reused tests'
        assert results()[0] == 200
        released = call(base)[1]
        assert released['phase'] == 'Results released' and released['first_released_at']
        # Corrections cannot silently reveal scheduled tests after first release.
        next_revision = uuid4()
        with identity.engine().begin() as conn:
            cases_key = conn.execute(sa.select(tasks.revisions.c.cases_key).where(tasks.revisions.c.id == revision)).scalar_one()
            conn.execute(sa.insert(tasks.revisions).values(id=next_revision, task_id=task_id, number=2,
                draft_version=2, config=config, cases_key=cases_key, case_count=2))
        assert call(base + f'/tasks/{task_id}/corrections', 'POST', {'version': released['version'],
            'revision_id': str(next_revision), 'reason': 'Update tests'})[0] == 409
        assert call(base + '/deadline', 'POST', {'version': released['version'], 'action': 'reopen',
            'ends_at': (identity.now() + timedelta(hours=1)).isoformat(), 'reason': 'No'})[0] == 409
        status, detail = call(private + '/details', student_view=True)
        assert status == 200, detail
        assert detail['source'] == source.decode() and detail['marks'] == '5.00'
        assert not {'client_ip', 'attempts', 'fault', 'account_id'} & detail.keys()
        assert len(detail['cases'][0]['stdin']) == 65536 and detail['cases'][0]['stdin_truncated']
        assert detail['cases'][0]['expected_truncated'] and detail['cases'][1]['stdin'] is None
        assert call(private + f'/details?run_id={run}', student_view=True)[0] == 200
        assert call(private + f'/details?run_id={uuid4()}', student_view=True)[0] == 404
        assert call(f'/labs/{lab_id}/submissions/{alien}/details', student_view=True)[0] == 404
        assert call(private + '/details', student_view=True, bound=False)[0] == 423
        assert call(private + '/source', student_view=True)[1] == source
        assert next(row for row in call(base + '/submissions')[1] if row['id'] == str(submission))['best_for_review']
        assert next(row for row in call(f'/labs/{lab_id}/submissions', student_view=True)[1] if row['id'] == str(submission))['best_for_review']
        # Newest equal-score attempt is preferred for review; counted marks still use earliest.
        with identity.engine().begin() as conn:
            tie, _ = seed(conn, student)
            assert next(row for row in review.marks(conn, lab_id) if row['id'] == student)['tasks'][0]['best_submission_id'] == submission
        admin_rows = call(base + '/submissions')[1]
        assert next(row for row in admin_rows if row['id'] == str(tie))['best_for_review']
        assert not next(row for row in admin_rows if row['id'] == str(submission))['best_for_review']
        assert next(row for row in call(f'/labs/{lab_id}/submissions', student_view=True)[1] if row['id'] == str(tie))['best_for_review']
        assert call(base + f'/submissions/{tie}/review', 'PUT', {'reason': 'Exclude review tie', 'deleted': True})[0] == 204
        assert next(row for row in call(f'/labs/{lab_id}/submissions', student_view=True)[1] if row['id'] == str(submission))['best_for_review']
        own_rows = call(f'/labs/{lab_id}/submissions', student_view=True)[1]
        deleted_row = next(row for row in own_rows if row['id'] == str(tie))
        assert deleted_row['deleted_at'] and deleted_row['delete_reason'] == 'Exclude review tie'
        assert not deleted_row['best_for_review']
        assert call(f'/labs/{lab_id}/submissions/{tie}/details', student_view=True)[0] == 200
        own_notices = call(f'/labs/{lab_id}', student_view=True)[1]['announcements']
        other_notices = call(f'/labs/{lab_id}', other_view=True)[1]['announcements']
        assert any(str(tie) in notice['body'] and notice['audience'] == 'Only you' for notice in own_notices)
        assert not any(str(tie) in notice['body'] for notice in other_notices)
        assert not any('Excluded failed infrastructure' in notice['body'] for notice in own_notices)
        for notices in (own_notices, other_notices):
            assert any('Lab stopped' in notice['body'] and 'Finished' in notice['body'] for notice in notices)
            assert any('Results released' in notice['body'] for notice in notices)
        # Rejected repeated actions do not create duplicate announcements.
        count = len(own_notices)
        assert call(base + f'/submissions/{tie}/review', 'PUT', {'reason': 'Again', 'deleted': True})[0] == 409
        assert len(call(f'/labs/{lab_id}', student_view=True)[1]['announcements']) == count
        assert results(False)[0] == 200
        assert call(private + '/details', student_view=True)[0] == 403
        assert results()[0] == 200
        assert call(base)[1]['first_released_at'] == released['first_released_at']
        status, sheet = call(base + '/marks.csv'); assert status == 200
        csv_rows = list(csv.reader(io.StringIO(sheet.decode('utf-8-sig'))))
        ada = next(row for row in csv_rows if row[0] == "'=Ada")
        assert ada[1:6] == ["'=Ada", '5.00', '50.00', '5.00', '1'], ada
        assert csv_rows[0][2].startswith("'")
        assert call(base + '/marks.csv', student_view=True)[0] == 403
        assert call(base + '/archive', 'POST', {'version': call(base)[1]['version'], 'reason': 'Retain final lab'})[0] == 200
        archived = call(base)[1]; assert archived['phase'] == 'Archived'
        assert call(base + f'/submissions/{submission}/rejudge', 'POST', {'expected_run_id': str(run), 'reason': 'No'})[0] == 409
        assert call(base + '/announcements', 'POST', {'body': 'No'})[0] == 409
        assert call(base + f'/submissions/{excluded}/review', 'PUT', {'reason': 'No', 'deleted': False})[0] == 409
        # The narrow deletion exception never allows ordinary SQL deletes or updates.
        with identity.engine().begin() as conn:
            for statement in (sa.delete(store.submissions).where(store.submissions.c.id == submission),
                              sa.update(store.submissions).where(store.submissions.c.id == submission).values(filename='changed.c')):
                savepoint = conn.begin_nested()
                try: conn.execute(statement)
                except sa.exc.DBAPIError: savepoint.rollback()
                else: raise AssertionError('Immutable submission guard bypassed')
        def export():
            return call(base + '/exports', 'POST', {'version': call(base)[1]['version'], 'reason': 'Save archive'})
        status, receipt = export(); assert status == 201, receipt
        status, zipped = call(base + f'/exports/{receipt["id"]}'); assert status == 200
        assert hashlib.sha256(zipped).hexdigest() == receipt['sha256']
        with zipfile.ZipFile(io.BytesIO(zipped)) as zipped_file:
            manifest = json.loads(zipped_file.read('manifest.json'))
            assert manifest['version'] == 1
            assert f'sources/{excluded}.c' in zipped_file.namelist()
            assert f'pdfs/{pdf}.pdf' in zipped_file.namelist()
            evidence = json.loads(zipped_file.read('snapshot.json'))
            assert len(evidence['runs']) == 3 and evidence['reviews'] and evidence['marks']
            assert b'password_hash' not in zipped_file.read('snapshot.json') and b'binding_hash' not in zipped_file.read('snapshot.json')
            for entry in manifest['entries']:
                content = zipped_file.read(entry['path'])
                assert len(content) == entry['size'] and hashlib.sha256(content).hexdigest() == entry['sha256']
        assert call(base + f'/exports/{receipt["id"]}', student_view=True)[0] == 403
        def remove(receipt, saved=True, title='M8 gate'):
            return call(base, 'DELETE', {'version': call(base)[1]['version'], 'reason': 'Stored safely', 'title': title,
                'saved_copy': saved, 'export_id': receipt['id']})
        assert remove(receipt, saved=False)[0] == 400
        assert remove(receipt, title='Wrong')[0] == 400
        assert results(False)[0] == 200
        assert remove(receipt)[0] == 409
        # Missing artifact fails export without registering success.
        pdf_path = Path(directory) / f'{pdf}.pdf'; backup = pdf_path.read_bytes(); pdf_path.unlink()
        assert export()[0] == 503
        pdf_path.write_bytes(backup)
        status, receipt = export(); assert status == 201, receipt
        status, result = remove(receipt); assert status == 200 and result['cleanup_pending'] == 0, result
        assert call(base)[0] == 404
        assert not (Path(directory) / f'{submission}.c').exists()
        assert not pdf_path.exists()
        with identity.engine().connect() as conn:
            assert conn.execute(sa.select(tasks.revisions.c.id).where(tasks.revisions.c.id == revision)).scalar_one() == revision
            assert conn.execute(sa.select(identity.accounts.c.id).where(identity.accounts.c.id == student)).scalar_one() == student
            assert conn.execute(sa.select(labs.labs.c.id).where(labs.labs.c.id == scheduled)).scalar_one() == scheduled
            assert conn.execute(sa.select(identity.audit_events.c.id).where(identity.audit_events.c.action == 'lab_permanently_deleted')).first()
            actions = set(conn.execute(sa.select(identity.audit_events.c.action).where(
                identity.audit_events.c.detail['lab_id'].as_string() == str(lab_id))).scalars())
            assert {'lab_stop_reason', 'lab_reveal_reason', 'lab_archive_reason', 'lab_export_generated',
                'lab_export_downloaded', 'lab_permanently_deleted'} <= actions
        # Cleanup failure leaves a durable retry record after the lab is gone.
        orphan = uuid4(); path = Path(directory) / f'{orphan}.c'; path.write_bytes(source)
        with identity.engine().begin() as conn:
            conn.execute(sa.insert(archive.cleanup_files).values(lab_id=lab_id, kind='source', artifact_id=orphan))
        with patch.object(Path, 'unlink', side_effect=OSError('Disk unavailable')):
            assert archive.cleanup(lab_id) == 1
        assert path.exists()
        assert call(base + '/cleanup', 'POST')[1]['cleanup_pending'] == 0
        assert not path.exists()
        print('PASS: Stop now, concurrent versions, retries, release/reuse gates, student privacy, retained runs, CSV, verified archives and permanent deletion')
    finally:
        server.terminate(); server.wait(timeout=10)


def main():
    database = 'release_gate_' + secrets.token_hex(8)
    url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn: conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = url.set(database=database).render_as_string(hide_password=False)
    try:
        subprocess.run(['python', '-m', 'alembic', 'upgrade', '20261002_authoring'], check=True)
        legacy = uuid4()
        with identity.engine().begin() as conn:
            conn.execute(sa.text('INSERT INTO labs(id,title,version) VALUES (:id,:title,1)'), {'id': legacy, 'title': 'Existing M7 lab'})
        subprocess.run(['python', '-m', 'alembic', 'upgrade', 'head'], check=True)
        with identity.engine().begin() as conn:
            old = labs.find(conn, legacy)
            assert not old['reveal_results'] and old['archived_at'] is None
            conn.execute(sa.delete(labs.labs).where(labs.labs.c.id == legacy))
        with tempfile.TemporaryDirectory() as directory: exercise(directory)
    finally:
        identity.engine().dispose(); identity.engine.cache_clear()
        with root.connect() as conn: conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__': main()
