"""Labs, enrollments, protected PDF versions and announcements."""
from alembic import op
import sqlalchemy as sa

revision = '20260930_labs'
down_revision = '20260929_tasks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('labs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('strict_ip', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('starts_at', sa.DateTime(timezone=True)),
        sa.Column('ends_at', sa.DateTime(timezone=True)),
        sa.Column('first_released_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('(starts_at IS NULL AND ends_at IS NULL) OR (starts_at IS NOT NULL AND ends_at > starts_at)'))
    op.execute("ALTER TABLE labs ADD CONSTRAINT no_lab_overlap EXCLUDE USING gist "
               "(tstzrange(starts_at, ends_at, '[)') WITH &&) WHERE (starts_at IS NOT NULL)")
    op.create_table('lab_tasks',
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id'), primary_key=True),
        sa.Column('position', sa.Integer(), primary_key=True),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id'), nullable=False),
        sa.UniqueConstraint('lab_id', 'revision_id'))
    op.create_table('lab_enrollments',
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id'), primary_key=True),
        sa.Column('account_id', sa.Uuid(), sa.ForeignKey('accounts.id'), primary_key=True),
        sa.Column('frozen', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('freeze_reason', sa.String(500)),
        sa.Column('binding_hash', sa.String(64)),
        sa.Column('bound_ip', sa.String(45)),
        sa.Column('last_ip', sa.String(45)),
        sa.Column('ip_changed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('bound_at', sa.DateTime(timezone=True)))
    op.create_index('enrollments_by_account', 'lab_enrollments', ['account_id'])
    op.create_table('lab_pdfs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id'), nullable=False),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('replaces_id', sa.Uuid(), sa.ForeignKey('lab_pdfs.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('pdfs_by_lab', 'lab_pdfs', ['lab_id'])
    op.create_table('lab_announcements',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id'), nullable=False),
        sa.Column('author_id', sa.Uuid(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('body', sa.String(4000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('announcements_by_lab', 'lab_announcements', ['lab_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('lab_announcements')
    op.drop_table('lab_pdfs')
    op.drop_table('lab_enrollments')
    op.drop_table('lab_tasks')
    op.drop_table('labs')
