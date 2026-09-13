-- Proposal-only guards for the fixed-asset register and straight-line
-- depreciation receipt.  Allocate a migration revision only after review.

CREATE OR REPLACE FUNCTION accounting.reject_fixed_asset_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Fixed-asset history is immutable: %', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER fixed_asset_register_immutable
BEFORE UPDATE OR DELETE ON accounting.fixed_asset_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_register_no_truncate
BEFORE TRUNCATE ON accounting.fixed_asset_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_depreciation_immutable
BEFORE UPDATE OR DELETE ON accounting.fixed_asset_depreciation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE TRIGGER fixed_asset_depreciation_no_truncate
BEFORE TRUNCATE ON accounting.fixed_asset_depreciation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_fixed_asset_mutation();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE; p accounting.policy%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id=NEW.source_entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id=NEW.source_line_id;
  SELECT * INTO STRICT p FROM accounting.policy WHERE id=e.policy_id;
  IF e.organization_id IS DISTINCT FROM NEW.organization_id
     OR l.entry_id IS DISTINCT FROM e.id
     OR e.digest IS DISTINCT FROM NEW.source_digest
     OR l.account_code IS DISTINCT FROM NEW.asset_account
     OR l.side IS DISTINCT FROM 'debit'
     OR l.amount IS DISTINCT FROM NEW.cost
     OR l.currency IS DISTINCT FROM 'BYN'
     OR split_part(NEW.asset_account, '.', 1) <> '01'
     OR split_part(NEW.accumulated_account, '.', 1) <> '02'
     OR p.depreciation_method IS DISTINCT FROM NEW.depreciation_method THEN
    RAISE EXCEPTION 'Fixed-asset register source does not match its posted acquisition';
  END IF;
  IF NEW.commissioning_date < NEW.acquisition_date
     OR NEW.depreciation_start < NEW.commissioning_date
     OR NEW.residual_value < 0 OR NEW.residual_value > NEW.cost
     OR NEW.useful_life_months <= 0 THEN
    RAISE EXCEPTION 'Invalid fixed-asset dates or cost bounds';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER fixed_asset_register_source_consistency
AFTER INSERT ON accounting.fixed_asset_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_fixed_asset_register_source();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_depreciation_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; a accounting.fixed_asset_register_entry%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO STRICT a FROM accounting.fixed_asset_register_entry WHERE id=NEW.asset_id;
  IF e.organization_id IS DISTINCT FROM NEW.organization_id
     OR a.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.operation IS DISTINCT FROM 'fixed_asset_depreciation'
     OR e.source IS DISTINCT FROM 'fixed-asset:depreciation:'||NEW.organization_id||':'||a.asset_key||':'||NEW.month
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'month' IS DISTINCT FROM NEW.month
     OR NEW.calculation->>'method' IS DISTINCT FROM 'straight_line' THEN
    RAISE EXCEPTION 'Fixed-asset depreciation receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER fixed_asset_depreciation_source_consistency
BEFORE INSERT ON accounting.fixed_asset_depreciation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_receipt();

CREATE OR REPLACE FUNCTION accounting.check_fixed_asset_depreciation_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'fixed_asset_depreciation' THEN RETURN NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM accounting.fixed_asset_depreciation_receipt WHERE entry_id=target) THEN
    RAISE EXCEPTION 'Fixed-asset depreciation requires its complete receipt';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER fixed_asset_depreciation_complete_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_complete();

CREATE CONSTRAINT TRIGGER fixed_asset_depreciation_complete_receipt
AFTER INSERT ON accounting.fixed_asset_depreciation_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_fixed_asset_depreciation_complete();
