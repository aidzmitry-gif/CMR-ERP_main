"""Full bank-statement source provenance and direction; preserve legacy receipts."""
from alembic import op

revision = "0135"
down_revision = "0134"
branch_labels = None
depends_on = None

SQL = r"""
ALTER TABLE finance.bank_transaction
  ADD COLUMN direction varchar(16) NOT NULL DEFAULT 'receipt',
  ADD COLUMN source_provider varchar(100),
  ADD COLUMN source_external_id varchar(200),
  ADD COLUMN source_kind varchar(8),
  ADD COLUMN source_reference varchar(500),
  ADD CONSTRAINT bank_statement_direction CHECK (direction IN ('receipt','payment')),
  ADD CONSTRAINT bank_statement_provenance CHECK (
    (source_provider IS NULL AND source_external_id IS NULL AND source_kind IS NULL
      AND source_reference IS NULL AND direction='receipt') OR
    (source_provider IS NOT NULL AND length(btrim(source_provider))>0
      AND source_external_id IS NOT NULL AND length(btrim(source_external_id))>0
      AND source_kind IS NOT NULL AND source_kind IN ('file','api')
      AND source_reference IS NOT NULL AND length(btrim(source_reference))>0
      AND occurred_on IS NOT NULL AND amount>0 AND amount<1000000000000 AND currency='BYN'
      AND account_code IS NOT NULL AND length(btrim(account_code))>0
      AND payment_id IS NULL AND allocation_id IS NULL AND match_status='unmatched'));
CREATE UNIQUE INDEX bank_statement_source_identity
  ON finance.bank_transaction(source_provider,account_code,source_external_id)
  WHERE source_provider IS NOT NULL;
CREATE OR REPLACE FUNCTION accounting.guard_bound_bank_source_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.id,NEW.ext_id,NEW.occurred_on,NEW.amount,NEW.currency,NEW.payer_unp,NEW.payer_name,NEW.purpose,NEW.account_code,
           NEW.direction,NEW.source_provider,NEW.source_external_id,NEW.source_kind,NEW.source_reference)
       IS NOT DISTINCT FROM ROW(OLD.id,OLD.ext_id,OLD.occurred_on,OLD.amount,OLD.currency,OLD.payer_unp,OLD.payer_name,OLD.purpose,OLD.account_code,
           OLD.direction,OLD.source_provider,OLD.source_external_id,OLD.source_kind,OLD.source_reference)
    THEN RETURN NEW; END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.source_binding WHERE source_type='finance_bank_transaction' AND source_id=OLD.id) THEN
    RAISE EXCEPTION 'Bound bank source financial fields are immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
-- Imported bank rows are an explicit source binding, not an automatic posting.
CREATE OR REPLACE FUNCTION accounting.guard_bank_import_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry;
DECLARE cash_line accounting.line;
DECLARE settlement_line accounting.line;
DECLARE line_count integer;
DECLARE source_row finance.bank_transaction;
BEGIN
  SELECT * INTO source_row FROM finance.bank_transaction WHERE id=NEW.source_transaction_id FOR UPDATE;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM accounting.source_binding
      WHERE source_type='finance_bank_transaction' AND source_id=source_row.id
        AND organization_id=NEW.organization_id AND ownership='own')
     OR NEW.amount IS DISTINCT FROM source_row.amount
     OR NEW.source_ext_id IS DISTINCT FROM source_row.ext_id THEN
    RAISE EXCEPTION 'Bank receipt requires its exact owned source';
  END IF;
  SELECT * INTO e FROM accounting.entry
    WHERE id = NEW.entry_id AND organization_id = NEW.organization_id;
  IF e IS NULL OR e.operation <> 'bank_settlement'
     OR e.rule_version <> 'bank-byn-v1'
     OR e.source <> NEW.source OR e.source_version <> 1
     OR e.digest <> NEW.digest THEN
    RAISE EXCEPTION 'Bank import receipt must bind its reviewed bank entry';
  END IF;
  SELECT count(*) INTO line_count FROM accounting.line WHERE entry_id = NEW.entry_id;
  SELECT * INTO cash_line FROM accounting.line WHERE entry_id = NEW.entry_id AND cash;
  SELECT * INTO settlement_line FROM accounting.line WHERE entry_id = NEW.entry_id AND NOT cash;
  IF line_count <> 2 OR cash_line.id IS NULL OR settlement_line.id IS NULL
     OR cash_line.side <> (CASE WHEN source_row.direction='payment' THEN 'credit' ELSE 'debit' END)
     OR settlement_line.side <> (CASE WHEN source_row.direction='payment' THEN 'debit' ELSE 'credit' END)
     OR cash_line.account_code <> NEW.bank_account
     OR settlement_line.account_code <> NEW.settlement_account
     OR cash_line.amount <> NEW.amount OR settlement_line.amount <> NEW.amount
     OR cash_line.currency <> 'BYN' OR settlement_line.currency <> 'BYN'
     OR cash_line.dimensions->>'bank_statement' IS DISTINCT FROM NEW.source_ext_id
     OR NEW.source_transaction_id <= 0 OR NEW.source_digest IS NULL THEN
    RAISE EXCEPTION 'Bank import receipt does not match its two-line BYN settlement';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.command_digest IS NULL OR NEW.basis_digest IS NULL
     OR NEW.digest IS NULL OR NEW.source = '' THEN
    RAISE EXCEPTION 'Bank import receipt has incomplete source evidence';
  END IF;
  RETURN NEW;
END $$;

"""


def upgrade():
    op.execute(SQL)


def downgrade():
    raise RuntimeError("Full statement history cannot be discarded by automatic downgrade")
