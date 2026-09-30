"""Durable sandbox generation jobs and case provenance."""
from alembic import op

revision = '20261002_authoring'
down_revision = '20261001_marks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from cjudge import tasks
    from cjudge.authoring import jobs, attempts, cases
    for table in (jobs, attempts, cases):
        table.create(op.get_bind())


def downgrade() -> None:
    for name in ('authoring_cases', 'authoring_attempts', 'authoring_jobs'):
        op.drop_table(name)
