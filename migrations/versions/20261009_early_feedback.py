"""Optional early submission counts."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_early_feedback'
down_revision = '20261008_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('labs', sa.Column('early_feedback_visible', sa.Boolean(), nullable=False,
                                    server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('labs', 'early_feedback_visible')
