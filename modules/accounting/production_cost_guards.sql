CREATE TRIGGER immutable_production_overhead_receipt BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_receipt FOR EACH STATEMENT
EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE TRIGGER immutable_production_overhead_withdrawal BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_withdrawal FOR EACH STATEMENT
EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_production_overhead_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF TG_TABLE_NAME='production_overhead_withdrawal' THEN
    IF EXISTS (SELECT 1 FROM accounting.production_overhead_receipt WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
      RAISE EXCEPTION 'A posted overhead request cannot be withdrawn';
    END IF;
    IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
      OR NEW.month IS DISTINCT FROM to_char((NEW.month||'-01')::date,'YYYY-MM')
      OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
      OR to_char((NEW.command->>'posting_date')::date,'YYYY-MM') IS DISTINCT FROM NEW.month
      OR length(btrim(NEW.actor))<1 OR length(btrim(NEW.reason))<10 THEN
      RAISE EXCEPTION 'Withdrawal must retain the original request identity and reason';
    END IF;
  ELSIF EXISTS (SELECT 1 FROM accounting.production_overhead_withdrawal WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'A withdrawn overhead request cannot be posted';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER production_overhead_withdrawal_decision BEFORE INSERT ON accounting.production_overhead_withdrawal
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_overhead_decision();
CREATE TRIGGER production_overhead_receipt_decision BEFORE INSERT ON accounting.production_overhead_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_overhead_decision();

CREATE OR REPLACE FUNCTION accounting.check_production_overhead_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.production_overhead_receipt%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target := NEW.id; ELSE target := NEW.entry_id; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF e.operation IS DISTINCT FROM 'production_overhead_correction' AND EXISTS (
      SELECT 1 FROM accounting.entry original WHERE original.id=e.correction_of
             AND original.operation IN ('production_overhead','production_overhead_correction')) THEN
    RAISE EXCEPTION 'Production overhead corrections require their dedicated workflow';
  END IF;
  IF e.operation IS DISTINCT FROM 'production_overhead' THEN
    IF TG_TABLE_NAME='production_overhead_receipt' THEN RAISE EXCEPTION 'Invalid production overhead receipt entry'; END IF;
    RETURN NULL;
  END IF;
  SELECT * INTO r FROM accounting.production_overhead_receipt WHERE entry_id=target;
  IF NOT FOUND OR r.organization_id IS DISTINCT FROM e.organization_id
    OR r.actor IS DISTINCT FROM e.actor OR r.month IS DISTINCT FROM to_char(e.posting_date,'YYYY-MM')
    OR e.source IS DISTINCT FROM 'production:overhead:'||e.organization_id||':'||r.month
    OR e.source_version<>1 OR e.rule_version<>'production-overhead-v1' OR e.opening OR e.correction_of IS NOT NULL
    OR r.command->>'request_key' IS DISTINCT FROM r.request_key
    OR r.command->>'expected_review_digest' IS DISTINCT FROM r.review->>'digest'
    OR r.review->'snapshot'->>'organization_id' IS DISTINCT FROM e.organization_id::text
    OR r.review->'snapshot'->>'month' IS DISTINCT FROM r.month
    OR r.command->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR accounting.posting_body_projection(r.posting::jsonb) IS DISTINCT FROM
       accounting.posting_body_projection(accounting.financial_posting_body(target),false) THEN
    RAISE EXCEPTION 'Production overhead requires its matching complete receipt';
  END IF;
  PERFORM accounting.verify_production_overhead(target);
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_production_overhead_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();
CREATE CONSTRAINT TRIGGER complete_production_overhead_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();
CREATE CONSTRAINT TRIGGER complete_production_overhead_receipt AFTER INSERT ON accounting.production_overhead_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_production_overhead_complete();

-- Ledger lines and stored source snapshots are immutable. Independent ID coverage
-- detects every subsequently admitted source line without trusting UI evidence.
CREATE OR REPLACE FUNCTION accounting.assert_production_overhead_current(book integer, closing_month text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_receipt%ROWTYPE; p accounting.policy%ROWTYPE;
  latest accounting.production_overhead_revision%ROWTYPE; applied integer[];
  saved jsonb; settings jsonb; policy_settings jsonb; actual_ids jsonb; expected_ids jsonb; first_day date; last_day date;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  FOR r IN SELECT * FROM accounting.production_overhead_receipt WHERE organization_id=book AND month<=closing_month ORDER BY month LOOP
    first_day := (r.month||'-01')::date;
    last_day := (first_day + interval '1 month - 1 day')::date;
    SELECT * INTO p FROM accounting.policy WHERE organization_id=book AND effective_from<=last_day ORDER BY effective_from DESC LIMIT 1;
    policy_settings := jsonb_build_object(
      'overhead_accounts', p.production_costing::jsonb->'overhead_accounts',
      'wip_account', p.production_costing::jsonb->>'wip_account',
      'finished_goods_account', p.production_costing::jsonb->>'finished_goods_account',
      'pool_dimensions', p.production_costing::jsonb->'pool_dimensions',
      'order_dimension', p.production_costing::jsonb->>'order_dimension',
      'rounding', p.production_costing::jsonb->>'rounding',
      'reference', p.production_costing::jsonb->>'reference'
    );
    SELECT * INTO latest FROM accounting.production_overhead_revision WHERE original_entry_id=r.entry_id ORDER BY sequence DESC LIMIT 1;
    SELECT ARRAY[r.entry_id]||coalesce(array_agg(entry_id) FILTER(WHERE entry_id IS NOT NULL),ARRAY[]::integer[])
      INTO applied FROM accounting.production_overhead_revision WHERE original_entry_id=r.entry_id;
    saved := CASE WHEN latest.id IS NULL THEN r.review::jsonb->'snapshot'->'source'->'snapshot'
      ELSE latest.preview::jsonb->'snapshot'->'reviewed'->'snapshot'->'source'->'snapshot' END;
    settings := saved->'settings';
    IF p.id IS DISTINCT FROM (r.command->'review'->>'policy_id')::integer OR p.effective_from>first_day
      OR policy_settings IS DISTINCT FROM settings THEN
      RAISE EXCEPTION 'Production overhead sources changed or cannot be verified for %; repeat costing before closing', r.month;
    END IF;
    SELECT coalesce(jsonb_agg(l.id ORDER BY l.id),'[]'::jsonb) INTO actual_ids
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=book AND e.posting_date<=last_day AND NOT(e.id=ANY(applied))
        AND l.account_code IN (SELECT jsonb_array_elements_text(settings->'overhead_accounts'||jsonb_build_array(settings->>'wip_account')));
    SELECT coalesce(jsonb_agg((line->>'line_id')::integer ORDER BY (line->>'line_id')::integer),'[]'::jsonb) INTO expected_ids
      FROM jsonb_array_elements(saved->'lines') line;
    IF actual_ids IS DISTINCT FROM expected_ids THEN
      RAISE EXCEPTION 'Production overhead sources changed or cannot be verified for %; repeat costing before closing', r.month;
    END IF;
  END LOOP;
END $$;
CREATE OR REPLACE FUNCTION accounting.guard_production_cost_close() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.closed THEN PERFORM accounting.assert_production_overhead_current(NEW.organization_id,NEW.month); END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER costing_before_period_close BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.guard_production_cost_close();
