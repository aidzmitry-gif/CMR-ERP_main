-- Proposal-only guards for reviewed paid and warranty repair packages.

CREATE OR REPLACE FUNCTION accounting.guard_repair_accounting_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'repair_service'
     OR e.source IS DISTINCT FROM 'service:repair:'||NEW.organization_id||':'||NEW.service_request_id
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR e.digest IS DISTINCT FROM NEW.digest
     OR to_char(e.posting_date,'YYYY-MM') IS DISTINCT FROM NEW.month
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR (NEW.command->>'service_request_id')::integer IS DISTINCT FROM NEW.service_request_id
     OR (NEW.command->>'source_version')::integer IS DISTINCT FROM NEW.source_version
     OR NEW.command->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.command->>'serial_number' IS DISTINCT FROM NEW.serial_number
     OR NEW.command->>'owner_type' IS DISTINCT FROM NEW.owner_type
     OR NEW.command->>'owner_reference' IS DISTINCT FROM NEW.owner_reference
     OR NEW.command->>'coverage' IS DISTINCT FROM NEW.coverage
     OR NEW.source->>'scope' IS DISTINCT FROM 'repair_accounting'
     OR (NEW.source->>'service_request_id')::integer IS DISTINCT FROM NEW.service_request_id
     OR NEW.source->>'source_digest' IS DISTINCT FROM NEW.source_digest
     OR NEW.source->>'serial_number' IS DISTINCT FROM NEW.serial_number
     OR NEW.source->>'owner_type' IS DISTINCT FROM NEW.owner_type
     OR NEW.source->>'owner_reference' IS DISTINCT FROM NEW.owner_reference
     OR NEW.source->>'coverage' IS DISTINCT FROM NEW.coverage
     OR NEW.posting IS NULL THEN
    RAISE EXCEPTION 'Repair accounting receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count < 1 OR credit_count < 1 OR debit_count <> credit_count THEN
    RAISE EXCEPTION 'Repair accounting package must contain balanced debit and credit lines';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.command::jsonb->'lines') line
    WHERE line->>'material_owner'='customer'
      AND ((line->>'amount_byn')::numeric <> 0 OR line->>'debit_account' IS NOT NULL
           OR line->>'credit_account' IS NOT NULL)
  ) THEN
    RAISE EXCEPTION 'Customer-owned repair materials cannot carry an owned accounting value';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_repair_accounting_receipt
BEFORE INSERT ON accounting.repair_accounting_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_repair_accounting_receipt();

CREATE TRIGGER immutable_repair_accounting_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.repair_accounting_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.check_repair_accounting_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'repair_service' THEN RETURN NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM accounting.repair_accounting_receipt WHERE entry_id=target) THEN
    RAISE EXCEPTION 'Repair service posting requires its complete source receipt';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER complete_repair_accounting_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_repair_accounting_complete();

CREATE CONSTRAINT TRIGGER complete_repair_accounting_receipt
AFTER INSERT ON accounting.repair_accounting_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_repair_accounting_complete();
