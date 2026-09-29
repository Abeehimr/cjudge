"""M4 integration gate. Uses a disposable database; never alters existing accounts/labs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from cjudge import identity, labs, tasks


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
    finally:
        identity.engine().dispose()
        identity.engine.cache_clear()
        with root.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        root.dispose()


if __name__ == '__main__':
    main()
