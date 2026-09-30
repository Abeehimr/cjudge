"""Admission under enrollment locks; retries preserve original evidence."""
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from cjudge import events, labs
from cjudge.submissions import submissions, jobs, turns
from cjudge.submissions import files


class SubmissionError(ValueError):
    def __init__(self, status: int, code: str, message: str, retry_at=None) -> None:
        super().__init__(message)
        self.status, self.code, self.retry_at = status, code, retry_at


def allowance(conn: sa.Connection, lab: dict, enrollment: dict) -> dict:
    timestamp = labs.now(conn)
    where = (submissions.c.lab_id == lab['id'], submissions.c.account_id == enrollment['account_id'])
    last = conn.execute(sa.select(sa.func.max(submissions.c.accepted_at)).where(*where)).scalar_one()
    pending = conn.execute(sa.select(sa.func.count()).select_from(submissions.join(
        jobs, jobs.c.submission_id == submissions.c.id)).where(*where, jobs.c.state != 'complete')).scalar_one()
    retry_at = last + timedelta(seconds=30) if last else None
    reason, code = '', ''
    if labs.phase(lab, timestamp) != 'Running':
        reason, code = 'Lab is not running', 'lab_closed'
    elif enrollment['frozen']:
        reason, code = 'Submissions paused by administrator', 'frozen'
    elif pending >= 3:
        reason, code = 'Three submissions are pending', 'pending_limit'
    elif retry_at and timestamp < retry_at:
        reason, code = 'Wait 30 seconds between submissions', 'cooldown'
    return {'allowed': not reason, 'reason': reason, 'code': code, 'pending': pending,
            'retry_at': retry_at if code == 'cooldown' else None, 'server_time': timestamp}


def accept(conn: sa.Connection, lab: dict, enrollment: dict, revision_id: UUID, key: UUID,
           filename: str, source: bytes, ip: str) -> tuple[dict, bool]:
    digest = files.validate(filename, source)
    existing = conn.execute(sa.select(submissions).where(submissions.c.lab_id == lab['id'],
        submissions.c.account_id == enrollment['account_id'], submissions.c.idempotency_key == key)).mappings().first()
    if existing:
        if (existing['filename'], existing['revision_id'], existing['sha256']) != (filename, revision_id, digest):
            raise SubmissionError(409, 'idempotency_conflict', 'Idempotency key was used for different source or task')
        return dict(existing), False
    assigned = conn.execute(sa.select(labs.assignments.c.revision_id).where(
        labs.assignments.c.lab_id == lab['id'], labs.assignments.c.revision_id == revision_id)).first()
    if not assigned:
        raise SubmissionError(400, 'invalid_task', 'Task revision is not assigned to this lab')
    policy = allowance(conn, lab, enrollment)
    if not policy['allowed']:
        raise SubmissionError(429 if policy['code'] in ('cooldown', 'pending_limit') else 423 if policy['code'] == 'frozen' else 403,
                              policy['code'], policy['reason'], policy['retry_at'])
    submission_id = uuid4()
    files.lock(conn)
    files.save(submission_id, source)
    timestamp = labs.now(conn)
    labs.submission_allowed(lab, enrollment, timestamp)
    row = dict(id=submission_id, lab_id=lab['id'], account_id=enrollment['account_id'],
               revision_id=revision_id, idempotency_key=key, filename=filename, sha256=digest,
               size=len(source), accepted_at=timestamp, client_ip=ip,
               client_mac=None, mac_source=None, mac_observed_at=None)
    conn.execute(sa.insert(submissions).values(**row))
    conn.execute(sa.insert(jobs).values(submission_id=submission_id))
    conn.execute(insert(turns).values(account_id=enrollment['account_id']).on_conflict_do_nothing())
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))
    events.publish(conn, account_id=enrollment['account_id'])
    return row, True
