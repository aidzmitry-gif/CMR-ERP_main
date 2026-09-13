-- Unallocated proposal guard: a finished-goods transfer is admitted only
-- together with its immutable source package and a balanced two-line entry.
CREATE OR REPLACE FUNCTION accounting.guard_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id <> NEW.organization_id
     OR e.source IS DISTINCT FROM 'production:output-transfer:'||NEW.organization_id||':'||NEW.order_id
     OR e.operation IS DISTINCT FROM 'production_output_transfer'
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'order_id' IS DISTINCT FROM NEW.order_id::text
     OR NEW.command->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
     OR NEW.command->>'digest' IS DISTINCT FROM NEW.digest
     OR NEW.posting IS NULL OR NEW.basis IS NULL THEN
    RAISE EXCEPTION 'Production output transfer receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count <> 1 OR credit_count <> 1 THEN
    RAISE EXCEPTION 'Production output transfer must contain one debit and one credit';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_production_output_transfer_receipt
BEFORE INSERT ON accounting.production_output_transfer_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_output_transfer_receipt();

CREATE OR REPLACE FUNCTION accounting.immutable_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Production output transfer receipts are immutable';
END $$;

CREATE TRIGGER immutable_production_output_transfer_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.production_output_transfer_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.immutable_production_output_transfer_receipt();
