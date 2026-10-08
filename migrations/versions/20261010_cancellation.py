"""Reversible lab cancellation."""
from alembic import op
import sqlalchemy as sa

revision = '20261010_cancellation'
down_revision = '20261009_early_feedback'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lab_enrollments', sa.Column('cancelled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('lab_enrollments', sa.Column('cancel_reason', sa.String(500)))


def downgrade() -> None:
    op.drop_column('lab_enrollments', 'cancel_reason')
    op.drop_column('lab_enrollments', 'cancelled')
