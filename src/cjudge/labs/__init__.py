"""Lab policy and persistence. All times and access decisions are server-authoritative."""
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from cjudge import identity, tasks, events

metadata = identity.metadata
labs = sa.Table('labs', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('title', sa.String(160)),
    sa.Column('version', sa.Integer()), sa.Column('strict_ip', sa.Boolean()),
    sa.Column('compiler_feedback', sa.String(8)),
    sa.Column('starts_at', sa.DateTime(timezone=True)), sa.Column('ends_at', sa.DateTime(timezone=True)),
    sa.Column('reveal_results', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('scoreboard_visible', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('archived_at', sa.DateTime(timezone=True)),
    sa.Column('first_released_at', sa.DateTime(timezone=True)), sa.Column('created_at', sa.DateTime(timezone=True)))
assignments = sa.Table('lab_tasks', metadata,
    sa.Column('lab_id', sa.Uuid(), primary_key=True), sa.Column('position', sa.Integer(), primary_key=True),
    sa.Column('revision_id', sa.Uuid()))
enrollments = sa.Table('lab_enrollments', metadata,
    sa.Column('lab_id', sa.Uuid(), primary_key=True), sa.Column('account_id', sa.Uuid(), primary_key=True),
    sa.Column('frozen', sa.Boolean()), sa.Column('freeze_reason', sa.String(500)),
    sa.Column('binding_hash', sa.String(64)), sa.Column('bound_ip', sa.String(45)),
    sa.Column('last_ip', sa.String(45)), sa.Column('ip_changed', sa.Boolean()),
    sa.Column('bound_at', sa.DateTime(timezone=True)))
pdfs = sa.Table('lab_pdfs', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('lab_id', sa.Uuid()), sa.Column('name', sa.String(160)),
    sa.Column('size', sa.Integer()), sa.Column('active', sa.Boolean()), sa.Column('replaces_id', sa.Uuid()),
    sa.Column('created_at', sa.DateTime(timezone=True)))
announcements = sa.Table('lab_announcements', metadata,
    sa.Column('id', sa.Uuid(), primary_key=True), sa.Column('lab_id', sa.Uuid()), sa.Column('author_id', sa.Uuid()),
    sa.Column('body', sa.String(4000)), sa.Column('recipient_id', sa.Uuid(), sa.ForeignKey('accounts.id')), sa.Column('created_at', sa.DateTime(timezone=True)))


class LabError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def now(conn: sa.Connection) -> datetime:
    return conn.execute(sa.select(sa.func.clock_timestamp())).scalar_one()


def phase(lab: dict, timestamp: datetime) -> str:
    if lab.get('archived_at'):
        return 'Archived'
    if lab.get('first_released_at'):
        return 'Results released'
    if lab['starts_at'] is None:
        return 'Draft'
    if timestamp < lab['starts_at']:
        return 'Scheduled'
    return 'Running' if timestamp < lab['ends_at'] else 'Ended'


def find(conn: sa.Connection, lab_id: UUID, version: int | None = None, *, shared: bool = False,
         lock: bool = True) -> dict:
    query = sa.select(labs).where(labs.c.id == lab_id)
    if lock:
        query = query.with_for_update(read=shared)
    row = conn.execute(query).mappings().first()
    if not row:
        raise LabError(404, 'Lab not found')
    if version is not None and version != row['version']:
        raise LabError(409, 'Lab changed; reload before editing')
    return dict(row)


def setup_open(lab: dict, timestamp: datetime) -> None:
    if lab['starts_at'] is not None and timestamp >= lab['starts_at']:
        raise LabError(409, 'Lab setup is fixed after start')


def notify(conn: sa.Connection, *, lab_id: UUID | None = None, account_id: UUID | None = None) -> None:
    events.publish(conn, lab_id=lab_id, account_id=account_id)


def scoreboard_notify(conn: sa.Connection, lab_id: UUID) -> None:
    if conn.execute(sa.select(labs.c.scoreboard_visible).where(labs.c.id == lab_id)).scalar_one():
        notify(conn, lab_id=lab_id)


def announce(conn: sa.Connection, lab_id: UUID, body: str, actor: UUID, recipient_id: UUID | None = None) -> None:
    if not body.strip() or len(body) > 4000:
        raise LabError(400, 'Announcement must contain 1–4000 characters')
    conn.execute(sa.insert(announcements).values(id=uuid4(), lab_id=lab_id, author_id=actor,
        body=body, recipient_id=recipient_id))
    identity.audit(conn, 'lab_announcement_posted', actor, recipient_id,
        detail={'lab_id': str(lab_id), 'recipient_id': str(recipient_id) if recipient_id else None})
    from cjudge.judging import queue
    queue.notify(conn, recipient_id)
    if recipient_id is None:
        notify(conn, lab_id=lab_id)


def editable(lab: dict) -> None:
    if lab.get('archived_at'):
        raise LabError(409, 'Archived lab is read-only')


def changed(conn: sa.Connection, lab: dict, actor: UUID, action: str, *, message: str | None = None, **values) -> dict:
    if action not in ('lab_results_revealed', 'lab_results_hidden'):
        editable(lab)
    conn.execute(sa.update(labs).where(labs.c.id == lab['id']).values(version=lab['version'] + 1, **values))
    identity.audit(conn, action, actor, detail={'lab_id': str(lab['id']), **{
        key: value.isoformat() if isinstance(value, datetime) else value for key, value in values.items()}})
    defaults = {
        'lab_edited': 'Lab settings updated.', 'lab_tasks_updated': 'Assigned problems updated.',
        'lab_scheduled': f"Lab schedule updated: {values.get('starts_at')} to {values.get('ends_at')}.",
        'lab_compiler_feedback': f"Compiler feedback policy changed to {values.get('compiler_feedback')}.",
    }
    message = message or defaults.get(action)
    if message:
        announce(conn, lab['id'], message, actor)
    notify(conn, lab_id=lab['id'])
    return find(conn, lab['id'])


def create(conn: sa.Connection, title: str, strict_ip: bool, actor: UUID) -> dict:
    lab_id = uuid4()
    conn.execute(sa.insert(labs).values(id=lab_id, title=title, strict_ip=strict_ip, version=1))
    identity.audit(conn, 'lab_created', actor, detail={'lab_id': str(lab_id)})
    return find(conn, lab_id)


def task_rows(conn: sa.Connection, lab_id: UUID) -> list[dict]:
    return [dict(row) for row in conn.execute(sa.select(assignments.c.position, tasks.revisions.c.id,
        tasks.revisions.c.task_id, tasks.revisions.c.number, tasks.revisions.c.config)
        .join(tasks.revisions, assignments.c.revision_id == tasks.revisions.c.id)
        .where(assignments.c.lab_id == lab_id).order_by(assignments.c.position)).mappings()]


def disclosure_lock(conn: sa.Connection) -> None:
    # Serialize scheduled test selection with release/correction disclosure checks.
    conn.execute(sa.select(sa.func.pg_advisory_xact_lock(51003)))


def set_tasks(conn: sa.Connection, lab: dict, ids: list[UUID], actor: UUID) -> dict:
    disclosure_lock(conn)
    setup_open(lab, now(conn))
    rows = conn.execute(sa.select(tasks.revisions.c.id, tasks.revisions.c.task_id)
                        .where(tasks.revisions.c.id.in_(ids))).all()
    if len(rows) != len(ids) or len({row.task_id for row in rows}) != len(ids):
        raise LabError(400, 'Select distinct published tasks; each revision must exist')
    if lab['starts_at'] is not None:
        if not ids:
            raise LabError(400, 'Scheduled lab needs at least one task')
        has_pdf = conn.execute(sa.select(pdfs.c.id).where(pdfs.c.lab_id == lab['id'], pdfs.c.active).limit(1)).first()
        configs = conn.execute(sa.select(tasks.revisions.c.config).where(tasks.revisions.c.id.in_(ids))).scalars()
        if not has_pdf and any(not config['statement'].strip() for config in configs):
            raise LabError(400, 'Scheduled lab needs a PDF or Markdown for every task')
    conn.execute(sa.delete(assignments).where(assignments.c.lab_id == lab['id']))
    if ids:
        conn.execute(sa.insert(assignments), [{'lab_id': lab['id'], 'position': pos, 'revision_id': key}
                                              for pos, key in enumerate(ids, 1)])
    return changed(conn, lab, actor, 'lab_tasks_updated')


def schedule(conn: sa.Connection, lab: dict, start: datetime | None, end: datetime, actor: UUID) -> dict:
    disclosure_lock(conn)
    timestamp = now(conn)
    setup_open(lab, timestamp)
    start = start or timestamp
    if start < timestamp or end <= start:
        raise LabError(400, 'Use a future start or Start now, and an end after start')
    assigned = task_rows(conn, lab['id'])
    if not assigned or not conn.execute(sa.select(enrollments.c.account_id).where(enrollments.c.lab_id == lab['id']).limit(1)).first():
        raise LabError(400, 'Add at least one published task and one student')
    has_pdf = conn.execute(sa.select(pdfs.c.id).where(pdfs.c.lab_id == lab['id'], pdfs.c.active).limit(1)).first()
    if not has_pdf and any(not row['config']['statement'].strip() for row in assigned):
        raise LabError(400, 'Add a lab PDF or provide Markdown for every assigned task')
    # The exclusion constraint arbitrates overlapping schedules, including races.
    return changed(conn, lab, actor, 'lab_scheduled', starts_at=start, ends_at=end)


def deadline(conn: sa.Connection, lab: dict, end: datetime, action: str, reason: str, actor: UUID) -> dict:
    timestamp = now(conn)
    state = phase(lab, timestamp)
    if lab['first_released_at'] is not None:
        raise LabError(409, 'Deadlines cannot change after first results release')
    if action == 'extend' and state != 'Running' or action == 'reopen' and state != 'Ended':
        raise LabError(409, 'Extend a running lab or reopen an ended lab')
    if end <= timestamp or end <= lab['ends_at']:
        raise LabError(400, 'New deadline must be later than now and the current deadline')
    identity.audit(conn, 'lab_deadline_reason', actor, detail={'lab_id': str(lab['id']), 'reason': reason})
    return changed(conn, lab, actor, 'lab_' + action, ends_at=end,
        message=f'Lab {"reopened" if action == "reopen" else "deadline extended"}. New deadline: {end.isoformat()}. Reason: {reason}')


def stop(conn: sa.Connection, lab: dict, reason: str, actor: UUID) -> dict:
    timestamp = now(conn)
    if phase(lab, timestamp) != 'Running' or lab['first_released_at']:
        raise LabError(409, 'Stop requires a running lab before release')
    if not reason.strip():
        raise LabError(400, 'Reason required')
    identity.audit(conn, 'lab_stop_reason', actor, detail={'lab_id': str(lab['id']),
        'reason': reason.strip(), 'previous_deadline': lab['ends_at'].isoformat()})
    return changed(conn, lab, actor, 'lab_stopped', ends_at=timestamp,
        message=f'Lab stopped. New submissions are closed; accepted work continues judging. Reason: {reason.strip()}')


def submission_allowed(lab: dict, enrollment: dict, timestamp: datetime) -> None:
    """M5 must call under the lab/enrollment locks before durable acceptance."""
    if phase(lab, timestamp) != 'Running':
        raise LabError(403, 'Lab is not running')
    if enrollment['frozen']:
        raise LabError(423, 'Submissions paused by administrator')


def overlap_error(exc: IntegrityError) -> LabError:
    if getattr(exc.orig, 'sqlstate', None) == '23P01':
        return LabError(409, 'Lab time overlaps another lab; reschedule the other lab first')
    raise exc


def enroll(conn: sa.Connection, lab: dict, ids: list[UUID], actor: UUID) -> dict:
    from sqlalchemy.dialects.postgresql import insert
    if len(ids) != len(set(ids)):
        raise LabError(400, 'Duplicate student selection')
    found = conn.execute(sa.select(identity.accounts.c.id).where(identity.accounts.c.id.in_(ids),
                                                               identity.accounts.c.role == 'student')).all()
    if len(found) != len(ids):
        raise LabError(404, 'Student not found')
    if ids:
        for key in ids:
            conn.execute(insert(enrollments).values(lab_id=lab['id'], account_id=key).on_conflict_do_nothing())
    return changed(conn, lab, actor, 'lab_students_added')


def import_roster(conn: sa.Connection, lab: dict, rows: list[tuple[str, str]], actor: UUID) -> dict:
    result = identity.import_student_rows(conn, rows)
    ids = list(conn.execute(sa.select(identity.accounts.c.id).where(
        identity.accounts.c.roll_number.in_([roll for roll, _ in rows]))).scalars())
    enroll(conn, lab, ids, actor)
    return result


def enrollment(conn: sa.Connection, lab_id: UUID, account_id: UUID, *, lock: bool = True) -> dict:
    query = sa.select(enrollments).where(enrollments.c.lab_id == lab_id, enrollments.c.account_id == account_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    if not row:
        raise LabError(403, 'Not enrolled in this lab')
    return dict(row)


def remove_student(conn: sa.Connection, lab: dict, account_id: UUID, actor: UUID) -> dict:
    setup_open(lab, now(conn))
    enrollment(conn, lab['id'], account_id)
    if lab['starts_at'] and conn.execute(sa.select(sa.func.count()).select_from(enrollments).where(
            enrollments.c.lab_id == lab['id'])).scalar_one() == 1:
        raise LabError(400, 'Scheduled lab needs at least one student')
    conn.execute(sa.delete(enrollments).where(enrollments.c.lab_id == lab['id'], enrollments.c.account_id == account_id))
    return changed(conn, lab, actor, 'lab_student_removed')


def freeze(conn: sa.Connection, lab: dict, account_id: UUID, frozen: bool, reason: str, actor: UUID) -> None:
    editable(lab)
    enrollment(conn, lab['id'], account_id)
    conn.execute(sa.update(enrollments).where(enrollments.c.lab_id == lab['id'], enrollments.c.account_id == account_id)
                 .values(frozen=frozen, freeze_reason=reason if frozen else None))
    identity.audit(conn, 'lab_student_frozen' if frozen else 'lab_student_unfrozen', actor, account_id,
                   detail={'lab_id': str(lab['id']), 'reason': reason})
    announce(conn, lab['id'], f'Submissions {"paused" if frozen else "resumed"}. Reason: {reason}', actor, account_id)
