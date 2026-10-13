"""Assigned TAs and ownership of lab penalties."""
from alembic import op
import sqlalchemy as sa

revision = '20261013_ta_labs'
down_revision = '20261013_ta_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('lab_tas',
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('ta_id', sa.Uuid(), sa.ForeignKey('accounts.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('lab_tas_by_ta', 'lab_tas', ['ta_id'])
    op.add_column('lab_enrollments', sa.Column('frozen_by', sa.Uuid(), sa.ForeignKey('accounts.id')))
    op.add_column('lab_enrollments', sa.Column('cancelled_by', sa.Uuid(), sa.ForeignKey('accounts.id')))
    op.execute("""UPDATE lab_enrollments SET frozen_by = (SELECT id FROM accounts WHERE role = 'admin')
                  WHERE frozen = true""")
    op.execute("""UPDATE lab_enrollments SET cancelled_by = (SELECT id FROM accounts WHERE role = 'admin')
                  WHERE cancelled = true""")


def downgrade() -> None:
    op.drop_column('lab_enrollments', 'cancelled_by')
    op.drop_column('lab_enrollments', 'frozen_by')
    op.drop_index('lab_tas_by_ta', table_name='lab_tas')
    op.drop_table('lab_tas')
