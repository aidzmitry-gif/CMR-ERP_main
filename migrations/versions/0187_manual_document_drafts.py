"""Versioned manual accounting documents before immutable posting."""

import sqlalchemy as sa
from alembic import op

revision = "0187"
down_revision = "0186"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("accounting.organization.id"), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("create_key", sa.String(length=36), nullable=False),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("accounting.entry.id")),
        sa.Column("post_key", sa.String(length=36)),
        sa.Column("post_digest", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "create_key", name="uq_manual_document_create_key"),
        sa.UniqueConstraint("entry_id", name="uq_manual_document_entry"),
        sa.CheckConstraint("version >= 1", name="manual_document_version_positive"),
        sa.CheckConstraint("length(trim(source)) > 0", name="manual_document_source_nonempty"),
        sa.CheckConstraint("(entry_id IS NULL AND post_key IS NULL AND post_digest IS NULL) "
                           "OR (entry_id IS NOT NULL AND post_key IS NOT NULL AND post_digest IS NOT NULL)",
                           name="manual_document_post_complete"),
        schema="accounting",
    )
    op.create_index("ix_manual_document_org_date", "manual_document",
                    ["organization_id", "posting_date"], schema="accounting")
    op.create_table(
        "manual_document_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("accounting.manual_document.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("posting", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "version", name="uq_manual_document_revision_version"),
        sa.UniqueConstraint("document_id", "request_key", name="uq_manual_document_revision_key"),
        sa.CheckConstraint("version >= 1", name="manual_document_revision_version_positive"),
        schema="accounting",
    )
    op.create_index("ix_manual_document_revision_document_id", "manual_document_revision",
                    ["document_id"], schema="accounting")
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.guard_manual_document() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE saved accounting.manual_document_revision%ROWTYPE;
                posted accounting.entry%ROWTYPE;
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'Manual document history is append-only';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id
             OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
             OR NEW.create_key IS DISTINCT FROM OLD.create_key
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR OLD.entry_id IS NOT NULL THEN
            RAISE EXCEPTION 'Manual document identity and posted state are immutable';
          END IF;
          SELECT * INTO saved FROM accounting.manual_document_revision
            WHERE document_id=NEW.id AND version=NEW.version;
          IF saved.id IS NULL OR saved.posting->>'source' IS DISTINCT FROM NEW.source
             OR saved.posting->>'posting_date' IS DISTINCT FROM NEW.posting_date::text THEN
            RAISE EXCEPTION 'Manual document update needs its exact saved revision';
          END IF;
          IF NEW.entry_id IS NULL THEN
            IF NEW.version <> OLD.version + 1 OR NEW.post_key IS NOT NULL
               OR NEW.post_digest IS NOT NULL THEN
              RAISE EXCEPTION 'Manual document edit must append one revision';
            END IF;
          ELSE
            SELECT * INTO posted FROM accounting.entry WHERE id=NEW.entry_id;
            IF NEW.version IS DISTINCT FROM OLD.version
               OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.posting_date IS DISTINCT FROM OLD.posting_date
               OR NEW.post_key IS NULL OR NEW.post_digest IS DISTINCT FROM saved.digest
               OR posted.id IS NULL OR posted.organization_id IS DISTINCT FROM NEW.organization_id
               OR posted.source IS DISTINCT FROM NEW.source
               OR posted.posting_date IS DISTINCT FROM NEW.posting_date
               OR posted.source_version IS DISTINCT FROM (saved.posting->>'source_version')::int
               OR posted.operation IS DISTINCT FROM 'manual'
               OR posted.digest IS DISTINCT FROM saved.digest THEN
              RAISE EXCEPTION 'Manual document posting needs its exact ledger receipt';
            END IF;
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION accounting.assert_manual_document_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM accounting.manual_document_revision
                         WHERE document_id=NEW.id AND version=NEW.version
                           AND posting->>'source'=NEW.source
                           AND posting->>'posting_date'=NEW.posting_date::text) THEN
            RAISE EXCEPTION 'Manual document has no matching saved revision';
          END IF;
          RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_manual_document
        BEFORE UPDATE OR DELETE ON accounting.manual_document
        FOR EACH ROW EXECUTE FUNCTION accounting.guard_manual_document()
    """)
    op.execute("""
        CREATE TRIGGER no_truncate_manual_document
        BEFORE TRUNCATE ON accounting.manual_document
        FOR EACH STATEMENT EXECUTE FUNCTION accounting.guard_manual_document()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER manual_document_has_revision
        AFTER INSERT OR UPDATE ON accounting.manual_document
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION accounting.assert_manual_document_revision()
    """)
    op.execute("""
        CREATE TRIGGER immutable_manual_document_revision
        BEFORE UPDATE OR DELETE ON accounting.manual_document_revision
        FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation()
    """)
    op.execute("""
        CREATE TRIGGER no_truncate_manual_document_revision
        BEFORE TRUNCATE ON accounting.manual_document_revision
        FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation()
    """)


def downgrade():
    raise RuntimeError("Manual document and posting history cannot be discarded")
