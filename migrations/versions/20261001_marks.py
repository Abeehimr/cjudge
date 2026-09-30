"""Official results, review state and correction batches."""
from alembic import op
import sqlalchemy as sa

revision = '20261001_marks'
down_revision = '20260930_submissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing M5 installations skip its import side effects during this upgrade.
    from cjudge import labs, tasks
    from cjudge.submissions import reviews, batches, members
    op.add_column('judge_jobs', sa.Column('kind', sa.String(16), nullable=False, server_default='initial'))
    op.add_column('judge_jobs', sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id')))
    op.add_column('judge_jobs', sa.Column('batch_id', sa.Uuid()))
    op.create_check_constraint('job_kind', 'judge_jobs', "kind IN ('initial', 'rejudge', 'correction')")
    for table in (reviews, batches, members):
        table.create(op.get_bind())
    op.create_foreign_key('job_batch', 'judge_jobs', 'correction_batches', ['batch_id'], ['id'])
    op.execute('INSERT INTO submission_reviews (submission_id, run_id) SELECT s.id, r.id FROM submissions s LEFT JOIN judge_jobs j ON j.submission_id=s.id LEFT JOIN judge_runs r ON r.id=j.attempt_id')
    op.execute('UPDATE judge_jobs j SET revision_id=s.revision_id FROM submissions s WHERE s.id=j.submission_id')


def downgrade() -> None:
    op.drop_constraint('job_batch', 'judge_jobs', type_='foreignkey')
    for name in ('correction_members', 'correction_batches', 'submission_reviews'):
        op.drop_table(name)
    op.drop_constraint('job_kind', 'judge_jobs')
    for name in ('batch_id', 'revision_id', 'kind'):
        op.drop_column('judge_jobs', name)
