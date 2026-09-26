"""Append-only void receipt for unposted manual accounting documents."""

import sqlalchemy as sa
from alembic import op

revision = "0188"
down_revision = "0187"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_document_void",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("accounting.organization.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("accounting.manual_document.id"), nullable=False),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", name="uq_manual_document_void_document"),
        sa.UniqueConstraint("organization_id", "request_key", name="uq_manual_document_void_key"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="manual_document_void_reason_nonempty"),
        schema="accounting",
    )
    op.execute("""
        CREATE FUNCTION accounting.guard_manual_document_void() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE document accounting.manual_document%ROWTYPE;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Manual document cancellation is immutable';
          END IF;
          SELECT * INTO document FROM accounting.manual_document
            WHERE id=NEW.document_id FOR UPDATE;
          IF document.id IS NULL OR document.organization_id IS DISTINCT FROM NEW.organization_id
             OR document.entry_id IS NOT NULL THEN
            RAISE EXCEPTION 'Only an unposted document of this organization may be cancelled';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_manual_document_void
        BEFORE INSERT OR UPDATE OR DELETE ON accounting.manual_document_void
        FOR EACH ROW EXECUTE FUNCTION accounting.guard_manual_document_void()
    """)
    op.execute("""
        CREATE TRIGGER no_truncate_manual_document_void
        BEFORE TRUNCATE ON accounting.manual_document_void
        FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation()
    """)
    op.execute("""
        CREATE FUNCTION accounting.prevent_voided_manual_document_post() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.entry_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM accounting.manual_document_void WHERE document_id=NEW.id
          ) THEN
            RAISE EXCEPTION 'Cancelled manual document cannot be posted';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER prevent_voided_manual_document_post
        BEFORE UPDATE ON accounting.manual_document
        FOR EACH ROW EXECUTE FUNCTION accounting.prevent_voided_manual_document_post()
    """)


def downgrade():
    raise RuntimeError("Manual document cancellation history cannot be discarded")
