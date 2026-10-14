"""M24 disposable PostgreSQL gate; run inside the API container."""
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from cryptography.fernet import Fernet
import sqlalchemy as sa

from cjudge import identity, labs, tasks
from cjudge.labs import ta_reviews, archive
from cjudge.labs.exports import sheet
from cjudge.tasks.grading import TaskConfig


def main() -> None:
    root = sa.make_url(os.environ['DATABASE_URL'])
    name = 'm24_' + uuid4().hex[:12]
    server = sa.create_engine(root, isolation_level='AUTOCOMMIT')
    with server.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE {name}'))
    original_url = os.environ['DATABASE_URL']
    os.environ['DATABASE_URL'] = root.set(database=name).render_as_string(hide_password=False)
    identity.engine.cache_clear()
    try:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True,
            capture_output=True, env=os.environ.copy())
        with TemporaryDirectory() as tmp:
            identity.KEY_FILE = Path(tmp) / 'key'
            identity.KEY_FILE.write_bytes(Fernet.generate_key())
            admin_id, ta_id, other_ta, task_id, revision_id, lab_id = [uuid4() for _ in range(6)]
            config = TaskConfig(title='Sum').model_dump(mode='json')
            with identity.engine().begin() as conn:
                conn.execute(sa.insert(identity.accounts), [
                    dict(id=admin_id, role='admin', username='ADMIN', name='Admin', password_hash='hash'),
                    dict(id=ta_id, role='ta', username='TAONE', name='TA One', password_hash='hash'),
                    dict(id=other_ta, role='ta', username='TATWO', name='TA Two', password_hash='hash')])
                student_id = identity.add_student(conn, 'M24-001', 'Student')
                conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Review gate', version=1,
                    strict_ip=False, compiler_feedback='short', first_released_at=datetime.now(timezone.utc),
                    reveal_results=False))
                conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=student_id))
                conn.execute(sa.insert(labs.ta_assignments), [dict(lab_id=lab_id, ta_id=ta_id),
                    dict(lab_id=lab_id, ta_id=other_ta)])
                conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=1))
                conn.execute(sa.insert(tasks.revisions).values(id=revision_id, task_id=task_id, number=1,
                    draft_version=1, config=config, cases_key=uuid4(), case_count=1))
                conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1,
                    revision_id=revision_id, maximum_marks=5, ta_maximum=5))
            with identity.engine().begin() as conn:
                lab = labs.find(conn, lab_id)
                result = ta_reviews.claim(conn, lab, student_id, 0, ta_id)
                assert result['version'] == 1 and result['owner_id'] == ta_id
            with identity.engine().begin() as conn:
                lab = labs.find(conn, lab_id)
                try: ta_reviews.claim(conn, lab, student_id, 0, other_ta)
                except labs.LabError as exc: assert exc.status == 409
                else: raise AssertionError('Competing claim accepted')
                result = ta_reviews.save(conn, lab, student_id, task_id, 1, ta_id, Decimal('2.50'), True)
                assert result['total'] == '2.50' and result['tasks'][0]['done']
                assert result['provisional']
                result = ta_reviews.finalize(conn, lab, student_id, 2, ta_id)
                assert result['finalized'] and result['reviewer_name'] == 'TA One'
            with identity.engine().begin() as conn:
                ta_reviews.flag(conn, lab_id, student_id)
                flagged = ta_reviews.detail(conn, lab_id, student_id)
                assert flagged['needs_recheck'] and flagged['total'] == '2.50'
                conn.execute(sa.update(labs.assignments).where(labs.assignments.c.lab_id == lab_id)
                    .values(ta_maximum=Decimal('10.00')))
                scaled = ta_reviews.detail(conn, lab_id, student_id)
                assert scaled['total'] == '5.00' and scaled['tasks'][0]['marks'] == '5.00'
                csv = sheet(conn, labs.find(conn, lab_id))
                assert b'TA total' in csv and b'Needs recheck' in csv and b'5.00' in csv
                reopened = ta_reviews.reopen(conn, labs.find(conn, lab_id), student_id,
                    scaled['version'], ta_id)
                assert reopened['tasks'][0]['done'] and not reopened['finalized']
                released = ta_reviews.release(conn, labs.find(conn, lab_id), student_id,
                    reopened['version'], ta_id)
                assert released['owner_id'] is None and released['total'] == '5.00'
                transferred = ta_reviews.claim(conn, labs.find(conn, lab_id), student_id,
                    released['version'], other_ta)
                assert transferred['owner_id'] == other_ta
                completed = ta_reviews.finalize(conn, labs.find(conn, lab_id), student_id,
                    transferred['version'], other_ta)
                assert completed['finalized'] and not completed['needs_recheck']
                current_archive = archive.snapshot(conn, labs.find(conn, lab_id))
                legacy_archive = archive.snapshot(conn, labs.find(conn, lab_id), 2)
                assert current_archive['ta_reviews'] and current_archive['ta_review_marks']
                assert 'ta_reviews' not in legacy_archive and 'ta_maximum' not in legacy_archive['assignments'][0]
            print('M24 TA review gate passed')
    finally:
        identity.engine.cache_clear()
        os.environ['DATABASE_URL'] = original_url
        with server.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE {name} WITH (FORCE)'))
        server.dispose()


if __name__ == '__main__':
    main()
