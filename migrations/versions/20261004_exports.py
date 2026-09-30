"""Archive export receipts and durable artifact cleanup."""
from alembic import op

revision = '20261004_exports'
down_revision = '20261003_release'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from cjudge.labs.archive import exports, cleanup_files
    exports.create(op.get_bind())
    cleanup_files.create(op.get_bind())


def downgrade() -> None:
    op.drop_table('lab_cleanup_files')
    op.drop_table('lab_exports')
