"""Retain matched teaching-rule identifiers in judge and tester results."""
from alembic import op
import sqlalchemy as sa

revision = '20261014_source_restrictions'
down_revision = '20261013_ta_reviews'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh M5 migrations create this table from current Core metadata.
    op.execute('ALTER TABLE judge_runs ADD COLUMN IF NOT EXISTS restriction JSON')
    op.add_column('tester_sources', sa.Column('restriction', sa.JSON()))


def downgrade() -> None:
    op.drop_column('tester_sources', 'restriction')
    op.drop_column('judge_runs', 'restriction')
