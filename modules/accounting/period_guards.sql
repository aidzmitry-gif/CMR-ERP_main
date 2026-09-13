-- Structural period integrity; transition provenance and exact generation
-- arithmetic are separate requirements before financial confirmation opens.
ALTER TABLE accounting.inbox ADD CONSTRAINT inbox_canonical_month
CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$' AND left(month,4)<>'0000');
ALTER TABLE accounting.source_control ADD CONSTRAINT source_control_canonical_month
CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$' AND left(month,4)<>'0000');
CREATE OR REPLACE FUNCTION accounting.guard_inbox_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.entry_id IS NOT NULL THEN
      RAISE EXCEPTION 'Inbox must start pending';
    END IF;
  ELSE
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.event_key IS DISTINCT FROM OLD.event_key OR NEW.month IS DISTINCT FROM OLD.month
       OR NEW.payload::text IS DISTINCT FROM OLD.payload::text THEN
      RAISE EXCEPTION 'Inbox source identity is immutable';
    END IF;
    IF OLD.entry_id IS NOT NULL AND (NEW.entry_id IS DISTINCT FROM OLD.entry_id OR NEW.error IS DISTINCT FROM OLD.error) THEN
      RAISE EXCEPTION 'Resolved inbox is immutable';
    END IF;
  END IF;
  IF NEW.entry_id IS NOT NULL AND (NEW.error IS NOT NULL OR NOT EXISTS (
      SELECT 1 FROM accounting.entry e WHERE e.id=NEW.entry_id AND e.organization_id=NEW.organization_id
        AND to_char(e.posting_date,'YYYY-MM')=NEW.month
        AND e.source=accounting.posting_text(NEW.payload->>'source')
        AND e.source_version=accounting.posting_integer_value(NEW.payload::jsonb->'source_version')
        AND e.operation=accounting.posting_text(NEW.payload->>'operation'))) THEN
    RAISE EXCEPTION 'Inbox resolution requires its matching source entry';
  END IF;
  IF NEW.entry_id IS NOT NULL THEN
    PERFORM accounting.validate_inbox_decimal_tokens(NEW.payload);
  END IF;
  IF NEW.entry_id IS NOT NULL AND accounting.posting_body_projection(NEW.payload::jsonb)
      IS DISTINCT FROM accounting.posting_body_projection(accounting.financial_posting_body(NEW.entry_id),false) THEN
    RAISE EXCEPTION 'Inbox posting body differs from the posted entry';
  END IF;
  IF NEW.entry_id IS NOT NULL AND (SELECT digest FROM accounting.entry WHERE id=NEW.entry_id)
      IS DISTINCT FROM accounting.financial_sha(accounting.inbox_replay_model(NEW.payload)) THEN
    RAISE EXCEPTION 'Inbox posting body replay digest differs from the posted entry';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_inbox_identity BEFORE INSERT OR UPDATE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inbox_identity();
CREATE TRIGGER no_delete_inbox BEFORE DELETE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_inbox BEFORE TRUNCATE ON accounting.inbox
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.guard_period_structure() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE required_steps text[]:=ARRAY['documents','bank','settlements','stock','costing',
  'depreciation','fx','tax','financial_result','trial_balance'];
  first_day date; start_policy accounting.policy;
