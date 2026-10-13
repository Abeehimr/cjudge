"""Manual TA marks, serialized under the lab row lock."""
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from cjudge import identity, labs
from cjudge.submissions.review import displayed

reviews = sa.Table('ta_reviews', identity.metadata,
    sa.Column('lab_id', sa.Uuid(), primary_key=True), sa.Column('student_id', sa.Uuid(), primary_key=True),
    sa.Column('owner_id', sa.Uuid()), sa.Column('reviewer_id', sa.Uuid()),
    sa.Column('version', sa.Integer(), nullable=False), sa.Column('finalized_at', sa.DateTime(timezone=True)),
    sa.Column('needs_recheck', sa.Boolean(), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True)))
marks = sa.Table('ta_review_marks', identity.metadata,
    sa.Column('lab_id', sa.Uuid(), primary_key=True), sa.Column('student_id', sa.Uuid(), primary_key=True),
    sa.Column('task_id', sa.Uuid(), primary_key=True), sa.Column('earned_numerator', sa.BigInteger()),
    sa.Column('earned_denominator', sa.BigInteger()), sa.Column('done', sa.Boolean()))


def enabled(conn: sa.Connection, lab_id: UUID) -> list[dict]:
    return [task for task in labs.task_rows(conn, lab_id) if task['ta_maximum'] > 0]


def current(conn: sa.Connection, lab_id: UUID, student_id: UUID) -> dict | None:
    row = conn.execute(sa.select(reviews).where(reviews.c.lab_id == lab_id,
        reviews.c.student_id == student_id)).mappings().first()
    return dict(row) if row else None


def detail(conn: sa.Connection, lab_id: UUID, student_id: UUID) -> dict:
    enrollment = labs.enrollment(conn, lab_id, student_id, lock=False)
    row = current(conn, lab_id, student_id)
    saved = {r['task_id']: r for r in conn.execute(sa.select(marks).where(
        marks.c.lab_id == lab_id, marks.c.student_id == student_id)).mappings()}
    cells, total = [], 0
    for task in enabled(conn, lab_id):
        item = saved.get(task['task_id'])
        value = displayed(Fraction(item['earned_numerator'], item['earned_denominator']) *
            Fraction(task['ta_maximum'])) if item else None
        if value is not None:
            total += int(Decimal(value) * 100)
        cells.append({'task_id': task['task_id'], 'title': task['config']['title'],
            'maximum': f"{task['ta_maximum']:.2f}", 'marks': value, 'done': bool(item and item['done'])})
    owner = conn.execute(sa.select(identity.accounts.c.name).where(
        identity.accounts.c.id == row['owner_id'])).scalar_one_or_none() if row and row['owner_id'] else None
    reviewer = conn.execute(sa.select(identity.accounts.c.name).where(
        identity.accounts.c.id == row['reviewer_id'])).scalar_one_or_none() if row and row['reviewer_id'] else None
    return {'student_id': student_id, 'cancelled': enrollment['cancelled'],
        'owner_id': row['owner_id'] if row else None, 'owner_name': owner,
        'reviewer_name': reviewer, 'version': row['version'] if row else 0,
        'finalized': bool(row and row['finalized_at']),
        'needs_recheck': bool(row and row['needs_recheck']),
        'tasks': cells, 'total': None if enrollment['cancelled'] else f'{total // 100}.{total % 100:02d}',
        'provisional': bool(cells and not row or row and not row['finalized_at'])}


def prepare(conn: sa.Connection, lab: dict, student_id: UUID, version: int, actor: UUID | None = None) -> dict | None:
    labs.editable(lab)
    if not lab['first_released_at']:
        raise labs.LabError(409, 'TA marking starts after first release')
    if not enabled(conn, lab['id']):
        raise labs.LabError(409, 'No TA marks enabled')
    enrollment = labs.enrollment(conn, lab['id'], student_id)
    if enrollment['cancelled']:
        raise labs.LabError(409, 'Cancelled student cannot be reviewed')
    row = current(conn, lab['id'], student_id)
    if version != (row['version'] if row else 0):
        raise labs.LabError(409, 'TA review changed; reload')
    if actor is not None and (not row or row['owner_id'] != actor):
        raise labs.LabError(403, 'Claim this student before marking')
    return row


def change(conn: sa.Connection, lab_id: UUID, student_id: UUID, actor: UUID,
           action: str, **values) -> dict:
    conn.execute(sa.update(reviews).where(reviews.c.lab_id == lab_id,
        reviews.c.student_id == student_id).values(version=reviews.c.version + 1,
        updated_at=labs.now(conn), **values))
    identity.audit(conn, action, actor, student_id, detail={'lab_id': str(lab_id), **{
        key: str(value) for key, value in values.items() if key in ('owner_id', 'reviewer_id')}})
    labs.ta_notify(conn, lab_id)
    labs.notify(conn)
    return detail(conn, lab_id, student_id)


def claim(conn: sa.Connection, lab: dict, student_id: UUID, version: int, actor: UUID) -> dict:
    row = prepare(conn, lab, student_id, version)
    if row and (row['owner_id'] or row['finalized_at']):
        raise labs.LabError(409, 'Review already claimed or finalized')
    if row is None:
        conn.execute(sa.insert(reviews).values(lab_id=lab['id'], student_id=student_id,
            owner_id=actor, version=0, needs_recheck=False))
    return change(conn, lab['id'], student_id, actor, 'ta_review_claimed', owner_id=actor)


