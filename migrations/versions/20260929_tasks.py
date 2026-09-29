"""Task drafts and immutable published revisions."""

from alembic import op
import sqlalchemy as sa

revision = '20260929_tasks'
down_revision = '20260929_identity'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tasks',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('cases_key', sa.Uuid()),
        sa.Column('case_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('task_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('draft_version', sa.Integer(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('cases_key', sa.Uuid(), nullable=False),
        sa.Column('case_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('task_id', 'number'),
        sa.UniqueConstraint('task_id', 'draft_version'))
    op.execute("""CREATE FUNCTION reject_task_revision_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Published task revisions are immutable'; END; $$""")
    op.execute("""CREATE TRIGGER immutable_task_revision BEFORE UPDATE OR DELETE ON task_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_task_revision_change()""")


def downgrade() -> None:
    op.drop_table('task_revisions')
    op.execute('DROP FUNCTION reject_task_revision_change()')
    op.drop_table('tasks')
