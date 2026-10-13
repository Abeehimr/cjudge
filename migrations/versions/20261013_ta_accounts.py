"""Globally unique account usernames and TA role."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_ta_accounts"
down_revision = "20261012_task_tester"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("username", sa.String(64)))
    op.execute("UPDATE accounts SET username = CASE WHEN role = 'admin' THEN 'ADMIN' ELSE roll_number END")
    op.alter_column("accounts", "username", nullable=False)
    op.create_unique_constraint("accounts_username_key", "accounts", ["username"])
    op.drop_constraint("accounts_check", "accounts", type_="check")
    op.create_check_constraint("accounts_identity", "accounts", """
        (role = 'admin' AND username = 'ADMIN' AND roll_number IS NULL AND encrypted_password IS NULL)
        OR (role = 'student' AND username = roll_number AND encrypted_password IS NOT NULL)
        OR (role = 'ta' AND username <> 'ADMIN' AND roll_number IS NULL AND encrypted_password IS NULL)
    """)
    op.execute("UPDATE login_attempts SET identifier = split_part(identifier, ':', 2) WHERE identifier LIKE 'admin:%' OR identifier LIKE 'student:%'")


def downgrade() -> None:
    op.execute("DELETE FROM accounts WHERE role = 'ta'")
    op.drop_constraint("accounts_identity", "accounts", type_="check")
    op.create_check_constraint("accounts_check", "accounts", """
        (role = 'admin' AND roll_number IS NULL AND encrypted_password IS NULL)
        OR (role = 'student' AND roll_number IS NOT NULL AND encrypted_password IS NOT NULL)
    """)
    op.drop_constraint("accounts_username_key", "accounts", type_="unique")
    op.drop_column("accounts", "username")
