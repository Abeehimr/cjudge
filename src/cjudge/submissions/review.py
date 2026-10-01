"""Official marks and audited corrections; immutable evidence is never rewritten."""
from decimal import Decimal
from fractions import Fraction
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from cjudge import identity, labs, tasks
from cjudge.submissions import submissions, jobs, runs, reviews, batches, members, attempts


def displayed(value: Fraction) -> str:
    # Exact half-up rounding without Decimal context precision loss.
    cents = (value.numerator * 200 + value.denominator) // (2 * value.denominator)
    return f'{cents // 100}.{cents % 100:02d}'


def exact(row: dict) -> Fraction:
    return Fraction(int(row['score_numerator']), int(row['score_denominator']))


def counted_submission(rows) -> dict | None:
    scored = [row for row in rows if row['run_id'] is not None]
    return min(scored, key=lambda row: (-exact(row), row['accepted_at'], str(row['id']))) if scored else None


def official_query(lab_id: UUID):
    return sa.select(submissions, tasks.revisions.c.task_id, reviews.c.run_id, reviews.c.deleted_at,
        reviews.c.delete_reason, runs.c.score_numerator, runs.c.score_denominator, runs.c.passed, runs.c.total,
        jobs.c.state, jobs.c.kind, jobs.c.batch_id).select_from(submissions.join(tasks.revisions,
        tasks.revisions.c.id == submissions.c.revision_id).outerjoin(reviews,
        reviews.c.submission_id == submissions.c.id).outerjoin(runs, runs.c.id == reviews.c.run_id)
        .join(jobs, jobs.c.submission_id == submissions.c.id)).where(submissions.c.lab_id == lab_id)


def marks(conn: sa.Connection, lab_id: UUID) -> list[dict]:
    assigned = labs.task_rows(conn, lab_id)
    task_ids = {row['task_id'] for row in assigned}
    all_rows = conn.execute(official_query(lab_id).where(reviews.c.deleted_at.is_(None))).mappings().all()
    grouped = {}
    for row in all_rows:
        grouped.setdefault((row['account_id'], row['task_id']), []).append(row)
    active_batches = set(conn.execute(sa.select(batches.c.task_id).where(
        batches.c.lab_id == lab_id, batches.c.state == 'judging')).scalars())
    students = conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number, identity.accounts.c.name)
        .join(labs.enrollments, labs.enrollments.c.account_id == identity.accounts.c.id)
        .where(labs.enrollments.c.lab_id == lab_id).order_by(identity.accounts.c.roll_number)).mappings()
    result = []
    for student in students:
        cells, total_cents = [], 0
        for task in assigned:
            rows = grouped.get((student['id'], task['task_id']), [])
            best = counted_submission(rows)
            value = displayed(exact(best)) if best else '0.00'
            pending = bool(rows) and task['task_id'] in active_batches or any(row['state'] != 'complete' or row['run_id'] is None for row in rows)
            cells.append(dict(task_id=task['task_id'], revision_id=task['id'], title=task['config']['title'],
                marks=value if best or not pending else None, pending=pending,
                best_submission_id=best['id'] if best else None, passed=best['passed'] if best else None,
                total=best['total'] if best else None))
            total_cents += int(Decimal(value) * 100)
        result.append(dict(**student, tasks=cells, total=f'{total_cents // 100}.{total_cents % 100:02d}',
            pending=any(cell['pending'] for cell in cells), submission_count=sum(len(grouped.get((student['id'], key), [])) for key in task_ids)))
    return result


def best_for_review(conn: sa.Connection, lab_id: UUID, account_id: UUID | None = None) -> set[UUID]:
    selection = official_query(lab_id).where(reviews.c.deleted_at.is_(None), reviews.c.run_id.is_not(None))
    if account_id:
        selection = selection.where(submissions.c.account_id == account_id)
    best = {}
    for row in conn.execute(selection).mappings():
        key = (row['account_id'], row['task_id'])
        priority = (exact(row), row['accepted_at'], -row['id'].int)
        if key not in best or priority > best[key][0]:
            best[key] = (priority, row['id'])
    return {row[1] for row in best.values()}


