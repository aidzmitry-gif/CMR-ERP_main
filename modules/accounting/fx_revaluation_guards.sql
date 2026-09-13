-- Unallocated proposal guard for the reviewed currency-revaluation package.
-- Production registration still requires the operator-assigned migration.
CREATE OR REPLACE FUNCTION accounting.reject_fx_revaluation_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'FX revaluation receipts are immutable';
END $$;

CREATE TRIGGER immutable_fx_revaluation_receipt
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.fx_revaluation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fx_revaluation_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_fx_revaluation_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; p accounting.period%ROWTYPE;
BEGIN
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'policy_id' IS NULL
     OR NEW.command->>'expected_generation' IS NULL
     OR NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
     OR NEW.snapshot->>'month' IS DISTINCT FROM NEW.month
     OR NEW.snapshot->>'source_version' IS DISTINCT FROM NEW.source_version::text
     OR NEW.command_digest IS DISTINCT FROM accounting.financial_sha(NEW.command::jsonb)
     OR NEW.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object(
          'organization_id',NEW.organization_id,'request_key',NEW.request_key,
          'kind','fx_revaluation','month',NEW.month,'source_version',NEW.source_version,'command',NEW.command,
          'command_digest',NEW.command_digest,'snapshot',NEW.snapshot,'entry_id',NEW.entry_id,
          'actor',NEW.actor)) THEN
    RAISE EXCEPTION 'FX revaluation receipt identity or digest is invalid';
  END IF;
  SELECT * INTO p FROM accounting.period WHERE organization_id=NEW.organization_id AND month=NEW.month;
  IF p.closed THEN RAISE EXCEPTION 'FX revaluation cannot be recorded in a closed period'; END IF;
  IF NEW.entry_id IS NULL THEN RETURN NEW; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.source IS DISTINCT FROM 'accounting:fx-revaluation:'||NEW.organization_id||':'||NEW.month
     OR e.source_version IS DISTINCT FROM NEW.source_version
     OR e.operation IS DISTINCT FROM 'fx_revaluation'
     OR e.actor IS DISTINCT FROM NEW.actor
     OR e.posting_date IS DISTINCT FROM (NEW.command->>'posting_date')::date
     OR e.policy_id IS DISTINCT FROM (NEW.command->>'policy_id')::integer
     OR NEW.snapshot->>'digest' IS DISTINCT FROM e.digest THEN
    RAISE EXCEPTION 'FX revaluation receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER guard_fx_revaluation_receipt
AFTER INSERT ON accounting.fx_revaluation_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_fx_revaluation_receipt();