BEGIN
  IF NEW.month !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' OR left(NEW.month,4)='0000'
     OR NEW.generation<0 OR (NEW.closed AND NEW.closed_generation IS DISTINCT FROM NEW.generation)
     OR (NOT NEW.closed AND NEW.closed_generation IS NOT NULL)
     OR jsonb_typeof(NEW.evidence::jsonb) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Invalid accounting period structure';
  END IF;
  IF NEW.closed AND (
      NOT (NEW.evidence::jsonb ?& required_steps)
      OR NEW.evidence::jsonb-required_steps<>'{}'::jsonb
      OR EXISTS (SELECT 1 FROM jsonb_each(NEW.evidence::jsonb) AS item(key,value)
        WHERE jsonb_typeof(value)<>'string' OR length(value#>>'{}') NOT BETWEEN 1 AND 1000
          OR accounting.posting_text(translate(value#>>'{}',chr(28)||chr(29)||chr(30)||chr(31),'    '))='')
  ) THEN
    RAISE EXCEPTION 'Closing evidence requires every control step with a nonempty bounded string';
  END IF;
  IF NEW.closed AND EXISTS (SELECT 1 FROM accounting.period p
      WHERE p.organization_id=NEW.organization_id AND p.month<NEW.month AND NOT p.closed) THEN
    RAISE EXCEPTION 'Close earlier periods first';
  END IF;
  IF NEW.closed THEN
    first_day:=(NEW.month||'-01')::date;
    SELECT * INTO start_policy FROM accounting.policy
      WHERE organization_id=NEW.organization_id AND effective_from<=first_day
      ORDER BY effective_from DESC LIMIT 1;
    IF start_policy.id IS NULL OR NOT start_policy.normative_verified OR EXISTS (
        SELECT 1 FROM accounting.policy q WHERE q.organization_id=NEW.organization_id
          AND q.effective_from>first_day AND q.effective_from<first_day+INTERVAL '1 month'
          AND NOT q.normative_verified) THEN
      RAISE EXCEPTION 'Normative basis must be verified before final closing';
    END IF;
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.closed OR NEW.generation<>0 OR NEW.closed_generation IS NOT NULL
       OR NEW.evidence::jsonb<>'{}'::jsonb THEN
      RAISE EXCEPTION 'Accounting period must start open with generation zero';
    END IF;
  ELSE
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.month IS DISTINCT FROM OLD.month THEN
      RAISE EXCEPTION 'Accounting period identity is immutable';
    END IF;
    IF NEW.generation<OLD.generation THEN
      RAISE EXCEPTION 'Accounting period generation cannot decrease';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER valid_period_structure BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_structure();
CREATE TRIGGER no_delete_period BEFORE DELETE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period BEFORE TRUNCATE ON accounting.period
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

-- SQL-originated transition evidence. Validators must inspect the complete
-- chain, not infer transitions solely from the final closed flag.
CREATE TABLE accounting.period_change (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  root_transaction bigint NOT NULL,
  organization_id integer NOT NULL REFERENCES accounting.organization(id),
  period_id integer NOT NULL REFERENCES accounting.period(id),
  before_row jsonb,
  after_row jsonb NOT NULL
);
CREATE INDEX period_change_root_org ON accounting.period_change(root_transaction,organization_id,id);
CREATE OR REPLACE FUNCTION accounting.guard_period_change_origin() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current()
     OR NOT EXISTS (SELECT 1 FROM accounting.period p
       WHERE p.id=NEW.period_id AND p.organization_id=NEW.organization_id
         AND to_jsonb(p)=NEW.after_row) THEN
    RAISE EXCEPTION 'Period change proof must originate from its period trigger';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_period_change BEFORE INSERT ON accounting.period_change
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_change_origin();
CREATE TRIGGER immutable_period_change BEFORE UPDATE OR DELETE ON accounting.period_change
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period_change BEFORE TRUNCATE ON accounting.period_change
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.record_period_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' AND to_jsonb(OLD)=to_jsonb(NEW) THEN RETURN NULL; END IF;
  INSERT INTO accounting.period_change(root_transaction,organization_id,period_id,before_row,after_row)
  VALUES(txid_current(),NEW.organization_id,NEW.id,
    CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,to_jsonb(NEW));
  RETURN NULL;
END $$;
CREATE TRIGGER record_period_change AFTER INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.record_period_change();

CREATE OR REPLACE FUNCTION accounting.validate_period_change_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous jsonb; current_change record; final_row jsonb; flips integer:=0; seen boolean:=false;
BEGIN
  FOR current_change IN SELECT before_row,after_row FROM accounting.period_change
    WHERE root_transaction=NEW.root_transaction AND organization_id=NEW.organization_id
      AND period_id=NEW.period_id ORDER BY id LOOP
    IF seen AND current_change.before_row IS DISTINCT FROM previous THEN
      RAISE EXCEPTION 'Accounting period change chain is discontinuous';
    END IF;
    IF current_change.before_row IS NOT NULL AND
       current_change.before_row->'closed' IS DISTINCT FROM current_change.after_row->'closed' THEN
      flips:=flips+1;
    END IF;
    previous:=current_change.after_row;
    seen:=true;
  END LOOP;
  IF flips>1 THEN
    RAISE EXCEPTION 'Accounting period cannot change closed state twice in one transaction';
  END IF;
  SELECT to_jsonb(p) INTO final_row FROM accounting.period p WHERE p.id=NEW.period_id;
  IF final_row IS DISTINCT FROM previous THEN
    RAISE EXCEPTION 'Accounting period state differs from its change journal';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER valid_period_change_chain AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.validate_period_change_chain();

CREATE TABLE accounting.period_root_basis (
  root_transaction bigint NOT NULL,
  organization_id integer NOT NULL REFERENCES accounting.organization(id),
  organization_generation bigint NOT NULL,
  periods_before jsonb NOT NULL,
  active_closes_before jsonb NOT NULL,
  PRIMARY KEY(root_transaction,organization_id)
);
CREATE OR REPLACE FUNCTION accounting.guard_period_basis_origin() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF pg_trigger_depth()<>2 OR NEW.root_transaction<>txid_current() THEN
    RAISE EXCEPTION 'Period basis must be captured by a guarded write';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER generated_period_basis BEFORE INSERT ON accounting.period_root_basis
FOR EACH ROW EXECUTE FUNCTION accounting.guard_period_basis_origin();
CREATE TRIGGER immutable_period_basis BEFORE UPDATE OR DELETE ON accounting.period_root_basis
FOR EACH ROW EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER no_truncate_period_basis BEFORE TRUNCATE ON accounting.period_root_basis
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.capture_period_basis() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; org_generation bigint; periods jsonb; closes jsonb;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION 'Accounting guarded writes require READ COMMITTED isolation';
  END IF;
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  SELECT generation INTO org_generation FROM accounting.organization WHERE id=org_key FOR UPDATE;
  IF TG_TABLE_NAME='period' AND TG_OP='INSERT' THEN
    IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org_key AND closed AND month>NEW.month) THEN
      RAISE EXCEPTION 'Cannot create an open period before a closed period';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period_root_basis
      WHERE root_transaction=txid_current() AND organization_id=org_key) THEN RETURN NEW; END IF;
  -- Read after acquiring the organization lock, before the guarded row changes.
  SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.month),'[]'::jsonb) INTO periods
    FROM accounting.period p WHERE p.organization_id=org_key;
  SELECT COALESCE(jsonb_agg(jsonb_build_object('id',c.id,'month',c.month,
      'closed_generation',c.snapshot::jsonb->'closed_generation') ORDER BY c.month,c.id),'[]'::jsonb)
    INTO closes FROM accounting.financial_close_receipt c
    WHERE c.organization_id=org_key AND NOT EXISTS
      (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.close_receipt_id=c.id);
  INSERT INTO accounting.period_root_basis VALUES(txid_current(),org_key,org_generation,periods,closes);
  RETURN NEW;
