-- Unallocated proposal guard: an interim gross-payroll import is admitted
-- only together with its immutable, source-bound ledger package.
CREATE OR REPLACE FUNCTION accounting.guard_payroll_accrual_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'payroll_accrual_import'
     OR e.source IS DISTINCT FROM 'payroll:accrual:'||NEW.organization_id||':'||NEW.source_document
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.source->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Payroll accrual receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Payroll accrual import must contain paired debit and credit lines';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_payroll_accrual_receipt
BEFORE INSERT ON accounting.payroll_accrual_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_accrual_receipt();

CREATE TRIGGER immutable_payroll_accrual_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_accrual_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_payroll_accrual_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.payroll_accrual_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'payroll_accrual_import' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.payroll_accrual_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Payroll accrual import requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_payroll_accrual_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_accrual_complete();
CREATE CONSTRAINT TRIGGER complete_payroll_accrual_receipt
AFTER INSERT ON accounting.payroll_accrual_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_accrual_complete();

-- A reviewed statutory payroll package is source-bound in the same way as a
-- gross accrual package.  The amounts are imported from evidence; no rate or
-- statutory-report calculation is implied by this receipt.
CREATE OR REPLACE FUNCTION accounting.guard_payroll_statutory_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'payroll_statutory_import'
     OR e.source IS DISTINCT FROM 'payroll:statutory:'||NEW.organization_id||':'||NEW.source_document
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'source_document' IS DISTINCT FROM NEW.source_document
     OR (NEW.source->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Payroll statutory receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Payroll statutory import must contain paired debit and credit lines';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_payroll_statutory_receipt
BEFORE INSERT ON accounting.payroll_statutory_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_statutory_receipt();

CREATE TRIGGER immutable_payroll_statutory_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_statutory_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_payroll_statutory_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.payroll_statutory_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'payroll_statutory_import' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.payroll_statutory_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Payroll statutory import requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_payroll_statutory_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_statutory_complete();
CREATE CONSTRAINT TRIGGER complete_payroll_statutory_receipt
AFTER INSERT ON accounting.payroll_statutory_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_payroll_statutory_complete();
