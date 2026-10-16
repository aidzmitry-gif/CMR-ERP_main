"""Bind correction drafts to the exact posted receipt revision and entry."""

import sqlalchemy as sa
from alembic import op

revision = "0190"
down_revision = "0189"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("receipt_document", sa.Column("correction_of_receipt_id", sa.Integer(), nullable=True),
                  schema="procurement")
    op.add_column("receipt_document", sa.Column("correction_of_version", sa.Integer(), nullable=True),
                  schema="procurement")
    op.add_column("receipt_document", sa.Column("correction_of_entry_id", sa.Integer(), nullable=True),
                  schema="procurement")
    op.create_check_constraint(
        "receipt_document_correction_complete", "receipt_document",
        "(correction_of_receipt_id IS NULL AND correction_of_version IS NULL AND correction_of_entry_id IS NULL) "
        "OR (correction_of_receipt_id IS NOT NULL AND correction_of_version IS NOT NULL AND correction_of_entry_id IS NOT NULL)",
        schema="procurement",
    )
    op.create_check_constraint(
        "receipt_document_correction_not_self", "receipt_document",
        "correction_of_receipt_id IS NULL OR correction_of_receipt_id <> id", schema="procurement",
    )
    op.create_foreign_key(
        "fk_receipt_document_correction_parent", "receipt_document", "receipt_document",
        ["correction_of_receipt_id"], ["id"], source_schema="procurement", referent_schema="procurement",
    )
    op.create_foreign_key(
        "fk_receipt_document_correction_entry", "receipt_document", "entry",
        ["correction_of_entry_id"], ["id"], source_schema="procurement", referent_schema="accounting",
    )
    op.create_index("ix_receipt_document_correction_parent", "receipt_document",
                    ["correction_of_receipt_id", "correction_of_version"], schema="procurement")
    op.create_index("ix_receipt_document_correction_entry", "receipt_document",
                    ["correction_of_entry_id"], schema="procurement")

    op.execute(r"""
CREATE FUNCTION procurement.guard_receipt_document_correction() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE original procurement.receipt_document%ROWTYPE;
DECLARE posted procurement.receipt_posting%ROWTYPE;
BEGIN
  IF TG_OP = 'UPDATE' AND (
       NEW.correction_of_receipt_id IS DISTINCT FROM OLD.correction_of_receipt_id
       OR NEW.correction_of_version IS DISTINCT FROM OLD.correction_of_version
       OR NEW.correction_of_entry_id IS DISTINCT FROM OLD.correction_of_entry_id) THEN
    RAISE EXCEPTION 'Receipt correction source identity is immutable';
  END IF;
  IF NEW.correction_of_receipt_id IS NULL THEN
    RETURN NEW;
  END IF;
  PERFORM 1 FROM accounting.organization
    WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO original FROM procurement.receipt_document
    WHERE id=NEW.correction_of_receipt_id FOR UPDATE;
  SELECT * INTO posted FROM procurement.receipt_posting
    WHERE receipt_id=NEW.correction_of_receipt_id;
  IF original.id IS NULL OR original.id=NEW.id
     OR original.organization_id IS DISTINCT FROM NEW.organization_id
     OR original.current_version IS DISTINCT FROM NEW.correction_of_version
     OR posted.receipt_id IS NULL
     OR posted.version IS DISTINCT FROM NEW.correction_of_version
     OR posted.entry_id IS DISTINCT FROM NEW.correction_of_entry_id
     OR NOT EXISTS (SELECT 1 FROM procurement.receipt_revision r
       WHERE r.receipt_id=NEW.correction_of_receipt_id AND r.version=NEW.correction_of_version)
     OR NOT EXISTS (SELECT 1 FROM accounting.entry e
       WHERE e.id=NEW.correction_of_entry_id AND e.organization_id=NEW.organization_id
         AND e.source='procurement:receipt:'||NEW.correction_of_receipt_id::text
         AND e.source_version=NEW.correction_of_version AND e.operation='inventory_purchase') THEN
    RAISE EXCEPTION 'Receipt correction must identify the exact posted source in this organization';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_receipt_document_correction
BEFORE INSERT OR UPDATE ON procurement.receipt_document
FOR EACH ROW EXECUTE FUNCTION procurement.guard_receipt_document_correction();

CREATE FUNCTION procurement.verify_receipt_correction_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE original_document jsonb;
DECLARE copied_document jsonb;
BEGIN
  IF NEW.correction_of_receipt_id IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT document::jsonb INTO original_document FROM procurement.receipt_revision
    WHERE receipt_id=NEW.correction_of_receipt_id AND version=NEW.correction_of_version;
  SELECT document::jsonb INTO copied_document FROM procurement.receipt_revision
    WHERE receipt_id=NEW.id AND version=1;
  IF original_document IS NULL OR copied_document IS DISTINCT FROM original_document
     OR EXISTS (SELECT 1 FROM accounting.entry e
       WHERE e.organization_id=NEW.organization_id
         AND e.source='procurement:receipt:'||NEW.id::text) THEN
    RAISE EXCEPTION 'Receipt correction draft must preserve the exact posted source revision';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER receipt_correction_exact_revision
AFTER INSERT ON procurement.receipt_document
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION procurement.verify_receipt_correction_revision();

CREATE FUNCTION procurement.reject_correction_receipt_posting() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_org integer;
BEGIN
  SELECT organization_id INTO source_org FROM procurement.receipt_document
    WHERE id=NEW.receipt_id;
  IF source_org IS NOT NULL THEN
    PERFORM 1 FROM accounting.organization WHERE id=source_org FOR UPDATE;
  END IF;
  IF EXISTS (SELECT 1 FROM procurement.receipt_document
      WHERE id=NEW.receipt_id AND correction_of_receipt_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Correction draft requires the separately approved correction workflow';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER reject_correction_receipt_posting
BEFORE INSERT ON procurement.receipt_posting
FOR EACH ROW EXECUTE FUNCTION procurement.reject_correction_receipt_posting();

CREATE FUNCTION accounting.reject_correction_receipt_entry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.source LIKE 'procurement:receipt:%' THEN
    PERFORM 1 FROM accounting.organization
      WHERE id=NEW.organization_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM procurement.receipt_document
        WHERE organization_id=NEW.organization_id
          AND NEW.source='procurement:receipt:'||id::text
          AND correction_of_receipt_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Receipt correction draft requires the separately approved correction workflow';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER _00_reject_correction_receipt_entry
BEFORE INSERT OR UPDATE ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_correction_receipt_entry();

CREATE FUNCTION wms.reject_correction_primary_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization
    WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM procurement.receipt_document
      WHERE id=NEW.source_receipt_id AND correction_of_receipt_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Correction draft cannot be prepared as a warehouse primary receipt';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER _00_reject_correction_primary_receipt
BEFORE INSERT ON wms.primary_receipt_binding
FOR EACH ROW EXECUTE FUNCTION wms.reject_correction_primary_receipt();
""")


