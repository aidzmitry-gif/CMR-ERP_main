-- Imported bank rows are an explicit source binding, not an automatic posting.
CREATE OR REPLACE FUNCTION accounting.guard_bank_import_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry;
DECLARE cash_line accounting.line;
DECLARE settlement_line accounting.line;
DECLARE line_count integer;
BEGIN
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
     OR cash_line.side <> 'debit' OR settlement_line.side <> 'credit'
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

CREATE TRIGGER guard_bank_import_receipt
BEFORE INSERT ON accounting.bank_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_import_receipt();
CREATE TRIGGER immutable_bank_import_receipt
BEFORE UPDATE OR DELETE ON accounting.bank_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_bank_import_receipt
BEFORE TRUNCATE ON accounting.bank_import_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
