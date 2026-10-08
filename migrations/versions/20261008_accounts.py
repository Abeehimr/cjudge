"""Student account activity."""
from alembic import op
import sqlalchemy as sa

revision = '20261008_accounts'
down_revision = '20261007_scoreboard'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('accounts', 'active')