def downgrade():
    op.execute("""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM procurement.receipt_document WHERE correction_of_receipt_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Cannot downgrade while receipt correction drafts exist';
  END IF;
END $$;
DROP TRIGGER _00_reject_correction_primary_receipt ON wms.primary_receipt_binding;
DROP FUNCTION wms.reject_correction_primary_receipt();
DROP TRIGGER _00_reject_correction_receipt_entry ON accounting.entry;
DROP FUNCTION accounting.reject_correction_receipt_entry();
DROP TRIGGER reject_correction_receipt_posting ON procurement.receipt_posting;
DROP FUNCTION procurement.reject_correction_receipt_posting();
DROP TRIGGER receipt_correction_exact_revision ON procurement.receipt_document;
DROP FUNCTION procurement.verify_receipt_correction_revision();
DROP TRIGGER guard_receipt_document_correction ON procurement.receipt_document;
DROP FUNCTION procurement.guard_receipt_document_correction();
""")
    op.drop_index("ix_receipt_document_correction_entry", table_name="receipt_document", schema="procurement")
    op.drop_index("ix_receipt_document_correction_parent", table_name="receipt_document", schema="procurement")
    op.drop_constraint("fk_receipt_document_correction_entry", "receipt_document", schema="procurement", type_="foreignkey")
    op.drop_constraint("fk_receipt_document_correction_parent", "receipt_document", schema="procurement", type_="foreignkey")
    op.drop_constraint("receipt_document_correction_not_self", "receipt_document", schema="procurement", type_="check")
    op.drop_constraint("receipt_document_correction_complete", "receipt_document", schema="procurement", type_="check")
    op.drop_column("receipt_document", "correction_of_entry_id", schema="procurement")
    op.drop_column("receipt_document", "correction_of_version", schema="procurement")
    op.drop_column("receipt_document", "correction_of_receipt_id", schema="procurement")
