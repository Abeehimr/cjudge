"""Final CSV sheets share official marks and exact rounding."""
import csv
from fractions import Fraction
import io
from uuid import UUID

from fastapi import Depends, Response
import sqlalchemy as sa

from cjudge import identity, labs
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
        (safe_cell(task['config']['title'] + ' marks'), safe_cell(task['config']['title'] + ' pass %'))],
        'Total marks', 'Active submissions', 'Last active submission (UTC)'])
    for student in marks:
        cells = []
        for cell in student['tasks']:
            percentage = review.displayed(Fraction(100 * cell['passed'], cell['total'])) if cell['total'] else '0.00'
            cells.extend(['', ''] if student['cancelled'] else [cell['marks'], percentage])
        timestamp = latest.get(student['id'])
        writer.writerow([safe_cell(student['roll_number']), safe_cell(student['name']),
            'Cancelled' if student['cancelled'] else 'Active', *cells,
            student['total'] or '', student['submission_count'], timestamp.isoformat() if timestamp else ''])
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
