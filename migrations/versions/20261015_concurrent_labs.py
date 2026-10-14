"""Allow concurrent labs and enforce enrollment reservations in application transactions."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_concurrent_labs'
down_revision = '20261014_cpp17'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    duplicate = conn.execute(sa.text("""
        SELECT e.account_id, count(*) AS labs
        FROM lab_enrollments AS e JOIN labs AS l ON l.id = e.lab_id
        WHERE l.first_released_at IS NULL
        GROUP BY e.account_id HAVING count(*) > 1 LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError(f'Cannot enable concurrent labs: student {duplicate.account_id} has '
                           f'{duplicate.labs} unreleased lab enrollments')
    op.execute('ALTER TABLE labs DROP CONSTRAINT no_lab_overlap')


def downgrade() -> None:
    op.execute("ALTER TABLE labs ADD CONSTRAINT no_lab_overlap EXCLUDE USING gist "
               "(tstzrange(starts_at, ends_at, '[)') WITH &&) WHERE (starts_at IS NOT NULL)")
