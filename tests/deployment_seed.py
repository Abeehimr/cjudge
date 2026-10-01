"""Seed only the disposable acceptance project's database; stdout is private state."""
from datetime import timedelta
import json
import os
import secrets
import hashlib
from uuid import uuid4

import sqlalchemy as sa
from cjudge import identity, labs, tasks
from deployment_fixtures import fixtures

assert os.environ.get('CJUDGE_ACCEPTANCE') == '1', 'Disposable acceptance environment required'
with identity.engine().begin() as conn:
    assert not conn.execute(sa.select(labs.labs.c.id).limit(1)).first(), 'Fresh database required'
    timestamp = labs.now(conn)
    lab_id, admin_id = uuid4(), uuid4()
    csrf, admin_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conn.execute(sa.insert(identity.accounts).values(id=admin_id, role='admin', name='Acceptance', password_hash='unused'))
    conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(admin_token), account_id=admin_id,
        csrf_token=csrf, expires_at=timestamp + timedelta(hours=2)))
    conn.execute(sa.insert(labs.labs).values(id=lab_id, title='M9 acceptance', version=1,
        starts_at=timestamp - timedelta(minutes=1), ends_at=timestamp + timedelta(hours=2)))
    students, programs = [], []
    for index in range(170):
        account, session, binding = uuid4(), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        conn.execute(sa.insert(identity.accounts).values(id=account, role='student', name=f'Acceptance {index}',
            roll_number=f'M9-{index:03}', password_hash='unused', encrypted_password=b'unused'))
        conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(session), account_id=account,
            csrf_token=csrf, expires_at=timestamp + timedelta(hours=2)))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=account,
            binding_hash=identity.token_digest(binding), bound_ip='127.0.0.1', last_ip='127.0.0.1', bound_at=timestamp))
        students.append(f'cjudge_session={session}; cjudge_lab_{lab_id.hex}={binding}')
    for position, (title, source, cases) in enumerate(fixtures(), 1):
        task_id, revision = uuid4(), uuid4()
        config = dict(title=title, statement=f'M9 {title} fixture.', maximum_marks='10', scoring='partial',
            cpu_seconds=.2, wall_seconds=1, memory_mib=64, stack_mib=8, stdout_mib=1)
        key = tasks.save_cases(cases)
        conn.execute(sa.insert(tasks.tasks).values(id=task_id, version=1, config=config, case_count=10))
        conn.execute(sa.insert(tasks.revisions).values(id=revision, task_id=task_id, number=1, draft_version=1,
            config=config, case_count=10, cases_key=key))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=position, revision_id=revision))
        programs.append(dict(title=title, source=source, revision_id=str(revision), cases=10,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            cases_sha256=hashlib.sha256(json.dumps([(a.hex(), b.hex()) for a, b in cases]).encode()).hexdigest()))
print(json.dumps(dict(lab_id=str(lab_id), csrf=csrf, admin_cookie=f'cjudge_session={admin_token}', students=students, programs=programs)))
