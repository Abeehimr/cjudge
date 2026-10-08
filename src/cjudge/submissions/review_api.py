"""Admin-only marks and audited grading mutations."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
import sqlalchemy as sa
from starlette.concurrency import run_in_threadpool

from cjudge import labs
from cjudge.identity.api import admin, admin_write, no_store, StrictModel
from cjudge.labs.api import ReasonInput
from cjudge.submissions import review, reviews, batches, members, jobs, submissions
from cjudge.submissions.api import transaction
from cjudge.tasks.api import json_input

router = APIRouter(prefix='/api/admin/labs/{lab_id}', dependencies=[Depends(admin), Depends(no_store)])


class ReviewInput(ReasonInput):
    deleted: bool


class RejudgeInput(ReasonInput):
    expected_run_id: UUID | None


class CorrectionInput(ReasonInput):
    acknowledge_reuse: bool = False
    revision_id: UUID
    version: int


def reason(body: ReasonInput) -> str:
    if not body.reason.strip():
        raise HTTPException(400, 'Reason required')
    return body.reason.strip()


@router.get('/marks')
def marks(lab_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        return review.marks(conn, lab_id)


@router.put('/submissions/{submission_id}/review', status_code=204)
async def set_review(lab_id: UUID, submission_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, ReviewInput)
    why = reason(body)
    def perform():
        with transaction() as conn:
            lab = labs.find(conn, lab_id)
            review.set_deleted(conn, lab, submission_id, body.deleted, actor['id'], why)
            review.publish_ready(conn, lab_id)
    await run_in_threadpool(perform)


@router.post('/submissions/{submission_id}/rejudge', status_code=204)
async def rejudge(lab_id: UUID, submission_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, RejudgeInput)
    why = reason(body)
    def perform():
        with transaction() as conn:
            lab = labs.find(conn, lab_id)
            review.find_submission(conn, lab_id, submission_id)
            current = conn.execute(sa.select(reviews.c.run_id).where(reviews.c.submission_id == submission_id)).scalar_one_or_none()
            if current != body.expected_run_id:
                raise labs.LabError(409, 'Official result changed; refresh before rejudging')
            review.rejudge(conn, lab, submission_id, actor['id'], why)
    await run_in_threadpool(perform)


@router.post('/tasks/{task_id}/corrections', status_code=201)
async def correction(lab_id: UUID, task_id: UUID, request: Request, actor: dict = Depends(admin_write)):
    body = await json_input(request, CorrectionInput)
    why = reason(body)
    def perform():
        with transaction() as conn:
            lab = labs.find(conn, lab_id, body.version)
            key = review.correct(conn, lab, task_id, body.revision_id, actor['id'], why, body.acknowledge_reuse)
            review.publish_ready(conn, lab_id)
            return {'id': key}
    return await run_in_threadpool(perform)


@router.get('/corrections')
def corrections(lab_id: UUID):
    with transaction() as conn:
        labs.find(conn, lab_id, shared=True)
        result = []
        for batch in conn.execute(sa.select(batches).where(batches.c.lab_id == lab_id)
                .order_by(batches.c.created_at.desc())).mappings():
            rows = conn.execute(sa.select(members.c.run_id, reviews.c.deleted_at, jobs.c.state,
                labs.enrollments.c.cancelled)
                .join(reviews, reviews.c.submission_id == members.c.submission_id)
                .join(jobs, jobs.c.submission_id == members.c.submission_id)
                .join(submissions, submissions.c.id == members.c.submission_id)
                .join(labs.enrollments, sa.and_(labs.enrollments.c.lab_id == lab_id,
                    labs.enrollments.c.account_id == submissions.c.account_id))
                .where(members.c.batch_id == batch['id'])).mappings().all()
            active = [row for row in rows if row['deleted_at'] is None and not row['cancelled']]
            result.append(dict(batch, total=len(active), completed=sum(row['run_id'] is not None for row in active),
                delayed=sum(row['run_id'] is None and row['state'] == 'delayed' for row in active)))
        return result
