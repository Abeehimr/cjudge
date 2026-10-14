"""Persist accepted source language without rewriting immutable evidence."""
from alembic import op

revision = '20261014_cpp17'
down_revision = '20261014_source_restrictions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('submissions', 'tester_sources'):
        # Fresh historical migrations may create tables from current Core metadata.
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'c11'")
        op.create_check_constraint(f'{table}_language', table, "language IN ('c11', 'cpp17')")


def downgrade() -> None:
    for table in ('tester_sources', 'submissions'):
        op.drop_column(table, 'language')
