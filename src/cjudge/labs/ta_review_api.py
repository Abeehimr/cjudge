"""Admin controls for TA marks and claims."""
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import Field
import sqlalchemy as sa

from cjudge import identity, labs
from cjudge.identity.api import StrictModel, admin, admin_write, no_store
from cjudge.labs import ta_reviews
from cjudge.labs.api import ReasonInput, transaction
from cjudge.submissions import review

router = APIRouter(prefix='/api/admin/labs/{lab_id}/ta-reviews', dependencies=[Depends(admin), Depends(no_store)])


class AdminChange(ReasonInput):
    version: int = Field(ge=0)
    owner_id: UUID | None = None


def summary(conn: sa.Connection, lab_id: UUID) -> dict:
    automatic = review.marks(conn, lab_id)
    has_manual = bool(ta_reviews.enabled(conn, lab_id))
    result = []
    for student in automatic:
        manual = ta_reviews.detail(conn, lab_id, student['id'])
        auto_total = student['total']
        ta_total = manual['total']
        combined = f'{Decimal(auto_total) + Decimal(ta_total):.2f}' if auto_total is not None and ta_total is not None else None
        result.append({'id': student['id'], 'roll_number': student['roll_number'], 'name': student['name'],
            'cancelled': student['cancelled'], 'automatic_total': auto_total,
            'ta_total': ta_total, 'combined_total': combined, 'review': manual})
    return {'total': len([row for row in result if not row['cancelled']]) if has_manual else 0,
        'remaining': len([row for row in result if not row['cancelled'] and not row['review']['finalized']]) if has_manual else 0,
        'students': result}


@router.get('')
def list_reviews(lab_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        return summary(conn, lab_id)


@router.post('/{student_id}/release')
def release(lab_id: UUID, student_id: UUID, body: AdminChange, actor: dict = Depends(admin_write)):
    with transaction() as conn:
        lab = labs.find(conn, lab_id)
        return ta_reviews.release(conn, lab, student_id, body.version, actor['id'],
            admin=True, target=body.owner_id, reason=body.reason)


@router.post('/{student_id}/reopen')
def reopen(lab_id: UUID, student_id: UUID, body: AdminChange, actor: dict = Depends(admin_write)):
    with transaction() as conn:
        lab = labs.find(conn, lab_id)
        return ta_reviews.reopen(conn, lab, student_id, body.version, actor['id'],
            admin=True, reason=body.reason)


@router.post('/{student_id}/acknowledge')
def acknowledge(lab_id: UUID, student_id: UUID, body: AdminChange, actor: dict = Depends(admin_write)):
    with transaction() as conn:
        lab = labs.find(conn, lab_id)
        row = ta_reviews.prepare(conn, lab, student_id, body.version)
        if not row or not row['needs_recheck'] or not body.reason.strip():
            raise labs.LabError(409, 'Needs recheck and reason required')
        identity.audit(conn, 'ta_review_recheck_acknowledged_reason', actor['id'], student_id,
            detail={'lab_id': str(lab_id), 'reason': body.reason.strip()})
        return ta_reviews.change(conn, lab_id, student_id, actor['id'],
            'ta_review_recheck_acknowledged', needs_recheck=False)
