"""Store isolated admin task test batches and per-case evidence."""
from alembic import op
import sqlalchemy as sa

revision = '20261012_task_tester'
down_revision = '20261011_lab_marks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh M5 baselines import the current workers table, while existing installs need the column.
    op.execute('ALTER TABLE judge_workers ADD COLUMN IF NOT EXISTS last_background_kind varchar(16)')
    op.create_table('tester_batches',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id'), nullable=False),
        sa.Column('revision_id', sa.Uuid(), sa.ForeignKey('task_revisions.id'), nullable=False),
        sa.Column('actor_id', sa.Uuid(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(128)),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('delete_reason', sa.Text()))
    op.create_index('tester_idempotency', 'tester_batches', ['actor_id', 'idempotency_key'], unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.create_table('tester_sources',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('batch_id', sa.Uuid(), sa.ForeignKey('tester_batches.id'), nullable=False),
        sa.Column('filename', sa.String(160), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False, server_default='queued'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('passed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fault_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('attempt_id', sa.Uuid()),
        sa.Column('last_claimed_at', sa.DateTime(timezone=True)),
        sa.Column('compiler_feedback', sa.Text(), nullable=False, server_default=''),
        sa.Column('compiler_truncated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('diagnostic', sa.Text(), nullable=False, server_default=''),
        sa.CheckConstraint("state IN ('queued','testing','complete','failed')", name='tester_state'))
    op.create_table('tester_attempts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('tester_sources.id'), nullable=False),
        sa.Column('worker_slot', sa.Integer(), nullable=False),
        sa.Column('worker_generation', sa.Uuid(), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('outcome', sa.String(16)))
    op.create_table('tester_cases',
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('tester_sources.id'), primary_key=True),
        sa.Column('number', sa.Integer(), primary_key=True),
        sa.Column('verdict', sa.String(16), nullable=False),
        sa.Column('cpu_seconds', sa.Float(), nullable=False),
        sa.Column('wall_seconds', sa.Float(), nullable=False),
        sa.Column('memory_kib', sa.Integer(), nullable=False),
        sa.Column('stdout', sa.LargeBinary(), nullable=False),
        sa.Column('stderr', sa.LargeBinary(), nullable=False),
        sa.Column('stdout_truncated', sa.Boolean(), nullable=False),
        sa.Column('stderr_truncated', sa.Boolean(), nullable=False))


def downgrade() -> None:
    for name in ('tester_cases', 'tester_attempts', 'tester_sources', 'tester_batches'):
        op.drop_table(name)
    op.drop_column('judge_workers', 'last_background_kind')
