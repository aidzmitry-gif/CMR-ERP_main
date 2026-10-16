"""Add the versioned external-bank-account mapping registry."""
from alembic import op

revision = "0137"
down_revision = "0136"
branch_labels = None
depends_on = None


SQL = r"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE accounting.bank_account_mapping (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  provider VARCHAR(100) NOT NULL,
  external_account VARCHAR(128) NOT NULL,
  currency VARCHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  valid_from DATE NOT NULL,
  valid_to DATE,
  version INTEGER NOT NULL CHECK (version > 0),
  ledger_account_id INTEGER NOT NULL REFERENCES accounting.account(id),
  dimensions JSONB NOT NULL,
  evidence VARCHAR(1000) NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT bank_account_mapping_valid_range CHECK (valid_to IS NULL OR valid_to > valid_from),
  CONSTRAINT uq_bank_account_mapping_version
    UNIQUE (organization_id, provider, external_account, currency, version),
  CONSTRAINT uq_bank_account_mapping_valid_from
    UNIQUE (organization_id, provider, external_account, currency, valid_from),
  CONSTRAINT bank_account_mapping_external_account_no_overlap
    EXCLUDE USING gist (
      provider WITH =,
      external_account WITH =,
      currency WITH =,
      daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[)') WITH &&
    )
);
CREATE INDEX ix_bank_account_mapping_organization ON accounting.bank_account_mapping (organization_id);

CREATE OR REPLACE FUNCTION accounting.guard_bank_account_mapping_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
     OR NEW.provider IS DISTINCT FROM OLD.provider
     OR NEW.external_account IS DISTINCT FROM OLD.external_account
     OR NEW.currency IS DISTINCT FROM OLD.currency
     OR NEW.valid_from IS DISTINCT FROM OLD.valid_from
     OR NEW.version IS DISTINCT FROM OLD.version
     OR NEW.ledger_account_id IS DISTINCT FROM OLD.ledger_account_id
     OR NEW.dimensions IS DISTINCT FROM OLD.dimensions
     OR NEW.evidence IS DISTINCT FROM OLD.evidence
     OR NEW.actor IS DISTINCT FROM OLD.actor
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Bank account mapping history is immutable; only valid_to may be set';
  END IF;
  IF OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL OR NEW.valid_to <= OLD.valid_from THEN
    RAISE EXCEPTION 'Bank account mapping can only be closed once with a later valid_to';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_account_mapping_history_guard
BEFORE UPDATE ON accounting.bank_account_mapping
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_account_mapping_update();

CREATE OR REPLACE FUNCTION accounting.guard_bank_account_mapping_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Bank account mapping history is immutable; rows cannot be deleted';
END $$;
CREATE TRIGGER bank_account_mapping_delete_guard
BEFORE DELETE ON accounting.bank_account_mapping
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_account_mapping_delete();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    raise RuntimeError("Removing versioned bank-account mapping history requires an explicit data review")
