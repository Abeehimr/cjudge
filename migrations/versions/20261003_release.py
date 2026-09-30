"""Release visibility and explicit lab archiving."""
from alembic import op
import sqlalchemy as sa

revision = '20261003_release'
down_revision = '20261002_authoring'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('labs', sa.Column('reveal_results', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('labs', sa.Column('archived_at', sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column('labs', 'archived_at')
    op.drop_column('labs', 'reveal_results')