END $$;
-- Names ensure capture precedes other row-level validation/effects.
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE UPDATE OF generation ON accounting.organization
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.financial_close_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.financial_reopen_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT OR UPDATE ON accounting.inbox
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();

CREATE OR REPLACE FUNCTION accounting.validate_reopen_periods() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; r accounting.financial_reopen_receipt; b accounting.period_root_basis;
  original jsonb; current_period accounting.period; expected_before jsonb; expected_after jsonb;
  entry_count bigint; period_entries bigint; current_org_generation bigint;
  reopened_from text;
BEGIN
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  SELECT q.* INTO r FROM accounting.financial_reopen_receipt q
    JOIN accounting.financial_receipt_transaction t ON t.kind='reopen' AND t.receipt_id=q.id
    WHERE t.root_transaction=txid_current() AND q.organization_id=org_key;
  SELECT * INTO b FROM accounting.period_root_basis
    WHERE root_transaction=txid_current() AND organization_id=org_key;
  SELECT min(after_row->>'month') INTO reopened_from FROM accounting.period_change
    WHERE root_transaction=txid_current() AND organization_id=org_key
      AND before_row->'closed'='true'::jsonb AND after_row->'closed'='false'::jsonb;
  IF reopened_from IS NOT NULL THEN
    IF b.organization_id IS NULL THEN RAISE EXCEPTION 'Reopening requires its original period basis'; END IF;
    IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org_key AND month>=reopened_from
        AND (closed OR closed_generation IS NOT NULL OR evidence::jsonb<>'{}'::jsonb)) THEN
      RAISE EXCEPTION 'Reopening must clear every later period';
    END IF;
    IF r.id IS NULL AND (
        EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) c WHERE c->>'month'>=reopened_from)
        OR EXISTS (SELECT 1 FROM accounting.financial_close_receipt c
          WHERE c.organization_id=org_key AND c.month>=reopened_from
            AND NOT EXISTS (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.close_receipt_id=c.id))) THEN
      RAISE EXCEPTION 'Financial reopening requires a dedicated current transaction receipt';
    END IF;
    IF r.id IS NULL AND EXISTS (SELECT 1 FROM accounting.period_change c
        WHERE c.root_transaction=txid_current() AND c.organization_id=org_key
          AND c.before_row->'closed'='true'::jsonb AND c.after_row->'closed'='false'::jsonb
          AND c.before_row->'generation' IS DISTINCT FROM c.after_row->'generation') THEN
      RAISE EXCEPTION 'Manual reopening cannot increase the period generation';
    END IF;
  END IF;
  IF r.id IS NULL THEN RETURN NULL; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) x
      WHERE x->>'month'>=r.from_month AND NOT EXISTS
        (SELECT 1 FROM accounting.financial_reopen_item i WHERE i.reopen_receipt_id=r.id
           AND to_jsonb(i.close_receipt_id)=x->'id')) THEN
    RAISE EXCEPTION 'Reopening must include every active close';
  END IF;
  IF b.organization_id IS NULL OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(b.periods_before) p
      WHERE p->>'month'=r.from_month AND p->'closed'='true'::jsonb) THEN
    RAISE EXCEPTION 'Reopening requires an initially closed period';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) c
      LEFT JOIN LATERAL (SELECT p FROM jsonb_array_elements(b.periods_before) p
        WHERE p->>'month'=c->>'month') x ON true
      WHERE c->>'month'>=r.from_month AND
        (x.p IS NULL OR x.p->'closed' IS DISTINCT FROM 'true'::jsonb
          OR c->'closed_generation' IS DISTINCT FROM x.p->'closed_generation')) THEN
    RAISE EXCEPTION 'Reopening close receipt generation is stale';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
      WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
        AND NOT EXISTS (SELECT 1 FROM accounting.financial_reopen_item i
          WHERE i.reopen_receipt_id=r.id AND e.id IN (i.monthly_entry_id,i.annual_entry_id))) THEN
    RAISE EXCEPTION 'Reopening transaction contains unrelated entries';
  END IF;
  SELECT count(*) INTO entry_count FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
    WHERE t.root_transaction=txid_current() AND e.organization_id=org_key;
  SELECT generation INTO current_org_generation FROM accounting.organization WHERE id=org_key;
  IF current_org_generation<>b.organization_generation+1+entry_count THEN
    RAISE EXCEPTION 'Reopening organization generation mismatch';
  END IF;
  IF (SELECT count(*) FROM accounting.period WHERE organization_id=org_key)<>jsonb_array_length(b.periods_before) THEN
    RAISE EXCEPTION 'Reopening cannot change the set of periods';
  END IF;
  FOR original IN SELECT value FROM jsonb_array_elements(b.periods_before) LOOP
    SELECT * INTO current_period FROM accounting.period WHERE id=(original->>'id')::integer;
    IF original->>'month'<r.from_month THEN
      IF to_jsonb(current_period) IS DISTINCT FROM original THEN
        RAISE EXCEPTION 'Reopening changed an earlier period';
      END IF;
    ELSE
      SELECT count(*) INTO period_entries FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
        WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
          AND to_char(e.posting_date,'YYYY-MM')<=original->>'month';
      IF current_period.closed OR current_period.closed_generation IS NOT NULL
         OR current_period.evidence::jsonb<>'{}'::jsonb
         OR current_period.generation<>(original->>'generation')::bigint+1+period_entries THEN
        RAISE EXCEPTION 'Reopening dependent period generation or state mismatch';
      END IF;
    END IF;
  END LOOP;
  SELECT jsonb_agg(jsonb_build_object('month',p->'month','generation',p->'generation','closed',p->'closed') ORDER BY p->>'month')
    INTO expected_before FROM jsonb_array_elements(b.periods_before) p WHERE p->>'month'>=r.from_month;
  SELECT jsonb_agg(jsonb_build_object('month',p.month,'generation',p.generation,'closed',p.closed) ORDER BY p.month)
    INTO expected_after FROM accounting.period p WHERE p.organization_id=org_key AND p.month>=r.from_month;
  IF r.snapshot::jsonb->'periods_before' IS DISTINCT FROM expected_before
     OR r.snapshot::jsonb->'periods_after' IS DISTINCT FROM expected_after THEN
    RAISE EXCEPTION 'Reopening period snapshots mismatch';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER reopen_period_basis_check AFTER INSERT ON accounting.period_root_basis
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_period_change_check AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_period_receipt_check AFTER INSERT ON accounting.financial_reopen_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER reopen_organization_check AFTER UPDATE ON accounting.organization
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();
CREATE CONSTRAINT TRIGGER z_reopen_entry_check AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_reopen_periods();

