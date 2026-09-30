"""Private recipients for transactional lab announcements."""
from alembic import op
import sqlalchemy as sa

revision = '20261006_notices'
down_revision = '20261005_delete'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lab_announcements', sa.Column('recipient_id', sa.Uuid(), sa.ForeignKey('accounts.id')))
    op.create_index('announcements_recipient', 'lab_announcements', ['lab_id', 'recipient_id'])


def downgrade() -> None:
    # Never turn private messages public on downgrade.
    op.execute('DELETE FROM lab_announcements WHERE recipient_id IS NOT NULL')
    op.drop_index('announcements_recipient', table_name='lab_announcements')
    op.drop_column('lab_announcements', 'recipient_id')
