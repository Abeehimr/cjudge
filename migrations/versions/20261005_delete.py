"""Permit submission deletion only inside a verified archived-lab transaction."""
from alembic import op

revision = '20261005_delete'
down_revision = '20261004_exports'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE OR REPLACE FUNCTION reject_submission_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('cjudge.delete_lab', true) = OLD.lab_id::text
                AND EXISTS (SELECT 1 FROM labs l JOIN lab_exports e ON e.lab_id=l.id AND e.version=l.version
                    WHERE l.id=OLD.lab_id AND l.archived_at IS NOT NULL) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Accepted submission evidence is immutable';
        END; $$""")


def downgrade() -> None:
    op.execute("""CREATE OR REPLACE FUNCTION reject_submission_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Accepted submission evidence is immutable'; END; $$""")