def save(conn: sa.Connection, lab: dict, student_id: UUID, task_id: UUID,
         version: int, actor: UUID, value: Decimal, done: bool) -> dict:
    row = prepare(conn, lab, student_id, version, actor)
    if row['finalized_at']:
        raise labs.LabError(409, 'Reopen finalized review before editing')
    task = next((task for task in enabled(conn, lab['id']) if task['task_id'] == task_id), None)
    if task is None or not value.is_finite() or value < 0 or value > task['ta_maximum']:
        raise labs.LabError(400, 'Marks must fit enabled TA maximum')
    earned = Fraction(value) / Fraction(task['ta_maximum'])
    conn.execute(insert(marks).values(lab_id=lab['id'], student_id=student_id,
        task_id=task_id, earned_numerator=earned.numerator, earned_denominator=earned.denominator,
        done=done).on_conflict_do_update(index_elements=['lab_id', 'student_id', 'task_id'],
        set_={'earned_numerator': earned.numerator, 'earned_denominator': earned.denominator, 'done': done}))
    return change(conn, lab['id'], student_id, actor, 'ta_review_marks_saved')


def finalize(conn: sa.Connection, lab: dict, student_id: UUID, version: int, actor: UUID) -> dict:
    row = prepare(conn, lab, student_id, version, actor)
    if row['finalized_at']:
        raise labs.LabError(409, 'Review already finalized')
    saved = set(conn.execute(sa.select(marks.c.task_id).where(marks.c.lab_id == lab['id'],
        marks.c.student_id == student_id, marks.c.done)).scalars())
    if any(task['task_id'] not in saved for task in enabled(conn, lab['id'])):
        raise labs.LabError(409, 'Mark every enabled task Done before finalizing')
    return change(conn, lab['id'], student_id, actor, 'ta_review_finalized',
        finalized_at=labs.now(conn), reviewer_id=actor, needs_recheck=False)


def release(conn: sa.Connection, lab: dict, student_id: UUID, version: int, actor: UUID,
            admin: bool = False, target: UUID | None = None, reason: str = '') -> dict:
    row = prepare(conn, lab, student_id, version)
    if not row or row['finalized_at'] or row['owner_id'] is None:
        raise labs.LabError(409, 'No unfinished claim')
    if not admin and row['owner_id'] != actor:
        raise labs.LabError(403, 'Only claim owner can release review')
    if admin and not reason.strip():
        raise labs.LabError(400, 'Reason required')
    if target is not None:
        assigned = conn.execute(sa.select(identity.accounts.c.id).join(labs.ta_assignments,
            labs.ta_assignments.c.ta_id == identity.accounts.c.id).where(
            labs.ta_assignments.c.lab_id == lab['id'], identity.accounts.c.id == target,
            identity.accounts.c.active, identity.accounts.c.role == 'ta')).first()
        if not admin or not assigned:
            raise labs.LabError(400, 'Transfer requires active assigned TA')
    identity.audit(conn, 'ta_review_claim_changed_reason', actor, student_id,
        detail={'lab_id': str(lab['id']), 'reason': reason, 'previous_owner': str(row['owner_id'])})
    return change(conn, lab['id'], student_id, actor, 'ta_review_transferred' if target else 'ta_review_released',
        owner_id=target)


def reopen(conn: sa.Connection, lab: dict, student_id: UUID, version: int, actor: UUID,
           admin: bool = False, reason: str = '') -> dict:
    row = prepare(conn, lab, student_id, version)
    if not row or not row['finalized_at']:
        raise labs.LabError(409, 'Review is not finalized')
    if not admin and row['reviewer_id'] != actor:
        raise labs.LabError(403, 'Only original reviewer can reopen')
    if admin and not reason.strip():
        raise labs.LabError(400, 'Reason required')
    identity.audit(conn, 'ta_review_reopen_reason', actor, student_id,
        detail={'lab_id': str(lab['id']), 'reason': reason})
    owner = conn.execute(sa.select(labs.ta_assignments.c.ta_id).join(identity.accounts,
        identity.accounts.c.id == labs.ta_assignments.c.ta_id).where(
        labs.ta_assignments.c.lab_id == lab['id'], labs.ta_assignments.c.ta_id == row['reviewer_id'],
        identity.accounts.c.active)).scalar_one_or_none()
    return change(conn, lab['id'], student_id, actor, 'ta_review_reopened',
        finalized_at=None, owner_id=owner)


def flag(conn: sa.Connection, lab_id: UUID, student_id: UUID | None = None,
         task_id: UUID | None = None) -> None:
    condition = [reviews.c.lab_id == lab_id]
    if student_id is not None:
        condition.append(reviews.c.student_id == student_id)
    evidence = [marks.c.lab_id == reviews.c.lab_id, marks.c.student_id == reviews.c.student_id]
    if task_id is not None:
        evidence.append(marks.c.task_id == task_id)
    conn.execute(sa.update(reviews).where(*condition, sa.exists(sa.select(marks.c.task_id).where(*evidence)))
        .values(needs_recheck=True, version=reviews.c.version + 1))
    labs.ta_notify(conn, lab_id)