def network_flags(conn: sa.Connection, lab_id: UUID) -> dict[UUID, dict]:
    rows = conn.execute(sa.select(submissions.c.account_id, submissions.c.client_ip, submissions.c.client_mac)
        .where(submissions.c.lab_id == lab_id)).mappings()
    addresses = {}
    for row in rows:
        ip, mac = addresses.setdefault(row['account_id'], (set(), set()))
        ip.add(row['client_ip'])
        if row['client_mac']:
            mac.add(row['client_mac'])
    return {key: dict(ip_changed=len(ip) > 1, mac_changed=len(mac) > 1) for key, (ip, mac) in addresses.items()}


def ensure_review(conn: sa.Connection, submission_id: UUID) -> None:
    conn.execute(insert(reviews).values(submission_id=submission_id).on_conflict_do_nothing())


def find_submission(conn: sa.Connection, lab_id: UUID, submission_id: UUID) -> dict:
    row = conn.execute(sa.select(submissions).where(submissions.c.lab_id == lab_id,
        submissions.c.id == submission_id)).mappings().first()
    if not row:
        raise labs.LabError(404, 'Submission not found')
    return dict(row)


def task_id_for(conn: sa.Connection, revision_id: UUID) -> UUID:
    value = conn.execute(sa.select(tasks.revisions.c.task_id).where(tasks.revisions.c.id == revision_id)).scalar_one_or_none()
    if value is None:
        raise labs.LabError(404, 'Task revision not found')
    return value


def current_revision(conn: sa.Connection, lab_id: UUID, task_id: UUID) -> UUID:
    value = conn.execute(sa.select(labs.assignments.c.revision_id).join(tasks.revisions,
        tasks.revisions.c.id == labs.assignments.c.revision_id).where(labs.assignments.c.lab_id == lab_id,
        tasks.revisions.c.task_id == task_id)).scalar_one_or_none()
    if value is None:
        raise labs.LabError(409, 'Task is no longer assigned')
    return value


def active_batch(conn: sa.Connection, lab_id: UUID, task_id: UUID) -> dict | None:
    return conn.execute(sa.select(batches).where(batches.c.lab_id == lab_id,
        batches.c.task_id == task_id, batches.c.state == 'judging')).mappings().first()


def enqueue(conn: sa.Connection, submission_id: UUID, revision_id: UUID, kind: str, batch_id: UUID | None = None) -> None:
    # Reset the current job token; already running attempts are fenced at finish.
    job = conn.execute(sa.select(jobs).where(jobs.c.submission_id == submission_id).with_for_update()).mappings().one()
    if job['state'] == 'judging' and job['attempt_id']:
        conn.execute(sa.update(attempts).where(attempts.c.id == job['attempt_id']).values(
            outcome='superseded', finished_at=labs.now(conn), lease_until=labs.now(conn)))
    conn.execute(sa.update(jobs).where(jobs.c.submission_id == submission_id).values(
        kind=kind, revision_id=revision_id, batch_id=batch_id, state='queued', attempt_id=None,
        retry_until=jobs.c.attempt_count + 3, ready_at=labs.now(conn)))
    conn.execute(sa.select(sa.func.pg_notify('cjudge_jobs', '')))


