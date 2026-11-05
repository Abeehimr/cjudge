"""M32 whole-draft replacement contracts against disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import secrets
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa

from cjudge import authoring, identity, labs, submissions, tasks
from cjudge.api import app
from cjudge.submissions import review
from cjudge.tasks import bundle
from cjudge.tasks.cases import MAX_ZIP
from cjudge.tasks.grading import TaskConfig
from test_ta_gate import ORIGIN, ta_database, write


@pytest.fixture
def replacement(ta_database, tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, 'ARTIFACTS', tmp_path)
    tokens = {role: secrets.token_urlsafe(32) for role in ('admin', 'ta', 'student')}
    ids = {role: uuid4() for role in tokens}
    csrf = secrets.token_hex(32)
    with identity.engine().begin() as conn:
        for role, id in ids.items():
            conn.execute(sa.insert(identity.accounts).values(id=id, role=role,
                username=role.upper(), roll_number='STUDENT' if role == 'student' else None,
                name=role, password_hash='unused', encrypted_password=b'unused' if role == 'student' else None))
            conn.execute(sa.insert(identity.sessions).values(token_hash=identity.token_digest(tokens[role]),
                account_id=id, csrf_token=csrf, expires_at=identity.now() + timedelta(hours=1)))
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('cjudge_session', tokens['admin'])
        created = write(client, '/api/admin/tasks', {'title': 'Original'}, csrf).json()
        path = '/api/admin/tasks/' + created['id']
        draft = write(client, path + '/cases', {'version': 1, 'input': 'old', 'answer': 'answer'}, csrf).json()
        revision = write(client, path + '/publish', {'version': 2}, csrf).json()
        yield client, csrf, draft, revision, tokens, ids


def upload(client, csrf, draft, payload, version=2):
    return client.put(f'/api/admin/tasks/{draft["id"]}/import?version={version}', content=payload,
        headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf, 'Content-Type': 'application/zip'})


def test_complete_replacement_preserves_lab_results_and_invalidates_generation(replacement):
    client, csrf, draft, revision, _, ids = replacement
    lab_id, submission_id, attempt_id, job_id = [uuid4() for _ in range(4)]
    task_id, revision_id = UUID(draft['id']), UUID(revision['id'])
    with identity.engine().begin() as conn:
        timestamp = identity.now()
        conn.execute(sa.insert(labs.labs).values(id=lab_id, title='Existing lab', version=1, strict_ip=False))
        conn.execute(sa.insert(labs.assignments).values(lab_id=lab_id, position=1,
            revision_id=revision_id, maximum_marks=5, ta_maximum=0))
        conn.execute(sa.insert(labs.enrollments).values(lab_id=lab_id, account_id=ids['student']))
        conn.execute(sa.insert(submissions.submissions).values(id=submission_id, lab_id=lab_id,
            account_id=ids['student'], revision_id=revision_id, idempotency_key=uuid4(), filename='answer.c',
            sha256='0' * 64, size=1, accepted_at=timestamp, client_ip='192.0.2.1'))
        conn.execute(sa.insert(submissions.jobs).values(submission_id=submission_id, revision_id=revision_id,
            state='complete', attempt_id=attempt_id))
        conn.execute(sa.insert(submissions.attempts).values(id=attempt_id, submission_id=submission_id,
            worker_slot=0, worker_generation=uuid4(), started_at=timestamp,
            lease_until=timestamp + timedelta(seconds=60), finished_at=timestamp, outcome='complete'))
        conn.execute(sa.insert(submissions.runs).values(id=attempt_id, submission_id=submission_id,
            revision_id=revision_id, verdict='Passed', passed=1, total=1, score_numerator='5',
            score_denominator='1', compiler_feedback='', compiler_truncated=False, finished_at=timestamp))
        conn.execute(sa.insert(submissions.reviews).values(submission_id=submission_id, run_id=attempt_id))
        conn.execute(sa.insert(authoring.jobs).values(id=job_id, task_id=task_id, base_version=2,
            config={'count': 1}, state='complete', actor_id=ids['admin']))
        before = review.marks(conn, lab_id)
    config = TaskConfig(title='Replacement', statement='New statement', languages=['cpp17'],
        scoring='all_or_nothing', banned_identifiers=['while'], cpu_seconds=1, wall_seconds=3,
        memory_mib=128, stack_mib=4, stdout_mib=2,
        checker={'kind': 'python', 'source': 'accept()'})
    payload = bundle.build(config.model_dump(mode='json'), [(b'new', b'output'), (b'', b'')])
    response = upload(client, csrf, draft, payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['id'] == draft['id'] and result['created_at'] == draft['created_at']
    assert result['version'] == 3 and result['case_count'] == 2
    assert result['config'] == config.model_dump(mode='json')
    assert len(result['revisions']) == 1 and result['revisions'][0]['id'] == revision['id']
    path = '/api/admin/tasks/' + draft['id']
    assert client.get(path + '/cases/1/in').content == b'new'
    published = client.get(path + '/revisions/' + revision['id']).json()
    assert published['config']['title'] == 'Original' and published['case_count'] == 1
    assert client.get(path + '/cases/1/in?revision_id=' + revision['id']).content == b'old'
    assert write(client, path + f'/generation/{job_id}/apply', {'version': 3}, csrf).status_code == 409
    with identity.engine().connect() as conn:
        assert review.marks(conn, lab_id) == before
        assert conn.execute(sa.select(labs.assignments.c.revision_id)).scalar_one() == revision_id
    minimal = bundle.build({'title': 'Defaults'}, [(b'', b'')])
    reset = upload(client, csrf, draft, minimal, version=3).json()
    assert reset['config'] == TaskConfig(title='Defaults').model_dump(mode='json')
    assert reset['version'] == 4 and len(reset['revisions']) == 1


def test_rejected_uploads_and_storage_failures_preserve_draft(replacement, monkeypatch):
    client, csrf, draft, _, tokens, _ = replacement
    path = '/api/admin/tasks/' + draft['id']
    original = client.get(path).json()
    payload = bundle.build({'title': 'New'}, [(b'new', b'new')])
    assert upload(client, csrf, draft, b'invalid').status_code == 400
    assert upload(client, csrf, draft, b'x' * (MAX_ZIP + 1)).status_code == 413
    assert upload(client, csrf, draft, payload, version=1).status_code == 409
    assert upload(client, 'bad', draft, payload).status_code == 403
    assert upload(client, csrf, {**draft, 'id': str(uuid4())}, payload).status_code == 404
    assert client.put(path + '/import?version=2', json={},
        headers={'Origin': ORIGIN, 'X-CSRF-Token': csrf}).status_code == 415
    for role in ('student', 'ta'):
        client.cookies.set('cjudge_session', tokens[role])
        assert upload(client, csrf, draft, payload).status_code == 403
    client.cookies.clear()
    assert upload(client, csrf, draft, payload).status_code == 401
    client.cookies.set('cjudge_session', tokens['admin'])
    def unavailable(*args, **kwargs):
        raise OSError('Storage unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(tasks, 'save_cases', unavailable)
        assert upload(client, csrf, draft, payload, version=1).status_code == 409
        assert upload(client, csrf, draft, payload).status_code == 503
    def failed_audit(*args, **kwargs):
        raise RuntimeError('Transaction interrupted')
    with monkeypatch.context() as patch:
        patch.setattr(identity, 'audit', failed_audit)
        with pytest.raises(RuntimeError, match='Transaction interrupted'):
            upload(client, csrf, draft, payload)
    assert client.get(path).json() == original
    assert client.get(path + '/cases/1/in').content == b'old'


@pytest.mark.parametrize('competitor', ['replace', 'edit', 'publish'])
def test_replacement_serializes_with_other_draft_writes(replacement, competitor):
    client, csrf, draft, _, _, _ = replacement
    path = '/api/admin/tasks/' + draft['id']
    payload = bundle.build({'title': 'Imported'}, [(b'new', b'new')])
    version = 2
    if competitor == 'publish':
        assert write(client, path, {'version': 2, 'config': {'title': 'Before race'}}, csrf, 'put').status_code == 200
        version = 3
    def competing():
        if competitor == 'replace':
            return upload(client, csrf, draft, payload)
        if competitor == 'edit':
            return write(client, path, {'version': 2, 'config': {'title': 'Edited'}}, csrf, 'put')
        return write(client, path + '/publish', {'version': version}, csrf)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(upload, client, csrf, draft, payload, version)
        second = pool.submit(competing)
        statuses = [first.result().status_code, second.result().status_code]
    if competitor == 'publish':
        assert statuses[0] == 200 and statuses[1] in (201, 409)
    else:
        assert sorted(statuses) == [200, 409]
    final = client.get(path).json()
    assert final['version'] == version + 1
    assert len(final['revisions']) == (2 if 201 in statuses else 1)
    if 201 in statuses:
        published = client.get(path + '/revisions/' + final['revisions'][0]['id']).json()
        assert published['config']['title'] == 'Before race'
        assert client.get(path + '/cases/1/in?revision_id=' + published['id']).content == b'old'
    if final['config']['title'] == 'Imported':
        assert client.get(path + '/cases/1/in').content == b'new'
    else:
        assert final['config']['title'] == 'Edited'
        assert client.get(path + '/cases/1/in').content == b'old'
