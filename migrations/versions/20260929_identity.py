"""Global accounts and revocable sessions.

Revision ID: 20260929_identity
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "20260929_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role", sa.String(7), nullable=False),
        sa.Column("roll_number", sa.String(64), unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("encrypted_password", sa.LargeBinary()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(role = 'admin' AND roll_number IS NULL AND encrypted_password IS NULL) OR "
                           "(role = 'student' AND roll_number IS NOT NULL AND encrypted_password IS NOT NULL)"),
    )
    op.create_index("one_admin", "accounts", ["role"], unique=True, postgresql_where=sa.text("role = 'admin'"))
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("sessions_by_account", "sessions", ["account_id"])
    op.create_table(
        "login_attempts",
        sa.Column("identifier", sa.String(72), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("accounts.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("login_attempts")
    op.drop_index("sessions_by_account", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("one_admin", table_name="accounts")
    op.drop_table("accounts")
