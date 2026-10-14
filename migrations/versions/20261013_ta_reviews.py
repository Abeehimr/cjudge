"""TA task maxima and retained student reviews."""
from alembic import op
import sqlalchemy as sa

revision = '20261013_ta_reviews'
down_revision = '20261013_ta_labs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('lab_tasks', sa.Column('ta_maximum', sa.Numeric(7, 2), nullable=False, server_default='0'))
    op.create_check_constraint('lab_tasks_ta_maximum_range', 'lab_tasks', 'ta_maximum >= 0 AND ta_maximum <= 10000')
    op.create_table('ta_reviews',
        sa.Column('lab_id', sa.Uuid(), sa.ForeignKey('labs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('student_id', sa.Uuid(), sa.ForeignKey('accounts.id'), primary_key=True),
        sa.Column('owner_id', sa.Uuid(), sa.ForeignKey('accounts.id')),
        sa.Column('reviewer_id', sa.Uuid(), sa.ForeignKey('accounts.id')),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('finalized_at', sa.DateTime(timezone=True)),
        sa.Column('needs_recheck', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ta_reviews_owner', 'ta_reviews', ['lab_id', 'owner_id'])
    op.create_table('ta_review_marks',
        sa.Column('lab_id', sa.Uuid(), primary_key=True),
        sa.Column('student_id', sa.Uuid(), primary_key=True),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id'), primary_key=True),
        sa.Column('earned_numerator', sa.BigInteger(), nullable=False),
        sa.Column('earned_denominator', sa.BigInteger(), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(['lab_id', 'student_id'], ['ta_reviews.lab_id', 'ta_reviews.student_id'], ondelete='CASCADE'),
        sa.CheckConstraint('earned_denominator > 0'),
        sa.CheckConstraint('earned_numerator >= 0'))


def downgrade() -> None:
    op.drop_table('ta_review_marks')
    op.drop_index('ta_reviews_owner', table_name='ta_reviews')
    op.drop_table('ta_reviews')
    op.drop_constraint('lab_tasks_ta_maximum_range', 'lab_tasks')
    op.drop_column('lab_tasks', 'ta_maximum')
