ALTER TABLE accounting.late_cost_receipt ADD CONSTRAINT fk_late_cost_primary
FOREIGN KEY (expense_id) REFERENCES procurement.additional_expense_document(id);

CREATE OR REPLACE FUNCTION accounting.reject_late_cost_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Late cost receipt is immutable';
END $$;
CREATE TRIGGER immutable_late_cost_receipt BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.late_cost_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_late_cost_receipt_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_late_cost_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; original jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id IS DISTINCT FROM NEW.organization_id
    OR e.operation IS DISTINCT FROM 'inventory_late_cost' OR e.actor IS DISTINCT FROM NEW.actor
    OR e.digest IS DISTINCT FROM NEW.digest OR e.rule_version NOT IN ('late-cost-byn-v1', 'late-cost-fx-v1')
    OR e.source IS DISTINCT FROM 'procurement:additional-expense:' || NEW.expense_id::text
    OR e.source_version IS DISTINCT FROM NEW.source_version
    OR NEW.posting->>'source' IS DISTINCT FROM e.source
    OR NEW.posting->>'source_version' IS DISTINCT FROM e.source_version::text
    OR NEW.posting->>'operation' IS DISTINCT FROM e.operation
    OR NEW.posting->>'rule_version' IS DISTINCT FROM e.rule_version
    OR NEW.calculation->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.calculation->>'expense_id' IS DISTINCT FROM NEW.expense_id::text
    OR NEW.calculation->>'source_version' IS DISTINCT FROM NEW.source_version::text
    OR NEW.calculation::jsonb->'source_movements_verified' IS DISTINCT FROM 'true'::jsonb
    OR NEW.calculation::jsonb->'posted' IS DISTINCT FROM 'false'::jsonb
    OR coalesce(NEW.calculation->>'basis_digest', '') !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'Late cost receipt does not match its ledger entry';
  END IF;
  SELECT r.document::jsonb INTO original FROM procurement.additional_expense_revision r
    JOIN procurement.additional_expense_document d ON d.id=r.expense_id
    WHERE r.expense_id=NEW.expense_id AND r.version=NEW.source_version AND d.organization_id=NEW.organization_id;
  IF NOT FOUND OR NEW.calculation::jsonb#>'{history,document}' IS DISTINCT FROM original THEN
    RAISE EXCEPTION 'Late cost receipt does not match its primary document';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_late_cost_receipt BEFORE INSERT ON accounting.late_cost_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_late_cost_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.verify_late_cost_lines(target integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
        l accounting.line%ROWTYPE; expected jsonb; pos integer:=0;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Late cost line verification requires a receipt'; END IF;
  IF r.posting->>'document_date' IS DISTINCT FROM e.document_date::text
    OR r.posting->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR r.posting->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR r.posting->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR r.posting->>'explanation' IS DISTINCT FROM e.explanation
    OR e.opening OR e.correction_of IS NOT NULL
    OR jsonb_typeof(r.posting::jsonb->'lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Late cost posting metadata differs from ledger';
  END IF;
  FOR l IN SELECT * FROM accounting.line WHERE entry_id=target ORDER BY id LOOP
    expected:=r.posting::jsonb->'lines'->pos;
    IF expected IS NULL OR expected->>'account' IS DISTINCT FROM l.account_code
      OR expected->>'side' IS DISTINCT FROM l.side
      OR (expected->>'amount')::numeric IS DISTINCT FROM l.amount
      OR expected->'dimensions' IS DISTINCT FROM l.dimensions::jsonb
      OR expected->>'currency' IS DISTINCT FROM 'BYN' OR l.currency<>'BYN'
      OR expected->>'quantity' IS NOT NULL OR l.quantity IS NOT NULL
      OR expected->>'original_amount' IS NOT NULL OR l.original_amount IS NOT NULL
      OR expected->>'rate' IS NOT NULL OR l.rate IS NOT NULL
      OR expected->>'rate_scale' IS NOT NULL OR l.rate_scale IS NOT NULL
      OR expected->>'rate_date' IS NOT NULL OR l.rate_date IS NOT NULL
      OR expected->>'rate_source' IS NOT NULL OR l.rate_source IS NOT NULL
      OR expected->>'cash_activity' IS NOT NULL OR l.cash_activity IS NOT NULL OR l.cash THEN
      RAISE EXCEPTION 'Late cost posting lines differ from ledger';
    END IF;
    pos:=pos+1;
  END LOOP;
  IF pos=0 OR pos<>jsonb_array_length(r.posting::jsonb->'lines') THEN
    RAISE EXCEPTION 'Late cost posting lines are incomplete';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.check_late_cost_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'inventory_late_cost' THEN RETURN NULL; END IF;
  SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
  IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM accounting.source_control c
    WHERE c.organization_id=e.organization_id AND c.source=e.source AND c.version=e.source_version AND c.entry_id=e.id) THEN
    RAISE EXCEPTION 'Late cost entry requires its complete receipt and source control';
  END IF;
  PERFORM procurement.check_additional_expense(r.expense_id);
  PERFORM accounting.verify_late_cost_lines(target);
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_late_cost_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();
CREATE CONSTRAINT TRIGGER complete_late_cost_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();
CREATE CONSTRAINT TRIGGER complete_late_cost_receipt AFTER INSERT ON accounting.late_cost_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_late_cost_complete();

CREATE OR REPLACE FUNCTION accounting.reject_posted_late_cost_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.late_cost_receipt WHERE expense_id=NEW.expense_id) THEN
    RAISE EXCEPTION 'Posted late expense requires a separate correction workflow';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER preserve_posted_late_cost_source BEFORE INSERT ON procurement.additional_expense_revision
FOR EACH ROW EXECUTE FUNCTION accounting.reject_posted_late_cost_revision();
