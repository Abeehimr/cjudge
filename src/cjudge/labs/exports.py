"""Final CSV sheets share official marks and exact rounding."""
import csv
from fractions import Fraction
import io
from uuid import UUID

from fastapi import Depends, Response
import sqlalchemy as sa

from cjudge import identity, labs
from cjudge.labs import ta_reviews
from decimal import Decimal
from cjudge.identity.api import admin
from cjudge.labs.api import admin_router
from cjudge.labs.release import resolved
from cjudge.submissions import submissions, reviews, review
from cjudge.submissions.api import transaction


def safe_cell(value: str) -> str:
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def final(conn: sa.Connection, lab: dict) -> None:
    if labs.phase(lab, labs.now(conn)) not in ('Ended', 'Results released', 'Archived'):
        raise labs.LabError(409, 'Final export requires an ended lab')
    resolved(conn, lab['id'])


def sheet(conn: sa.Connection, lab: dict) -> bytes:
    marks = review.marks(conn, lab['id'])
    assigned = labs.task_rows(conn, lab['id'])
    latest = dict(conn.execute(sa.select(submissions.c.account_id, sa.func.max(submissions.c.accepted_at))
        .outerjoin(reviews, reviews.c.submission_id == submissions.c.id).where(submissions.c.lab_id == lab['id'],
        reviews.c.deleted_at.is_(None)).group_by(submissions.c.account_id)).all())
    buffer = io.StringIO(newline=''); writer = csv.writer(buffer)
    writer.writerow(['Roll number', 'Name', 'Status', *[heading for task in assigned for heading in
        (safe_cell(task['config']['title'] + ' automatic marks'), safe_cell(task['config']['title'] + ' pass %'),
         safe_cell(task['config']['title'] + ' TA marks'), safe_cell(task['config']['title'] + ' combined marks'))],
        'Automatic total', 'TA total', 'Combined total', 'TA review status', 'TA reviewer',
        'Active submissions', 'Last active submission (UTC)'])
    for student in marks:
        manual = ta_reviews.detail(conn, lab['id'], student['id'])
        by_task = {task['task_id']: task for task in manual['tasks']}
        cells = []
        for cell in student['tasks']:
            percentage = review.displayed(Fraction(100 * cell['passed'], cell['total'])) if cell['total'] else '0.00'
            manual_mark = by_task.get(cell['task_id'], {}).get('marks')
            combined = f"{Decimal(cell['marks']) + Decimal(manual_mark or '0'):.2f}" if cell['marks'] is not None else ''
            cells.extend(['', '', '', ''] if student['cancelled'] else
                [cell['marks'], percentage, manual_mark or '', combined])
        timestamp = latest.get(student['id'])
        combined_total = f"{Decimal(student['total']) + Decimal(manual['total']):.2f}" if student['total'] is not None and manual['total'] is not None else ''
        status = 'Cancelled' if student['cancelled'] else 'Needs recheck' if manual['needs_recheck'] else (
            'Finalized' if manual['finalized'] else 'Provisional' if manual['owner_id'] else 'Unclaimed')
        writer.writerow([safe_cell(student['roll_number']), safe_cell(student['name']),
            'Cancelled' if student['cancelled'] else 'Active', *cells,
            student['total'] or '', manual['total'] or '', combined_total, status,
            safe_cell(manual['reviewer_name'] or manual['owner_name'] or ''),
            student['submission_count'], timestamp.isoformat() if timestamp else ''])
    return buffer.getvalue().encode('utf-8-sig')


@admin_router.get('/{lab_id}/marks.csv')
def marks_csv(lab_id: UUID, actor: dict = Depends(admin)):
    with transaction() as conn:
        lab = labs.find(conn, lab_id, shared=True)
        final(conn, lab)
        data = sheet(conn, lab)
        identity.audit(conn, 'lab_marks_exported', actor['id'], detail={'lab_id': str(lab_id), 'format': 'csv'})
    return Response(data, media_type='text/csv', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': f'attachment; filename="{lab_id}-marks.csv"'})
