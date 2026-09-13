CREATE FUNCTION accounting.guard_production_material_issue_receipt_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE issue_row wms.production_material_issue%ROWTYPE; m wms.stock_movement%ROWTYPE;
        e accounting.entry%ROWTYPE; p accounting.policy%ROWTYPE; source_request_key text;
        debit accounting.line%ROWTYPE; credit accounting.line%ROWTYPE;
BEGIN
  IF NEW.command::jsonb->>'source' NOT LIKE 'production:material:%' THEN RETURN NEW; END IF;
  source_request_key := split_part(NEW.command::jsonb->>'source', ':', 4);
  SELECT issue.* INTO issue_row FROM wms.production_material_issue AS issue
    WHERE issue.organization_id=NEW.organization_id AND issue.request_key=source_request_key FOR UPDATE;
  SELECT * INTO m FROM wms.stock_movement WHERE id=issue_row.movement_id;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO p FROM accounting.policy WHERE id=e.policy_id;
  IF NOT FOUND OR issue_row.id IS NULL OR m.id IS NULL OR e.id IS NULL OR p.id IS NULL
    OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_issue'
    OR e.source IS DISTINCT FROM NEW.command::jsonb->>'source'
    OR e.source_version IS DISTINCT FROM 1
    OR e.rule_version NOT LIKE 'inventory-issue-v2:%'
    OR e.operation_date IS DISTINCT FROM issue_row.operation_date
    OR NEW.command::jsonb->>'operation_date' IS DISTINCT FROM issue_row.operation_date::text
    OR NEW.command::jsonb->>'order_id' IS NOT NULL
    OR NEW.command::jsonb->>'warehouse' IS DISTINCT FROM m.warehouse
    OR NEW.command::jsonb->>'sku' IS DISTINCT FROM m.sku_code
    OR NEW.command::jsonb->>'lot' IS DISTINCT FROM m.batch_ref
    OR (NEW.command::jsonb->>'quantity')::numeric IS DISTINCT FROM m.qty
    OR m.kind IS DISTINCT FROM 'out' OR m.reason IS DISTINCT FROM 'production_issue'
    OR NEW.command::jsonb->>'expense_account' IS DISTINCT FROM p.production_costing::jsonb->>'wip_account'
    OR jsonb_typeof(NEW.command::jsonb->'expense_dimensions') IS DISTINCT FROM 'object'
    OR NOT (NEW.command::jsonb->'expense_dimensions' ? 'department')
    OR NOT (NEW.command::jsonb->'expense_dimensions' ? 'order') THEN
    RAISE EXCEPTION 'Production material issue receipt is not bound to its reviewed WMS source';
  END IF;
  SELECT * INTO debit FROM accounting.line WHERE entry_id=e.id AND side='debit';
  SELECT * INTO credit FROM accounting.line WHERE entry_id=e.id AND side='credit';
  IF debit.id IS NULL OR credit.id IS NULL
    OR (SELECT count(*) FROM accounting.line WHERE entry_id=e.id)<>2
    OR debit.account_code IS DISTINCT FROM NEW.command::jsonb->>'expense_account'
    OR debit.dimensions::jsonb IS DISTINCT FROM NEW.command::jsonb->'expense_dimensions'
    OR credit.account_code IS DISTINCT FROM NEW.command::jsonb->>'account'
    OR credit.quantity IS DISTINCT FROM (NEW.command::jsonb->>'quantity')::numeric
    OR credit.dimensions->>'warehouse' IS DISTINCT FROM m.warehouse
    OR credit.dimensions->>'sku' IS DISTINCT FROM m.sku_code
    OR credit.dimensions->>'lot' IS DISTINCT FROM m.batch_ref
    OR debit.amount IS DISTINCT FROM credit.amount
    OR NEW.cost::jsonb->>'issue_cost_byn' IS NULL
    OR (NEW.cost::jsonb->>'issue_cost_byn')::numeric IS DISTINCT FROM credit.amount
    OR NEW.cost::jsonb->'inventory_dimensions' IS DISTINCT FROM credit.dimensions::jsonb THEN
    RAISE EXCEPTION 'Production material issue ledger lines differ from its reviewed source';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_production_material_issue_receipt
BEFORE INSERT ON accounting.inventory_issue_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_material_issue_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.check_production_material_issue_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.inventory_issue_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_issue' OR e.source NOT LIKE 'production:material:%' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.inventory_issue_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Production material issue requires its complete source receipt'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_production_material_issue_entry
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_material_issue_complete();
CREATE CONSTRAINT TRIGGER complete_production_material_issue_receipt
AFTER INSERT ON accounting.inventory_issue_receipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_production_material_issue_complete();
