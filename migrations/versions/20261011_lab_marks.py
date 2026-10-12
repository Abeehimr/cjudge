"""Store automatic maximum marks on lab assignments."""
from alembic import op
import sqlalchemy as sa

revision = '20261011_lab_marks'
down_revision = '20261010_cancellation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lab_tasks', sa.Column('maximum_marks', sa.Numeric(7, 2)))
    op.execute("""UPDATE lab_tasks AS assignment SET maximum_marks =
        COALESCE(revision.config->>'maximum_marks', '100')::numeric
        FROM task_revisions AS revision WHERE revision.id = assignment.revision_id""")
    op.alter_column('lab_tasks', 'maximum_marks', nullable=False)
    op.create_check_constraint('lab_task_maximum_valid', 'lab_tasks', 'maximum_marks > 0 AND maximum_marks <= 10000')
    op.add_column('labs', sa.Column('legacy_archived_marks', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute('UPDATE labs SET legacy_archived_marks = true WHERE archived_at IS NOT NULL')
    op.execute("ALTER TABLE lab_exports ADD COLUMN IF NOT EXISTS format_version smallint NOT NULL DEFAULT 1")


def downgrade() -> None:
    op.execute('ALTER TABLE lab_exports DROP COLUMN IF EXISTS format_version')
    op.drop_column('labs', 'legacy_archived_marks')
    op.drop_constraint('lab_task_maximum_valid', 'lab_tasks')
    op.drop_column('lab_tasks', 'maximum_marks')