CREATE OR REPLACE FUNCTION accounting.validate_close_periods() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE org_key integer; r accounting.financial_close_receipt; b accounting.period_root_basis;
  original jsonb; target_before jsonb; p accounting.period; k bigint; initial_generation bigint;
  new_target integer; final_org bigint;
BEGIN
  IF TG_TABLE_NAME='organization' THEN org_key:=NEW.id;
  ELSE org_key:=NEW.organization_id; END IF;
  -- Completeness applies to every open-to-closed transition, including the
  -- manual path without a financial transfer receipt. Only this root's
  -- transitions are checked: a later delivery remains a durable pending item.
  IF EXISTS (
    SELECT 1 FROM accounting.period_change c
    WHERE c.root_transaction=txid_current() AND c.organization_id=org_key
      AND c.before_row->'closed'='false'::jsonb AND c.after_row->'closed'='true'::jsonb
      AND (EXISTS (SELECT 1 FROM accounting.inbox i WHERE i.organization_id=org_key
                    AND i.month<=c.after_row->>'month' AND i.entry_id IS NULL)
           OR EXISTS (SELECT 1 FROM accounting.source_control s WHERE s.organization_id=org_key
                    AND s.month<=c.after_row->>'month' AND s.entry_id IS NULL))
  ) THEN
    RAISE EXCEPTION 'Unposted documents prevent closing';
  END IF;
  SELECT q.* INTO r FROM accounting.financial_close_receipt q
    JOIN accounting.financial_receipt_transaction t ON t.kind='close' AND t.receipt_id=q.id
    WHERE t.root_transaction=txid_current() AND q.organization_id=org_key;
  IF r.id IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO b FROM accounting.period_root_basis
    WHERE root_transaction=txid_current() AND organization_id=org_key;
  SELECT value INTO target_before FROM jsonb_array_elements(b.periods_before) WHERE value->>'month'=r.month;
  IF b.organization_id IS NULL OR target_before->'closed'='true'::jsonb THEN
    RAISE EXCEPTION 'Closing requires an initially open period';
  END IF;
  initial_generation:=COALESCE((target_before->>'generation')::bigint,0);
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.active_closes_before) WHERE value->>'month'=r.month) THEN
    RAISE EXCEPTION 'Period already has an active close';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(b.periods_before)
      WHERE value->>'month'<r.month AND value->'closed'='false'::jsonb) THEN
    RAISE EXCEPTION 'Close earlier periods first';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.inbox WHERE organization_id=org_key AND month<=r.month AND entry_id IS NULL)
     OR EXISTS (SELECT 1 FROM accounting.source_control WHERE organization_id=org_key AND month<=r.month AND entry_id IS NULL) THEN
    RAISE EXCEPTION 'Unposted documents prevent closing';
  END IF;
  new_target:=CASE WHEN target_before IS NULL THEN 1 ELSE 0 END;
  IF EXISTS (SELECT 1 FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
      WHERE t.root_transaction=txid_current() AND e.organization_id=org_key
        AND e.id IS DISTINCT FROM r.monthly_entry_id AND e.id IS DISTINCT FROM r.annual_entry_id) THEN
    RAISE EXCEPTION 'Closing transaction contains unrelated entries';
  END IF;
  SELECT count(*) INTO k FROM accounting.entry e JOIN accounting.entry_transaction t ON t.entry_id=e.id
    WHERE t.root_transaction=txid_current() AND e.organization_id=org_key;
  SELECT generation INTO final_org FROM accounting.organization WHERE id=org_key;
  IF final_org<>b.organization_generation+k OR r.command::jsonb->'expected_generation' IS DISTINCT FROM to_jsonb(initial_generation) THEN
    RAISE EXCEPTION 'Closing initial or organization generation mismatch';
  END IF;
  IF (SELECT count(*) FROM accounting.period WHERE organization_id=org_key)<>jsonb_array_length(b.periods_before)+new_target THEN
    RAISE EXCEPTION 'Closing changed unrelated period set';
  END IF;
  SELECT * INTO p FROM accounting.period WHERE organization_id=org_key AND month=r.month;
  IF p.id IS NULL OR NOT p.closed OR p.generation<>initial_generation+k
     OR p.evidence::jsonb IS DISTINCT FROM r.command::jsonb->'evidence'
     OR r.snapshot::jsonb->'closed_generation' IS DISTINCT FROM to_jsonb(p.generation) THEN
    RAISE EXCEPTION 'Closing target generation or state mismatch';
  END IF;
  FOR original IN SELECT value FROM jsonb_array_elements(b.periods_before) WHERE value->>'month'<>r.month LOOP
    SELECT * INTO p FROM accounting.period WHERE id=(original->>'id')::integer;
    IF original->>'month'<r.month OR k=0 THEN
      IF to_jsonb(p) IS DISTINCT FROM original THEN RAISE EXCEPTION 'Closing changed an unrelated period'; END IF;
    ELSE
      IF to_jsonb(p.closed) IS DISTINCT FROM original->'closed'
         OR p.generation<>(original->>'generation')::bigint+k OR p.evidence::jsonb<>'{}'::jsonb THEN
        RAISE EXCEPTION 'Closing dependent period generation mismatch';
      END IF;
    END IF;
  END LOOP;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER close_period_basis_check AFTER INSERT ON accounting.period_root_basis
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_period_change_check AFTER INSERT ON accounting.period_change
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
-- In IMMEDIATE mode the root stamp must exist before this validator runs.
CREATE CONSTRAINT TRIGGER z_close_period_receipt_check AFTER INSERT ON accounting.financial_close_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_organization_check AFTER UPDATE ON accounting.organization
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER z_close_entry_check AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_source_control_check AFTER INSERT OR UPDATE ON accounting.source_control
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
CREATE CONSTRAINT TRIGGER close_inbox_check AFTER INSERT OR UPDATE ON accounting.inbox
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.validate_close_periods();
