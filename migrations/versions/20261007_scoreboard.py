"""Optional participant scoreboard visibility."""
from alembic import op
import sqlalchemy as sa

revision = '20261007_scoreboard'
down_revision = '20261006_notices'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('labs', sa.Column('scoreboard_visible', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('labs', 'scoreboard_visible')
