"""Reject ambiguous legacy/full-statement duplicates under concurrent ingestion."""
from alembic import op

revision = "0136"
down_revision = "0135"
branch_labels = None
depends_on = None

SQL = r"""
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM finance.bank_transaction legacy
      JOIN finance.bank_transaction statement ON statement.source_external_id=legacy.ext_id
      WHERE legacy.source_provider IS NULL AND statement.source_provider IS NOT NULL) THEN
    RAISE EXCEPTION 'Reconcile existing legacy/full-statement bank identity collisions before upgrade';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_bank_source_identity_bridge() RETURNS trigger
LANGUAGE plpgsql VOLATILE AS $$
DECLARE identity_key text;
DECLARE old_identity_key text;
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION 'Bank source writes require READ COMMITTED isolation'
      USING ERRCODE='25000';
  END IF;
  identity_key := COALESCE(NEW.source_external_id, NEW.ext_id);
  -- Both ingestion paths acquire the same transaction lock before insertion.
  -- The following SELECT is a fresh volatile-function query after any wait.
  IF TG_OP='UPDATE' THEN
    old_identity_key := COALESCE(OLD.source_external_id, OLD.ext_id);
    IF old_identity_key < identity_key THEN
      PERFORM pg_advisory_xact_lock(hashtextextended(old_identity_key, 0));
      PERFORM pg_advisory_xact_lock(hashtextextended(identity_key, 0));
    ELSE
      PERFORM pg_advisory_xact_lock(hashtextextended(identity_key, 0));
      PERFORM pg_advisory_xact_lock(hashtextextended(old_identity_key, 0));
    END IF;
  ELSE
    PERFORM pg_advisory_xact_lock(hashtextextended(identity_key, 0));
  END IF;
  IF EXISTS (
    SELECT 1 FROM finance.bank_transaction other
    WHERE other.id IS DISTINCT FROM (CASE WHEN TG_OP='UPDATE' THEN OLD.id ELSE NULL END) AND (
      (NEW.source_provider IS NULL AND other.source_provider IS NOT NULL
        AND other.source_external_id=NEW.ext_id) OR
      (NEW.source_provider IS NOT NULL AND other.source_provider IS NULL
        AND other.ext_id=NEW.source_external_id)
    )
  ) THEN
    RAISE EXCEPTION 'Bank identity exists in the other ingestion path; reconcile the existing source'
      USING ERRCODE='23505', CONSTRAINT='bank_source_cross_path_identity';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_source_identity_bridge
BEFORE INSERT OR UPDATE OF ext_id,source_external_id,source_provider ON finance.bank_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_source_identity_bridge();

CREATE OR REPLACE FUNCTION accounting.guard_bank_import_line_seal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.bank_import_receipt WHERE entry_id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Bank import receipt seals its ledger lines';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_import_line_seal BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_import_line_seal();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    raise RuntimeError("Removing bank source identity protection requires an explicit data review")
