"""M16 integration gate on a disposable PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import secrets
import tempfile
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from cjudge import identity, labs, tasks
from cjudge.labs import release


def main() -> None:
    name = 'concurrent_labs_gate_' + secrets.token_hex(8)
    root_url = sa.make_url(os.environ['DATABASE_URL'])
    root = sa.create_engine(root_url, isolation_level='AUTOCOMMIT')
    with root.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    os.environ['DATABASE_URL'] = root_url.set(database=name).render_as_string(hide_password=False)
    files = tempfile.TemporaryDirectory()
    previous_files = tasks.ARTIFACTS
    tasks.ARTIFACTS = Path(files.name)
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        admin, first, second, third = [uuid4() for _ in range(4)]
        with identity.engine().begin() as conn:
            conn.execute(sa.insert(identity.accounts).values(id=admin, role='admin', name='Admin', password_hash='unused'))
            conn.execute(sa.insert(identity.accounts), [dict(id=key, role='student', name=roll,
                roll_number=roll, password_hash='unused', encrypted_password=identity.cipher().encrypt(b'unused'))
                for key, roll in ((first, 'FIRST'), (second, 'SECOND'), (third, 'THIRD'))])
            a, b = [labs.create(conn, title, False, admin) for title in ('A', 'B')]

        def enroll(lab_id):
            try:
                with identity.engine().begin() as conn:
                    labs.enroll(conn, labs.find(conn, lab_id), [first], admin)
                return 'ok'
            except labs.LabError as exc:
                assert exc.status == 409
                return 'reserved'

        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(enroll, (a['id'], b['id']))) == ['ok', 'reserved']
        with identity.engine().begin() as conn:
            holder = conn.execute(sa.select(labs.enrollments.c.lab_id).where(
                labs.enrollments.c.account_id == first)).scalar_one()
            held = labs.find(conn, holder)
            other = labs.find(conn, b['id'] if holder == a['id'] else a['id'])
            assert labs.phase(held, labs.now(conn)) == 'Draft'
            report = labs.import_roster(conn, other, [('FIRST', 'FIRST'), ('SECOND', 'SECOND')], admin, partial=True)
            assert report['enrolled'] == ['SECOND'] and report['skipped'][0]['roll_number'] == 'FIRST'
            assert report['skipped'][0]['lab_id'] == str(holder)
            assert conn.execute(sa.select(sa.func.count()).select_from(labs.enrollments).where(
                labs.enrollments.c.lab_id == other['id'])).scalar_one() == 1
            try:
                labs.import_roster(conn, other, [('FIRST', 'FIRST')], admin)
            except labs.LabError as exc:
                assert exc.status == 409
            else:
                raise AssertionError('Manual conflict accepted')
            held = labs.enroll(conn, held, [third], admin)
            other = labs.find(conn, other['id'])
            future = labs.now(conn) + timedelta(hours=1)
            # Separate rosters may run at the same time.
            task_id, revision_id = uuid4(), uuid4()
            config = {'title': 'Task', 'statement': 'Add numbers.', 'maximum_marks': '5', 'scoring': 'partial'}
            conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
            conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
                draft_version=1, config=config, case_count=1, cases_key=tasks.save_cases([(b'1\n', b'2\n')])))
            for lab in (held, other):
                lab = labs.set_tasks(conn, lab, [{'revision_id': revision_id, 'maximum_marks': '5'}], admin)
                labs.schedule(conn, lab, future, future + timedelta(hours=1), admin)
            held = labs.find(conn, held['id'])
            held = labs.remove_students(conn, held, [first, third], admin)
            assert held['starts_at'] is None and held['ends_at'] is None
            other = labs.enroll(conn, labs.find(conn, other['id']), [first], admin)
            held = labs.enroll(conn, held, [third], admin)
            timestamp = labs.now(conn)
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == held['id']).values(
                starts_at=timestamp - timedelta(hours=1), ends_at=timestamp + timedelta(hours=1)))
            assert release.reuse(conn, other['id']) == [dict(id=held['id'], title=held['title'])]
            # First release frees reservations even if results are later hidden.
            conn.execute(sa.update(labs.labs).where(labs.labs.c.id == other['id']).values(
                starts_at=future - timedelta(days=2), ends_at=future - timedelta(days=1)))
            try:
                release.reveal(conn, labs.find(conn, other['id']), True, False, admin, 'Done')
            except labs.LabError as exc:
                assert exc.status == 409
            else:
                raise AssertionError('Reused running tests released without acknowledgment')
            other = release.reveal(conn, labs.find(conn, other['id']), True, True, admin, 'Done')
            release.reveal(conn, other, False, False, admin, 'Hide')
            labs.enroll(conn, held, [second], admin)
            try:
                labs.enroll(conn, labs.find(conn, other['id']), [third], admin)
            except labs.LabError as exc:
                assert exc.status == 409
            else:
                raise AssertionError('Enrollment after first release accepted')
        print('PASS: competing enrollments, partial CSV, overlapping labs, schedule removal, release reuse')
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        root.dispose()
        tasks.ARTIFACTS = previous_files
        files.cleanup()


if __name__ == '__main__':
    main()
