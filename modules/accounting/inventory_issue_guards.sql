CREATE OR REPLACE FUNCTION accounting.reject_inventory_issue_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Inventory issue receipt is immutable';
END $$;
CREATE TRIGGER immutable_inventory_issue_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.inventory_issue_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inventory_issue_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_inventory_issue_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id = NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_issue' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.digest IS DISTINCT FROM NEW.digest
    OR NEW.command->>'source' IS DISTINCT FROM e.source
    OR (NEW.command->>'source_version')::integer IS DISTINCT FROM e.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.cost->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.cost->>'basis_digest' IS NULL THEN
    RAISE EXCEPTION 'Inventory issue receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_issue_receipt BEFORE INSERT ON accounting.inventory_issue_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_issue_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.reject_inventory_sale_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Inventory sale receipt is immutable';
END $$;
CREATE TRIGGER immutable_inventory_sale_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.inventory_sale_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inventory_sale_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_inventory_sale_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id = NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_sale' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.rule_version NOT LIKE 'sale-v1:%' OR e.digest IS DISTINCT FROM NEW.digest
    OR NEW.command->>'source' IS DISTINCT FROM e.source
    OR (NEW.command->>'source_version')::integer IS DISTINCT FROM e.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.cost->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.cost->>'basis_digest' IS NULL THEN
    RAISE EXCEPTION 'Inventory sale receipt does not match its ledger entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_sale_receipt BEFORE INSERT ON accounting.inventory_sale_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_sale_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.check_inventory_sale_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.inventory_sale_receipt%ROWTYPE;
        l accounting.line%ROWTYPE; expected jsonb; pos integer:=0;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_sale' OR e.rule_version NOT LIKE 'sale-v1:%' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.inventory_sale_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Inventory sale requires its complete receipt'; END IF;
  IF r.posting->>'document_date' IS DISTINCT FROM e.document_date::text
    OR r.posting->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR r.posting->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR r.posting->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR r.posting->>'explanation' IS DISTINCT FROM e.explanation
    OR e.opening OR e.correction_of IS NOT NULL
    OR jsonb_typeof(r.posting::jsonb->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Inventory sale posting metadata differs from ledger';
  END IF;
  FOR l IN SELECT * FROM accounting.line WHERE entry_id=target ORDER BY id LOOP
    expected:=r.posting::jsonb->'lines'->pos;
    IF expected IS NULL OR expected->>'account' IS DISTINCT FROM l.account_code
      OR expected->>'side' IS DISTINCT FROM l.side
      OR (expected->>'amount')::numeric IS DISTINCT FROM l.amount
      OR (expected->>'quantity')::numeric IS DISTINCT FROM l.quantity
      OR expected->'dimensions' IS DISTINCT FROM l.dimensions::jsonb
      OR expected->>'currency' IS DISTINCT FROM 'BYN' OR l.currency<>'BYN'
      OR expected->>'original_amount' IS NOT NULL OR l.original_amount IS NOT NULL
      OR expected->>'rate' IS NOT NULL OR l.rate IS NOT NULL
      OR expected->>'rate_scale' IS NOT NULL OR l.rate_scale IS NOT NULL
      OR expected->>'rate_date' IS NOT NULL OR l.rate_date IS NOT NULL
      OR expected->>'rate_source' IS NOT NULL OR l.rate_source IS NOT NULL
      OR expected->>'cash_activity' IS NOT NULL OR l.cash_activity IS NOT NULL OR l.cash THEN
      RAISE EXCEPTION 'Inventory sale posting lines differ from ledger';
    END IF;
    pos:=pos+1;
  END LOOP;
  IF pos=0 OR pos<>jsonb_array_length(r.posting::jsonb->'lines') THEN
    RAISE EXCEPTION 'Inventory sale posting lines are incomplete';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_inventory_sale_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();
CREATE CONSTRAINT TRIGGER complete_inventory_sale_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();
CREATE CONSTRAINT TRIGGER complete_inventory_sale_receipt AFTER INSERT ON accounting.inventory_sale_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_sale_complete();
