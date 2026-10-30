"""Persist immutable author scope for new Office drafts, without claiming history."""
import sqlalchemy as sa
from alembic import op

revision = "0199"
down_revision = "0198"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.add_column("office_doc", sa.Column("draft_owner_subject", sa.String(200), nullable=True), schema="office")
    op.execute("""
        CREATE FUNCTION office.preserve_draft_owner() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.draft_owner_subject IS DISTINCT FROM OLD.draft_owner_subject THEN
                RAISE EXCEPTION 'Office draft owner is immutable';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER office_draft_owner_immutable
        BEFORE UPDATE OF draft_owner_subject ON office.office_doc
        FOR EACH ROW EXECUTE FUNCTION office.preserve_draft_owner();
    """)


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM office.office_doc WHERE draft_owner_subject IS NOT NULL) THEN
                RAISE EXCEPTION 'Office draft ownership history prevents downgrade';
            END IF;
        END $$;
        DROP TRIGGER office_draft_owner_immutable ON office.office_doc;
        DROP FUNCTION office.preserve_draft_owner();
    """)
    op.drop_column("office_doc", "draft_owner_subject", schema="office")
