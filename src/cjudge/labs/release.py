"""Release policy shared by disclosure, sheets and archives."""
import hashlib
from uuid import UUID

import sqlalchemy as sa

from cjudge import identity, labs, tasks
from cjudge.submissions import submissions, jobs, reviews, batches, runs, attempts


def resolved(conn: sa.Connection, lab_id: UUID) -> None:
    unresolved = conn.execute(sa.select(submissions.c.id).join(jobs,
        jobs.c.submission_id == submissions.c.id).outerjoin(reviews,
        reviews.c.submission_id == submissions.c.id).where(submissions.c.lab_id == lab_id,
        reviews.c.deleted_at.is_(None), sa.or_(jobs.c.state != 'complete', reviews.c.run_id.is_(None))).limit(1)).first()
    batch = conn.execute(sa.select(batches.c.id).where(batches.c.lab_id == lab_id,
        batches.c.state == 'judging').limit(1)).first()
    if unresolved or batch:
        raise labs.LabError(409, 'Resolve active judging and correction batches before release or final export')


def revision_ids(conn: sa.Connection, lab_id: UUID) -> set[UUID]:
    result = set(conn.execute(sa.select(labs.assignments.c.revision_id).where(labs.assignments.c.lab_id == lab_id)).scalars())
    result.update(conn.execute(sa.select(submissions.c.revision_id).where(submissions.c.lab_id == lab_id)).scalars())
    result.update(conn.execute(sa.select(runs.c.revision_id).join(submissions,
        submissions.c.id == runs.c.submission_id).where(submissions.c.lab_id == lab_id)).scalars())
    for row in conn.execute(sa.select(batches.c.base_revision_id, batches.c.revision_id).where(batches.c.lab_id == lab_id)):
        result.update(row)
    return result


def fingerprints(conn: sa.Connection, ids: set[UUID]) -> set[bytes]:
    keys = conn.execute(sa.select(tasks.revisions.c.cases_key).where(tasks.revisions.c.id.in_(ids))).scalars()
    return {hashlib.sha256(len(i).to_bytes(8, 'big') + i + o).digest()
        for key in set(keys) for i, o in tasks.load_cases(key)}


def reuse(conn: sa.Connection, lab_id: UUID) -> list[dict]:
    other = conn.execute(sa.select(labs.labs.c.id, labs.labs.c.title).where(labs.labs.c.id != lab_id,
        labs.labs.c.starts_at > labs.now(conn))).mappings().all()
    if not other:
        return []
    disclosed = fingerprints(conn, revision_ids(conn, lab_id))
    result = []
    for row in other:
        ids = set(conn.execute(sa.select(labs.assignments.c.revision_id).where(labs.assignments.c.lab_id == row['id'])).scalars())
        if disclosed & fingerprints(conn, ids):
            result.append(dict(row))
    return result


def visible(lab: dict) -> None:
    if not lab['first_released_at'] or not lab['reveal_results']:
        raise labs.LabError(403, 'Submission details are hidden until results are released and reveal is enabled')


def reveal(conn: sa.Connection, lab: dict, enabled: bool, acknowledge: bool, actor: UUID, reason: str) -> dict:
    if not reason.strip():
        raise labs.LabError(400, 'Reason required')
    if enabled:
        if labs.phase(lab, labs.now(conn)) not in ('Ended', 'Results released', 'Archived'):
            raise labs.LabError(409, 'Release requires an ended lab')
        resolved(conn, lab['id'])
        warnings = reuse(conn, lab['id'])
        if warnings and not acknowledge:
            raise labs.LabError(409, 'Tests are reused by scheduled labs; acknowledge the disclosure warning')
    elif not lab['first_released_at']:
        raise labs.LabError(409, 'Results have not been released')
    values = {'reveal_results': enabled}
    if enabled and not lab['first_released_at']:
        values['first_released_at'] = labs.now(conn)
    identity.audit(conn, 'lab_reveal_reason', actor, detail={'lab_id': str(lab['id']),
        'reason': reason.strip(), 'reuse_acknowledged': acknowledge})
    return labs.changed(conn, lab, actor, 'lab_results_revealed' if enabled else 'lab_results_hidden', **values)


def archive(conn: sa.Connection, lab: dict, actor: UUID, reason: str) -> dict:
    from cjudge.judging import queue
    labs.editable(lab)
    if not lab['first_released_at'] or not reason.strip():
        raise labs.LabError(409, 'Archive requires released results and a reason')
    resolved(conn, lab['id'])
    queue.scheduler_lock(conn)
    # Excluded unfinished jobs cannot add evidence after the archive snapshot.
    ids = list(conn.execute(sa.select(submissions.c.id).join(reviews,
        reviews.c.submission_id == submissions.c.id).join(jobs, jobs.c.submission_id == submissions.c.id)
        .where(submissions.c.lab_id == lab['id'], reviews.c.deleted_at.is_not(None), jobs.c.state != 'complete')).scalars())
    if ids:
        conn.execute(sa.update(attempts).where(attempts.c.submission_id.in_(ids), attempts.c.finished_at.is_(None))
            .values(outcome='superseded', finished_at=labs.now(conn), lease_until=labs.now(conn)))
        conn.execute(sa.update(jobs).where(jobs.c.submission_id.in_(ids)).values(state='complete', attempt_id=None))
    identity.audit(conn, 'lab_archive_reason', actor, detail={'lab_id': str(lab['id']), 'reason': reason.strip()})
    return labs.changed(conn, lab, actor, 'lab_archived', archived_at=labs.now(conn))
