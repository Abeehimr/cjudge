"""M4 integration gate. Uses a disposable database; never alters existing accounts/labs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import json
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from cjudge import identity, labs, tasks
from cjudge.labs import binding as lab_binding, files as lab_files


def core_checks():
    with identity.engine().begin() as conn:
        admin_id, student_id, task_id, revision_id = uuid4(), uuid4(), uuid4(), uuid4()
        conn.execute(sa.insert(identity.accounts).values(id=admin_id, role='admin', name='Admin', password_hash='unused'))
        conn.execute(sa.insert(identity.accounts).values(id=student_id, role='student', name='Student', roll_number='GATE',
            password_hash='unused', encrypted_password=identity.cipher().encrypt(b'unused')))
        config = {'title': 'Sum', 'statement': 'Add numbers.', 'maximum_marks': '100', 'scoring': 'partial'}
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
        conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1, draft_version=1,
                                                       config=config, case_count=1, cases_key=uuid4()))
        a = labs.create(conn, 'A', False, admin_id)
        b = labs.create(conn, 'B', False, admin_id)
        for lab in [a, b]:
            conn.execute(sa.insert(labs.enrollments).values(lab_id=lab['id'], account_id=student_id))
            labs.set_tasks(conn, lab, [revision_id], admin_id)
        timestamp = labs.now(conn)
    def schedule(key):
        try:
            with identity.engine().begin() as conn:
                labs.schedule(conn, labs.find(conn, key), timestamp + timedelta(hours=1),
                              timestamp + timedelta(hours=2), admin_id)
            return 'ok'
        except IntegrityError as exc:
            assert labs.overlap_error(exc).status == 409
            return 'overlap'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(schedule, [a['id'], b['id']])) == ['ok', 'overlap']
    with identity.engine().begin() as conn:
        winner = conn.execute(sa.select(labs.labs).where(labs.labs.c.starts_at.is_not(None))).mappings().one()
        loser = b if winner['id'] == a['id'] else a
        labs.schedule(conn, labs.find(conn, loser['id']), winner['ends_at'], winner['ends_at'] + timedelta(hours=1), admin_id)
        assert labs.task_rows(conn, winner['id'])[0]['id'] == revision_id
        try:
            labs.find(conn, winner['id'], 1)
        except labs.LabError as exc:
            assert exc.status == 409
        else:
            raise AssertionError('Stale edit allowed')
    print('PASS: migrations, scheduling races, adjacent windows, stale versions, pinned task revisions')
    return admin_id, student_id, revision_id


def roster_checks(admin_id, student_id, revision_id):
    with identity.engine().begin() as conn:
        a = labs.create(conn, 'Roster', False, admin_id)
        b = labs.create(conn, 'Other roster', False, admin_id)
        result = labs.import_roster(conn, a, [('GATE', 'Different'), ('LATE', 'Late Student')], admin_id)
        assert result == {'created': ['LATE'], 'existing': ['GATE'], 'name_mismatches': ['GATE']}
        assert conn.execute(sa.select(identity.accounts.c.name).where(identity.accounts.c.id == student_id)).scalar_one() == 'Student'
        labs.enroll(conn, b, [student_id], admin_id)
        labs.freeze(conn, a, student_id, True, 'Review', admin_id)
        assert labs.enrollment(conn, a['id'], student_id)['frozen']
        assert not labs.enrollment(conn, b['id'], student_id)['frozen']
        labs.freeze(conn, a, student_id, False, 'Resolved', admin_id)
        assert not labs.enrollment(conn, a['id'], student_id)['frozen']
        timestamp = labs.now(conn)
        conn.execute(sa.update(labs.labs).where(labs.labs.c.id == a['id']).values(
            starts_at=timestamp - timedelta(days=2), ends_at=timestamp - timedelta(days=1)))
        current = labs.find(conn, a['id'])
        labs.enroll(conn, current, [student_id], admin_id)
        try:
            labs.remove_student(conn, current, student_id, admin_id)
        except labs.LabError as exc:
            assert exc.status == 409
        else:
            raise AssertionError('Late removal allowed')
    print('PASS: account reuse, atomic enrollment, name mismatch, late additions, freeze isolation')


def binding_checks(admin_id, student_id, revision_id):
    session = secrets.token_urlsafe(32)
    with identity.engine().begin() as conn:
        timestamp = labs.now(conn)
        conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(session), account_id=student_id,
                    csrf_token='csrf', expires_at=timestamp + timedelta(hours=8)))
        lab = labs.create(conn, 'Binding', False, admin_id)
        labs.enroll(conn, lab, [student_id], admin_id)
        conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(
            starts_at=timestamp - timedelta(hours=2), ends_at=timestamp - timedelta(hours=1)))
        lab = labs.find(conn, lab['id'])
        _, token = lab_binding.access(conn, lab, student_id, session, None, '192.0.2.1', enter=True)
        assert token
        for missing in [None, 'wrong']:
            try:
                lab_binding.access(conn, lab, student_id, session, missing, '192.0.2.1', enter=True)
            except labs.LabError as exc:
                assert exc.status == 423
            else:
                raise AssertionError('Missing binding accepted')
        row, _ = lab_binding.access(conn, lab, student_id, session, token, '192.0.2.2')
        assert row['ip_changed'] and row['bound_ip'] == '192.0.2.1'
        strict = {**lab, 'strict_ip': True}
        try:
            lab_binding.access(conn, strict, student_id, session, token, '192.0.2.2')
        except labs.LabError as exc:
            assert exc.status == 423
        else:
            raise AssertionError('Strict IP accepted changed address')
        lab_binding.release(conn, lab, student_id, 'New browser', admin_id)
        try:
            lab_binding.access(conn, lab, student_id, session, None, '192.0.2.1', enter=True)
        except labs.LabError as exc:
            assert exc.status == 401
        else:
            raise AssertionError('Revoked session rebound')
    print('PASS: ended-lab binding, token loss, IP flags, strict IP, release and revoked-session fencing')


def pdf_checks(admin_id, student_id, revision_id):
    with tempfile.TemporaryDirectory() as directory:
        lab_files.FILES = Path(directory)
        data = b'%PDF-1.7\nexample\n%%EOF\n'
        with identity.engine().begin() as conn:
            lab = labs.create(conn, 'PDFs', False, admin_id)
            lab = lab_files.upload(conn, lab, data, 'Lab one.pdf', admin_id)
            lab = lab_files.upload(conn, lab, data, 'Lab two.pdf', admin_id)
            originals = list(conn.execute(sa.select(labs.pdfs.c.id).where(labs.pdfs.c.lab_id == lab['id'])).scalars())
            assert len(originals) == 2
            timestamp = labs.now(conn)
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(
                starts_at=timestamp - timedelta(minutes=20), ends_at=timestamp + timedelta(minutes=20)))
            lab = labs.find(conn, lab['id'])
            lab_files.upload(conn, lab, data, 'Updated.pdf', admin_id, originals[0])
            assert conn.execute(sa.select(sa.func.count()).select_from(labs.announcements).where(
                labs.announcements.c.lab_id == lab['id'])).scalar_one() == 1
            assert lab_files.read(conn, lab['id'], originals[0], active_only=False) == data
            try:
                lab_files.read(conn, lab['id'], originals[0], active_only=True)
            except labs.LabError as exc:
                assert exc.status == 404
            else:
                raise AssertionError('Superseded PDF visible to student')
            (Path(directory) / f'{originals[1]}.pdf').unlink()
            try:
                lab_files.read(conn, lab['id'], originals[1], active_only=False)
            except labs.LabError as exc:
                assert exc.status == 503
            else:
                raise AssertionError('Missing PDF silently accepted')
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(ends_at=labs.now(conn)))
    print('PASS: multiple PDFs, retained versions, automatic update notice, active-only download, storage faults')


def api_checks(admin_id, student_id, revision_id):
    cookies = {role: secrets.token_urlsafe(32) for role in ['admin', 'student', 'outsider']}
    csrf = secrets.token_hex(32)
    with identity.engine().begin() as conn:
        outsider = uuid4()
        conn.execute(sa.insert(identity.accounts).values(id=outsider, role='student', roll_number='OUTSIDER',
            name='Not enrolled', password_hash='unused', encrypted_password=identity.cipher().encrypt(b'unused')))
        for role, account_id in [('admin', admin_id), ('student', student_id), ('outsider', outsider)]:
            conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(cookies[role]),
                account_id=account_id, csrf_token=csrf, expires_at=labs.now(conn) + timedelta(hours=8)))
    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, 'CJUDGE_LAB_FILES': directory, 'CJUDGE_PROXY_HOST': '127.0.0.1'}
        service = subprocess.Popen(['python', '-m', 'uvicorn', 'cjudge.api:app', '--host', '127.0.0.1',
            '--port', '8012', '--no-proxy-headers'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def call(path, method='GET', body=None, role='admin', binding=None, content_type='application/json', token=csrf, ip='192.0.2.1'):
            data = json.dumps(body).encode() if body is not None and content_type == 'application/json' else body
            headers = {'Origin': 'https://localhost:8443', 'X-CSRF-Token': token, 'Content-Type': content_type, 'X-Real-IP': ip}
            if role:
                headers['Cookie'] = 'cjudge_session=' + cookies[role] + ('; ' + binding if binding else '')
            try:
                response = urlopen(Request('http://127.0.0.1:8012/api' + path, data=data, headers=headers, method=method), timeout=10)
            except HTTPError as exc:
                return exc.code, None, exc.headers
            data = response.read()
            return response.status, json.loads(data) if data and response.headers.get_content_type() == 'application/json' else data, response.headers
        try:
            for _ in range(100):
                try:
                    if call('/admin/labs')[0] == 200:
                        break
                except URLError:
                    time.sleep(.1)
            else:
                raise AssertionError('Test API did not start')
            assert call('/admin/labs', role='student')[0] == 403
            assert call('/labs', role='admin')[0] == 403
            assert call('/admin/labs', 'POST', {'title': 'API'}, token='wrong')[0] == 403
            status, lab, _ = call('/admin/labs', 'POST', {'title': 'API'})
            assert status == 201
            path = '/admin/labs/' + lab['id']
            student_path = '/labs/' + lab['id']
            _, lab, _ = call(path + '/tasks', 'PUT', {'version': lab['version'], 'revision_ids': [str(revision_id)]})
            _, lab, _ = call(path + '/students', 'POST', {'version': lab['version'], 'ids': [str(student_id)]})
            data = b'%PDF-1.7\nlab\n%%EOF\n'
            _, lab, _ = call(path + '/pdfs?version=' + str(lab['version']) + '&name=Lab.pdf', 'POST', data, content_type='application/pdf')
            pdf_id = lab['pdfs'][0]['id']
            future = identity.now() + timedelta(days=3)
            status, lab, _ = call(path + '/schedule', 'POST', {'version': lab['version'], 'starts_at': future.isoformat(),
                'ends_at': (future + timedelta(hours=2)).isoformat()})
            assert status == 200
            assert call(student_path, role='student')[0] == 403
            assert call(student_path + '/pdfs/' + pdf_id, role='student')[0] == 403
            summaries = call('/labs', role='student')[1]
            assert all('tasks' not in item and 'pdfs' not in item for item in summaries)
            assert call(path + '/announcements', 'POST', {'body': 'Before start'})[0] == 200
            status, lab, _ = call(path + '/schedule', 'POST', {'version': lab['version'],
                'ends_at': (identity.now() + timedelta(minutes=2)).isoformat()})
            assert status == 200
            status, student_view, headers = call(student_path + '/enter', 'POST', role='student')
            assert status == 200
            binding = headers['Set-Cookie'].split(';', 1)[0]
            assert 'HttpOnly' in headers['Set-Cookie'] and 'Secure' in headers['Set-Cookie'] and 'SameSite=lax' in headers['Set-Cookie']
            assert student_view['announcements'][0]['body'] == 'Before start'
            assert 'checker' not in student_view['tasks'][0] and 'cases' not in student_view['tasks'][0]
            assert call('/labs', role='outsider')[1] == []
            for suffix in ['', '/pdfs/' + pdf_id, '/events']:
                assert call(student_path + suffix, role='outsider', binding=binding)[0] == 403
            assert call(student_path, role='student')[0] == 423
            assert call(student_path + '/pdfs/' + pdf_id, role='student', binding=binding)[1] == data
            assert call(path + '/tasks', 'PUT', {'version': lab['version'], 'revision_ids': []})[0] == 409
            assert call(path + '/students/' + str(student_id), 'DELETE')[0] == 422
            assert call(path + '/students/' + str(student_id) + '?version=' + str(lab['version']), 'DELETE')[0] == 409
            def open_events():
                return urlopen(Request('http://127.0.0.1:8012/api' + student_path + '/events', headers={
                    'Cookie': 'cjudge_session=' + cookies['student'] + '; ' + binding,
                    'X-Real-IP': '192.0.2.1'}), timeout=10)
            def read_event(stream):
                lines = []
                while True:
                    line = stream.readline()
                    if not line or line == b'\n':
                        return b''.join(lines)
                    lines.append(line)
            stream = open_events()
            assert 'text/event-stream' in stream.headers['Content-Type']
            assert b'event: refresh' in read_event(stream)
            assert call(path + '/announcements', 'POST', {'body': 'Live notice'})[0] == 200
            assert b'event: refresh' in read_event(stream)
            assert call(student_path, role='student', binding=binding)[1]['announcements'][-1]['body'] == 'Live notice'
            stream.close()
            stream = open_events()
            assert b'event: refresh' in read_event(stream)
            freeze_path = path + '/students/' + str(student_id) + '/freeze'
            assert call(freeze_path, 'POST', {'frozen': True, 'reason': 'Review'})[0] == 204
            assert call(student_path, role='student', binding=binding)[1]['frozen']
            assert call(freeze_path, 'POST', {'frozen': False, 'reason': 'Resolved'})[0] == 204
            assert not call(student_path, role='student', binding=binding)[1]['frozen']
            status, lab, _ = call(path + '/pdfs?version=' + str(lab['version']) + '&name=New.pdf&replaces=' + pdf_id,
                'POST', data, content_type='application/pdf')
            assert status == 200 and len(lab['pdfs']) == 2
            assert call(student_path + '/pdfs/' + pdf_id, role='student', binding=binding)[0] == 404
            assert call(path + '/pdfs/' + pdf_id)[1] == data
            assert 'PDF replaced' in call(student_path, role='student', binding=binding)[1]['announcements'][-1]['body']
            status, lab, _ = call(path + '/deadline', 'POST', {'version': lab['version'], 'action': 'extend',
                'reason': 'Extra time', 'ends_at': (identity.now() + timedelta(minutes=3)).isoformat()})
            assert status == 200
            with identity.engine().begin() as conn:
                conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(first_released_at=labs.now(conn)))
            assert call(path + '/deadline', 'POST', {'version': lab['version'], 'action': 'extend',
                'reason': 'Bad', 'ends_at': (identity.now() + timedelta(minutes=4)).isoformat()})[0] == 409
            with identity.engine().begin() as conn:
                conn.execute(sa.update(labs.labs).where(labs.labs.c.id == lab['id']).values(first_released_at=None, ends_at=labs.now(conn)))
            status, lab, _ = call(path + '/deadline', 'POST', {'version': lab['version'], 'action': 'reopen',
                'reason': 'Reopened', 'ends_at': (identity.now() + timedelta(minutes=4)).isoformat()})
            assert status == 200
            assert call(path + '/students/' + str(student_id) + '/release', 'POST', {'reason': 'Replace browser'})[0] == 204
            assert call(student_path + '/enter', 'POST', role='student')[0] == 401
            for _ in range(20):
                event = read_event(stream)
                if b'event: denied' in event:
                    break
            else:
                raise AssertionError('Revoked live connection stayed authorized')
            stream.close()
            print('PASS: live announcements, reconnect refresh, bounded invalidations, revoked SSE access')
            print('PASS: HTTP roles/CSRF, pre-start secrecy, PDF authorization, freeze, setup locks, extensions/reopen/release guards')
        finally:
            service.terminate()
            service.wait(timeout=10)


def main():
    database = 'lab_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{database}"')
    os.environ['DATABASE_URL'] = root_url.set(database=database).render_as_string(hide_password=False)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        actors = core_checks()
        roster_checks(*actors)
        binding_checks(*actors)
        pdf_checks(*actors)
        api_checks(*actors)
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
