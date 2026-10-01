"""Live standings from official results; sources and test data never enter this contract."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from cjudge import identity, labs
from cjudge.identity.api import admin, admin_write, no_store
from cjudge.labs.api import student, student_access, transaction, VersionInput
from cjudge.submissions import batches, reviews
from cjudge.submissions.review import counted_submission, displayed, exact, official_query
from cjudge.tasks.api import json_input

router = APIRouter(dependencies=[Depends(no_store)])


def standings(assigned: list[dict], students: list[dict], rows: list[dict], active: set[UUID],
              start: datetime | None, account_id: UUID | None = None) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        if row['deleted_at'] is None:
            grouped[row['account_id'], row['task_id']].append(row)
    result, first = [], {}
    for student in students:
        cells, total_cents, elapsed = [], 0, 0
        for task in assigned:
            attempts = grouped[student['id'], task['task_id']]
            best = counted_submission(attempts)
            pending = bool(attempts) and task['task_id'] in active or any(
                row['state'] != 'complete' or row['run_id'] is None for row in attempts)
            delayed = any(row['state'] == 'delayed' for row in attempts)
            marks = displayed(exact(best)) if best else None
            duration = best['accepted_at'] - start if best and start else None
            time_us = ((duration.days * 86400 + duration.seconds) * 1_000_000 + duration.microseconds) if duration else 0
            total_cents += int(Decimal(marks or '0') * 100)
            if best and exact(best) > 0:
                elapsed += time_us
            solved = best is not None and exact(best) == Fraction(str(task['config']['maximum_marks']))
            state = 'solved' if solved else 'partial' if best and exact(best) > 0 else 'zero' if best else 'empty'
            cell = dict(task_id=task['task_id'], marks=marks, elapsed_us=time_us if best else None,
                submission_id=best['id'] if best and (account_id is None or student['id'] == account_id) else None,
                state='judging' if pending else state, pending=bool(pending), delayed=delayed, first_solve=False)
            cells.append(cell)
            if solved:
                priority = (best['accepted_at'], str(best['id']))
                previous = first.get(task['task_id'])
                if previous is None or priority < previous[0]:
                    first[task['task_id']] = (priority, cell)
        result.append(dict(roll_number=student['roll_number'], name=student['name'], tasks=cells,
            total=f'{total_cents // 100}.{total_cents % 100:02d}', elapsed_us=elapsed,
            pending=any(cell['pending'] for cell in cells)))
    for _, cell in first.values():
        cell['first_solve'] = True
        if not cell['pending']:
            cell['state'] = 'first_solve'
    result.sort(key=lambda row: (-Decimal(row['total']), row['elapsed_us'], row['roll_number']))
    previous, rank = None, 0
    for index, row in enumerate(result, 1):
        priority = (row['total'], row['elapsed_us'])
        if priority != previous:
            rank = index
        row['rank'], previous = rank, priority
    return dict(tasks=[dict(task_id=task['task_id'], title=task['config']['title'],
        maximum_marks=str(task['config']['maximum_marks'])) for task in assigned], students=result)


def snapshot(conn: sa.Connection, lab: dict, account_id: UUID | None = None) -> dict:
    assigned = labs.task_rows(conn, lab['id'])
    students = list(conn.execute(sa.select(identity.accounts.c.id, identity.accounts.c.roll_number,
        identity.accounts.c.name).join(labs.enrollments, labs.enrollments.c.account_id == identity.accounts.c.id)
        .where(labs.enrollments.c.lab_id == lab['id'])).mappings())
    rows = list(conn.execute(official_query(lab['id']).where(reviews.c.deleted_at.is_(None))).mappings())
    active = set(conn.execute(sa.select(batches.c.task_id).where(
        batches.c.lab_id == lab['id'], batches.c.state == 'judging')).scalars())
    return standings(assigned, students, rows, active, lab['starts_at'], account_id)


@router.get('/api/admin/labs/{lab_id}/scoreboard', dependencies=[Depends(admin)])
def admin_scoreboard(lab_id: UUID):
    with transaction() as conn:
        conn.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        return snapshot(conn, labs.find(conn, lab_id, lock=False))


@router.get('/api/labs/{lab_id}/scoreboard')
def student_scoreboard(lab_id: UUID, request: Request, account: dict = Depends(student)):
    with transaction() as conn:
        # Binding policy may record a permitted IP change during authorization.
        conn.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        lab, _, _ = student_access(conn, lab_id, account, request, readonly=True)
        if not lab['scoreboard_visible']:
            raise labs.LabError(403, 'Scoreboard is visible only to admin')
        return snapshot(conn, lab, account['id'])


class VisibilityInput(VersionInput):
    visible: bool


@router.put('/api/admin/labs/{lab_id}/scoreboard/visibility', dependencies=[Depends(admin)])
async def visibility(lab_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, VisibilityInput)
    def change():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            labs.editable(lab)
            labs.changed(conn, lab, actor['id'], 'lab_scoreboard_visibility',
                message=f'Scoreboard {"enabled for participants" if body.visible else "hidden from participants"}.',
                scoreboard_visible=body.visible)
    await run_in_threadpool(change)
