"""Durable submissions, leased judging and sandbox worker status."""
from alembic import op
import sqlalchemy as sa

revision = '20260930_submissions'
down_revision = '20260930_labs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Shared declarations keep the queue schema and Core interfaces identical.
    from cjudge import labs, tasks
    from cjudge.submissions import TABLES
    for table in TABLES:
        if table.name == 'judge_jobs':
            # Keep the original queue schema independent of later declarations.
            op.create_table('judge_jobs',
                sa.Column('submission_id', sa.Uuid(), sa.ForeignKey('submissions.id'), primary_key=True),
                sa.Column('state', sa.String(16), nullable=False, server_default='queued'),
                sa.Column('attempt_id', sa.Uuid()),
                sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
                sa.Column('retry_until', sa.Integer(), nullable=False, server_default='3'),
                sa.Column('ready_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
                sa.CheckConstraint("state IN ('queued', 'judging', 'delayed', 'complete')"))
            op.create_index('jobs_ready', 'judge_jobs', ['state', 'ready_at'])
        else:
            table.create(op.get_bind())
    op.add_column('labs', sa.Column('compiler_feedback', sa.String(8), nullable=False, server_default='short'))
    op.create_check_constraint('lab_compiler_feedback', 'labs', "compiler_feedback IN ('short', 'full', 'none')")
    op.execute("""CREATE FUNCTION reject_submission_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Accepted submission evidence is immutable'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_submission BEFORE UPDATE OR DELETE ON submissions
        FOR EACH ROW EXECUTE FUNCTION reject_submission_change()""")


def downgrade() -> None:
    from cjudge.submissions import TABLES
    for table in reversed(TABLES):
        table.drop(op.get_bind())
    op.execute('DROP FUNCTION reject_submission_change()')
    op.drop_constraint('lab_compiler_feedback', 'labs')
    op.drop_column('labs', 'compiler_feedback')
