-- Reviewed advance offsets are immutable and may only point to the two
-- accounting entries that the application snapshots in the same organization.
CREATE OR REPLACE FUNCTION accounting.guard_settlement_offset_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE posted_entry accounting.entry;
DECLARE bank_entry accounting.entry;
DECLARE source_line accounting.line;
DECLARE target_line accounting.line;
DECLARE bank_cash_line accounting.line;
DECLARE bank_settlement_line accounting.line;
DECLARE posting_line_count integer;
DECLARE bank_line_count integer;
DECLARE used_offsets numeric;
DECLARE used_invoice_settlements numeric;
DECLARE available numeric;
DECLARE expected_source_side text;
DECLARE expected_target_side text;
BEGIN
  SELECT * INTO posted_entry FROM accounting.entry
    WHERE id = NEW.entry_id AND organization_id = NEW.organization_id;
  IF posted_entry IS NULL OR posted_entry.operation <> 'settlement_offset'
     OR posted_entry.rule_version <> 'settlement-offset-v1'
     OR posted_entry.source <> ('accounting:settlement-offset:' || NEW.request_key)
     OR posted_entry.source_version <> 1 THEN
    RAISE EXCEPTION 'Settlement receipt must bind its reviewed ledger entry';
  END IF;
  SELECT * INTO bank_entry FROM accounting.entry
    WHERE id = NEW.bank_entry_id AND organization_id = NEW.organization_id;
  IF bank_entry IS NULL OR bank_entry.operation <> 'bank_settlement'
     OR bank_entry.rule_version <> 'bank-byn-v1' OR bank_entry.correction_of IS NOT NULL THEN
    RAISE EXCEPTION 'Settlement receipt must bind an uncorrected bank settlement';
  END IF;
  expected_source_side := CASE WHEN NEW.kind = 'customer_advance' THEN 'debit' ELSE 'credit' END;
  expected_target_side := CASE WHEN NEW.kind = 'customer_advance' THEN 'credit' ELSE 'debit' END;
  IF NEW.source_account = NEW.target_account THEN
    RAISE EXCEPTION 'Settlement offset source and target accounts must be different';
  END IF;
  SELECT count(*) INTO posting_line_count FROM accounting.line WHERE entry_id = NEW.entry_id;
  SELECT * INTO source_line FROM accounting.line
    WHERE entry_id = NEW.entry_id AND account_code = NEW.source_account AND side = expected_source_side;
  SELECT * INTO target_line FROM accounting.line
    WHERE entry_id = NEW.entry_id AND account_code = NEW.target_account AND side = expected_target_side;
  IF posting_line_count <> 2 OR source_line.id IS NULL OR target_line.id IS NULL
     OR source_line.amount <> NEW.amount OR target_line.amount <> NEW.amount
     OR posted_entry.digest IS DISTINCT FROM NEW.digest THEN
    RAISE EXCEPTION 'Settlement receipt amount or ledger package differs from its snapshot';
  END IF;
  SELECT count(*) INTO bank_line_count FROM accounting.line WHERE entry_id = NEW.bank_entry_id;
  SELECT * INTO bank_cash_line FROM accounting.line WHERE entry_id = NEW.bank_entry_id AND cash;
  SELECT * INTO bank_settlement_line FROM accounting.line WHERE entry_id = NEW.bank_entry_id AND NOT cash;
  IF bank_line_count <> 2 OR bank_cash_line.id IS NULL OR bank_settlement_line.id IS NULL
     OR bank_settlement_line.account_code <> NEW.source_account
     OR bank_cash_line.amount <> bank_settlement_line.amount
     OR bank_cash_line.currency <> 'BYN' OR bank_settlement_line.currency <> 'BYN'
     OR (NEW.kind = 'customer_advance' AND (bank_cash_line.side <> 'debit' OR bank_settlement_line.side <> 'credit'
                                             OR bank_settlement_line.category <> 'liability'))
     OR (NEW.kind = 'supplier_advance' AND (bank_cash_line.side <> 'credit' OR bank_settlement_line.side <> 'debit'
                                             OR bank_settlement_line.category <> 'asset')) THEN
    RAISE EXCEPTION 'Settlement receipt direction or bank source role is invalid';
  END IF;
  IF (NEW.source_snapshot->>'entry_id')::integer IS DISTINCT FROM NEW.bank_entry_id
     OR NEW.source_snapshot->>'digest' IS DISTINCT FROM bank_entry.digest
     OR NEW.target_snapshot->>'document' IS DISTINCT FROM NEW.target_document
     OR NEW.target_snapshot->'dimensions'->>'settlement_document' IS DISTINCT FROM NEW.target_document THEN
    RAISE EXCEPTION 'Settlement source or target snapshot is inconsistent';
  END IF;
  SELECT coalesce(sum(amount), 0) INTO used_offsets FROM accounting.settlement_offset_receipt
    WHERE organization_id = NEW.organization_id AND bank_entry_id = NEW.bank_entry_id;
  SELECT coalesce(sum(amount), 0) INTO used_invoice_settlements FROM sales.invoice_settlement
    WHERE organization_id = NEW.organization_id AND bank_entry_id = NEW.bank_entry_id;
  available := bank_cash_line.amount - used_offsets - used_invoice_settlements;
  IF NEW.amount > available THEN
    RAISE EXCEPTION 'Settlement receipt exceeds the available bank source amount';
  END IF;
  IF NEW.amount <= 0 OR NEW.command_digest IS NULL OR NEW.basis_digest IS NULL
     OR NEW.digest IS NULL OR NEW.target_document = '' THEN
    RAISE EXCEPTION 'Settlement receipt has incomplete immutable evidence';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_settlement_offset_receipt
BEFORE INSERT ON accounting.settlement_offset_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_settlement_offset_receipt();
CREATE TRIGGER immutable_settlement_offset_receipt
BEFORE UPDATE OR DELETE ON accounting.settlement_offset_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_settlement_offset_receipt
BEFORE TRUNCATE ON accounting.settlement_offset_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