def set_deleted(conn: sa.Connection, lab: dict, submission_id: UUID, deleted: bool, actor: UUID, reason: str) -> None:
    from cjudge.judging import queue
    labs.editable(lab)
    queue.scheduler_lock(conn)
    row = find_submission(conn, lab['id'], submission_id)
    ensure_review(conn, submission_id)
    state = conn.execute(sa.select(reviews).where(reviews.c.submission_id == submission_id).with_for_update()).mappings().one()
    if bool(state['deleted_at']) == deleted:
        raise labs.LabError(409, 'Submission review state already changed')
    conn.execute(sa.update(reviews).where(reviews.c.submission_id == submission_id).values(
        deleted_at=labs.now(conn) if deleted else None, deleted_by=actor if deleted else None,
        delete_reason=reason if deleted else None))
    if not deleted:
        task_id = task_id_for(conn, row['revision_id'])
        batch = active_batch(conn, lab['id'], task_id)
        if batch:
            conn.execute(insert(members).values(batch_id=batch['id'], submission_id=submission_id)
                .on_conflict_do_nothing())
            member = conn.execute(sa.select(members.c.run_id).where(members.c.batch_id == batch['id'],
                members.c.submission_id == submission_id)).scalar_one()
            if member is None:
                enqueue(conn, submission_id, batch['revision_id'], 'correction', batch['id'])
        else:
            revision = current_revision(conn, lab['id'], task_id)
            run_revision = conn.execute(sa.select(runs.c.revision_id).where(runs.c.id == state['run_id'])).scalar_one_or_none()
            if run_revision != revision:
                conn.execute(sa.update(reviews).where(reviews.c.submission_id == submission_id).values(run_id=None))
                enqueue(conn, submission_id, revision, 'rejudge')
    identity.audit(conn, 'submission_deleted' if deleted else 'submission_restored', actor, row['account_id'],
        detail={'lab_id': str(lab['id']), 'submission_id': str(submission_id), 'reason': reason})
    labs.announce(conn, lab['id'], f'Submission {submission_id} {"deleted from marks" if deleted else "restored"}. Reason: {reason}', actor, row['account_id'])
    queue.notify(conn, row['account_id'])


def rejudge(conn: sa.Connection, lab: dict, submission_id: UUID, actor: UUID, reason: str) -> None:
    from cjudge.judging import queue
    labs.editable(lab)
    queue.scheduler_lock(conn)
    row = find_submission(conn, lab['id'], submission_id)
    ensure_review(conn, submission_id)
    state = conn.execute(sa.select(reviews).where(reviews.c.submission_id == submission_id)).mappings().one()
    task_id = task_id_for(conn, row['revision_id'])
    if state['deleted_at'] or active_batch(conn, lab['id'], task_id):
        raise labs.LabError(409, 'Restore submission or wait for the correction batch')
    job = conn.execute(sa.select(jobs).where(jobs.c.submission_id == submission_id).with_for_update()).mappings().one()
    if job['state'] != 'complete':
        raise labs.LabError(409, 'Wait for current judging or retry its delayed job')
    enqueue(conn, submission_id, current_revision(conn, lab['id'], task_id), 'rejudge')
    identity.audit(conn, 'submission_rejudge', actor, row['account_id'],
        detail={'lab_id': str(lab['id']), 'submission_id': str(submission_id), 'reason': reason})
    labs.announce(conn, lab['id'], f'Submission {submission_id} queued for rejudge. Reason: {reason}', actor, row['account_id'])
    queue.notify(conn, row['account_id'])


def correct(conn: sa.Connection, lab: dict, task_id: UUID, revision_id: UUID, actor: UUID, reason: str, acknowledge_reuse: bool = False) -> UUID:
    from cjudge.judging import queue
    labs.editable(lab)
    queue.scheduler_lock(conn)
    if labs.phase(lab, labs.now(conn)) not in ('Running', 'Ended', 'Results released'):
        raise labs.LabError(409, 'Corrections require a running or ended lab')
    base = current_revision(conn, lab['id'], task_id)
    if task_id_for(conn, revision_id) != task_id:
        raise labs.LabError(400, 'Select a published revision of the same task')
    if lab.get('reveal_results'):
        from cjudge.labs.release import reuse
        labs.disclosure_lock(conn)
        if reuse(conn, lab['id'], revision_id) and not acknowledge_reuse:
            raise labs.LabError(409, 'Correction reveals reused tests; acknowledge the warning or hide results first')
    if base == revision_id or active_batch(conn, lab['id'], task_id):
        raise labs.LabError(409, 'Select a different revision and wait for the current correction')
    selection = sa.select(submissions.c.id).join(tasks.revisions, tasks.revisions.c.id == submissions.c.revision_id)
    ids = conn.execute(selection.where(submissions.c.lab_id == lab['id'], tasks.revisions.c.task_id == task_id)).scalars().all()
    if ids and conn.execute(sa.select(jobs.c.submission_id).outerjoin(reviews,
            reviews.c.submission_id == jobs.c.submission_id).where(jobs.c.submission_id.in_(ids),
            reviews.c.deleted_at.is_(None), jobs.c.kind != 'initial', jobs.c.state != 'complete')).first():
        raise labs.LabError(409, 'Wait for current rejudges')
    batch_id = uuid4()
    conn.execute(sa.insert(batches).values(id=batch_id, lab_id=lab['id'], task_id=task_id,
        base_revision_id=base, revision_id=revision_id, actor_id=actor, reason=reason))
    for key in ids:
        ensure_review(conn, key)
        if conn.execute(sa.select(reviews.c.deleted_at).where(reviews.c.submission_id == key)).scalar_one() is None:
            conn.execute(sa.insert(members).values(batch_id=batch_id, submission_id=key))
            enqueue(conn, key, revision_id, 'correction', batch_id)
    conn.execute(sa.update(labs.assignments).where(labs.assignments.c.lab_id == lab['id'],
        labs.assignments.c.revision_id == base).values(revision_id=revision_id))
    title = conn.execute(sa.select(tasks.revisions.c.config).where(tasks.revisions.c.id == revision_id)).scalar_one()['title']
    labs.changed(conn, lab, actor, 'task_correction_started',
        message=f'Problem {title} updated; active submissions are being rejudged. Reason: {reason}')
    identity.audit(conn, 'task_correction', actor, detail={'lab_id': str(lab['id']), 'task_id': str(task_id),
        'batch_id': str(batch_id), 'revision_id': str(revision_id), 'reason': reason, 'reuse_acknowledged': acknowledge_reuse})
    queue.notify(conn)
    return batch_id


def publish_ready(conn: sa.Connection, lab_id: UUID) -> None:
    from cjudge.judging import queue
    lab = labs.find(conn, lab_id)
    for batch in conn.execute(sa.select(batches).where(batches.c.lab_id == lab_id, batches.c.state == 'judging')).mappings().all():
        unresolved = conn.execute(sa.select(members.c.submission_id).join(reviews,
            reviews.c.submission_id == members.c.submission_id).where(members.c.batch_id == batch['id'],
            reviews.c.deleted_at.is_(None), members.c.run_id.is_(None)).limit(1)).first()
        if unresolved:
            continue
        staged = conn.execute(sa.select(jobs.c.submission_id, jobs.c.attempt_id).join(runs, runs.c.id == jobs.c.attempt_id)
            .where(jobs.c.batch_id == batch['id'], jobs.c.state == 'complete')).all()
        for key, run_id in staged:
            conn.execute(sa.update(reviews).where(reviews.c.submission_id == key).values(run_id=run_id))
        conn.execute(sa.update(batches).where(batches.c.id == batch['id']).values(state='published', published_at=labs.now(conn)))
        conn.execute(sa.update(jobs).where(jobs.c.batch_id == batch['id']).values(batch_id=None))
        identity.audit(conn, 'task_correction_published', batch['actor_id'], detail={'lab_id': str(lab_id), 'batch_id': str(batch['id'])})
        title = conn.execute(sa.select(tasks.revisions.c.config).where(tasks.revisions.c.id == batch['revision_id'])).scalar_one()['title']
        labs.announce(conn, lab_id, f'Problem {title}: rejudge completed; official results updated.', batch['actor_id'])
        accounts = conn.execute(sa.select(labs.enrollments.c.account_id).where(labs.enrollments.c.lab_id == lab_id)).scalars()
        for account in accounts:
            queue.notify(conn, account)
        queue.notify(conn)
