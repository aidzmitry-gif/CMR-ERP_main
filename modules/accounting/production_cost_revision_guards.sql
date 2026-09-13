CREATE TRIGGER immutable_production_overhead_revision BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_revision FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE TRIGGER a_capture_period_basis BEFORE INSERT ON accounting.production_overhead_revision
FOR EACH ROW EXECUTE FUNCTION accounting.capture_period_basis();

CREATE OR REPLACE FUNCTION accounting.guard_overhead_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE original accounting.production_overhead_receipt; predecessor accounting.production_overhead_revision; day date;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM accounting.production_overhead_correction_withdrawal
    WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'Withdrawn correction request cannot be confirmed';
  END IF;
  SELECT * INTO original FROM accounting.production_overhead_receipt WHERE entry_id=NEW.original_entry_id;
  SELECT * INTO predecessor FROM accounting.production_overhead_revision WHERE original_entry_id=NEW.original_entry_id ORDER BY sequence DESC LIMIT 1;
  day := (NEW.command->'preview'->>'posting_date')::date;
  IF original.entry_id IS NULL OR original.organization_id IS DISTINCT FROM NEW.organization_id OR original.month IS DISTINCT FROM NEW.month
    OR NEW.sequence IS DISTINCT FROM coalesce(predecessor.sequence,0)+1 OR NEW.previous_id IS DISTINCT FROM predecessor.id
    OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
    OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
    OR day IS NULL OR to_char(day,'YYYY-MM') IS DISTINCT FROM NEW.month
    OR day<coalesce((predecessor.command->'preview'->>'posting_date')::date,(original.command->>'posting_date')::date)
    OR length(btrim(NEW.actor))<1 OR length(btrim(coalesce(NEW.command->'preview'->>'evidence',''))) NOT BETWEEN 10 AND 1000
    OR NEW.command->'preview'->>'method' IS DISTINCT FROM 'delta'
    OR EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id AND month>=NEW.month AND closed) THEN
    RAISE EXCEPTION 'Invalid or stale production calculation revision chain';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_overhead_revision_chain BEFORE INSERT ON accounting.production_overhead_revision
FOR EACH ROW EXECUTE FUNCTION accounting.guard_overhead_revision();

CREATE OR REPLACE FUNCTION accounting.verify_overhead_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_revision; original accounting.production_overhead_receipt;
  e accounting.entry; predecessor accounting.production_overhead_revision;
  target integer; applied integer[]; excluded integer[]; ids jsonb; chain jsonb; snap jsonb; reviewed jsonb;
  desired jsonb; delta jsonb; expected_lines jsonb; declared_matrix jsonb; actual_matrix jsonb; day date;
  basis accounting.period_root_basis; before_period jsonb; current_period accounting.period; current_generation bigint;
BEGIN
  IF TG_TABLE_NAME='production_overhead_revision' THEN SELECT * INTO r FROM accounting.production_overhead_revision WHERE id=NEW.id;
  ELSE
    IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
    SELECT * INTO e FROM accounting.entry WHERE id=target;
    IF e.operation IS DISTINCT FROM 'production_overhead_correction' THEN RETURN NULL; END IF;
    SELECT * INTO r FROM accounting.production_overhead_revision WHERE entry_id=target;
  END IF;
  IF r.id IS NULL THEN RAISE EXCEPTION 'Production correction requires its complete immutable calculation revision'; END IF;
  PERFORM 1 FROM accounting.organization WHERE id=r.organization_id FOR UPDATE;
  SELECT * INTO original FROM accounting.production_overhead_receipt WHERE entry_id=r.original_entry_id;
  SELECT * INTO e FROM accounting.entry WHERE id=r.original_entry_id;
  SELECT * INTO predecessor FROM accounting.production_overhead_revision WHERE id=r.previous_id;
  SELECT coalesce(jsonb_agg(id ORDER BY sequence),'[]'::jsonb),
    ARRAY[r.original_entry_id]||coalesce(array_agg(entry_id ORDER BY sequence) FILTER(WHERE entry_id IS NOT NULL),ARRAY[]::integer[])
    INTO ids,applied FROM accounting.production_overhead_revision WHERE original_entry_id=r.original_entry_id AND sequence<r.sequence;
  chain:=jsonb_build_object('revision_ids',ids,'applied_entry_ids',to_jsonb(applied),
    'latest_digest',coalesce(predecessor.preview->>'digest',original.review->>'digest'));
  snap:=r.preview::jsonb->'snapshot'; reviewed:=snap->'reviewed'; day:=(r.command->'preview'->>'posting_date')::date;
  IF snap->'command' IS DISTINCT FROM r.command::jsonb->'preview'
    OR snap->>'organization_id' IS DISTINCT FROM r.organization_id::text OR snap->>'month' IS DISTINCT FROM r.month
    OR snap->>'original_entry_id' IS DISTINCT FROM r.original_entry_id::text
    OR snap->'original_posting' IS DISTINCT FROM original.posting::jsonb
    OR snap->>'status' IS DISTINCT FROM 'correction_preview' OR snap->'posted' IS DISTINCT FROM 'false'::jsonb
    OR snap->'confirmation_available' IS DISTINCT FROM 'true'::jsonb OR snap->'final_cost_certified' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'source'->'snapshot'->'calculation_chain' IS DISTINCT FROM chain
    OR reviewed->'snapshot'->'source'->'snapshot'->>'scope' IS DISTINCT FROM 'production_cost_correction_sources'
    OR reviewed->'snapshot'->'source'->'snapshot'->'excluded_allocation' IS DISTINCT FROM
      jsonb_build_object('entry_id',original.entry_id,'entry_digest',e.digest,'request_key',original.request_key)
    OR r.command->'preview'->>'original_entry_id' IS DISTINCT FROM r.original_entry_id::text
    OR r.command->'preview'->'review'->>'policy_id' IS DISTINCT FROM original.command->'review'->>'policy_id'
    OR r.command->'preview'->>'expected_review_digest' IS DISTINCT FROM reviewed->>'digest'
    OR r.preview->>'digest' IS DISTINCT FROM accounting.financial_sha(snap)
    OR r.command->>'expected_preview_digest' IS DISTINCT FROM r.preview->>'digest' THEN
    RAISE EXCEPTION 'Production correction calculation snapshot or chain mismatch';
  END IF;
  excluded:=applied||CASE WHEN r.entry_id IS NULL THEN ARRAY[]::integer[] ELSE ARRAY[r.entry_id] END;
  desired:=accounting.verify_production_cost_review(r.organization_id,r.month,(original.command->'review'->>'policy_id')::integer,
    day,reviewed,r.command::jsonb->'preview'->'review',excluded,true);
  SELECT coalesce(jsonb_agg(jsonb_build_array(line->>'account',line->>'side',line->'dimensions',(line->>'amount')::numeric)
    ORDER BY line->>'account',line->>'side',line->'dimensions',(line->>'amount')::numeric),'[]'::jsonb)
    INTO declared_matrix FROM jsonb_array_elements(snap->'desired_allocation_lines') line;
  IF desired IS DISTINCT FROM declared_matrix THEN RAISE EXCEPTION 'Production correction target differs from verified costs'; END IF;
  delta:=accounting.production_cost_delta(r.organization_id,desired,applied);
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',line->>0,'side',line->>1,'dimensions',line->2,
    'amount',((line->>3)::numeric)::numeric(38,2)::text) ORDER BY line->>0,line->2),'[]'::jsonb)
    INTO expected_lines FROM jsonb_array_elements(delta) line;
  IF snap->'correction_lines' IS DISTINCT FROM expected_lines
    OR snap->'creates_entry' IS DISTINCT FROM to_jsonb(delta<>'[]'::jsonb)
    OR (r.entry_id IS NULL) IS DISTINCT FROM (delta='[]'::jsonb) THEN
    RAISE EXCEPTION 'Production correction delta or optional entry mismatch';
  END IF;
  IF r.entry_id IS NULL THEN
    IF r.posting::jsonb IS NOT NULL AND r.posting::jsonb<>'null'::jsonb THEN RAISE EXCEPTION 'Zero correction cannot contain a posting'; END IF;
    SELECT * INTO basis FROM accounting.period_root_basis WHERE organization_id=r.organization_id AND root_transaction=txid_current();
    SELECT generation INTO current_generation FROM accounting.organization WHERE id=r.organization_id;
    IF basis.organization_id IS NULL OR current_generation<>basis.organization_generation+1
      OR EXISTS (SELECT 1 FROM accounting.entry movement JOIN accounting.entry_transaction t ON t.entry_id=movement.id
        WHERE movement.organization_id=r.organization_id AND t.root_transaction=txid_current())
      OR (SELECT count(*) FROM accounting.period WHERE organization_id=r.organization_id)<>jsonb_array_length(basis.periods_before) THEN
      RAISE EXCEPTION 'Zero correction must invalidate its calculation generation exactly once';
    END IF;
    FOR before_period IN SELECT value FROM jsonb_array_elements(basis.periods_before) LOOP
      SELECT * INTO current_period FROM accounting.period WHERE id=(before_period->>'id')::integer;
      IF before_period->>'month'<r.month THEN
        IF to_jsonb(current_period) IS DISTINCT FROM before_period THEN RAISE EXCEPTION 'Zero correction changed an earlier period'; END IF;
      ELSIF current_period.generation<>(before_period->>'generation')::bigint+1 OR current_period.closed
        OR current_period.evidence::jsonb<>'{}'::jsonb THEN
        RAISE EXCEPTION 'Zero correction must invalidate every dependent period';
      END IF;
    END LOOP;
    RETURN NULL;
  END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=r.entry_id;
  IF e.operation IS DISTINCT FROM 'production_overhead_correction' OR e.organization_id IS DISTINCT FROM r.organization_id
    OR e.actor IS DISTINCT FROM r.actor OR e.posting_date IS DISTINCT FROM day OR e.document_date IS DISTINCT FROM day OR e.operation_date IS DISTINCT FROM day
    OR e.policy_id IS DISTINCT FROM (original.command->'review'->>'policy_id')::integer OR e.opening
    OR e.correction_of IS DISTINCT FROM applied[cardinality(applied)] OR e.source_version IS DISTINCT FROM r.sequence
    OR e.source IS DISTINCT FROM 'production:overhead:'||r.organization_id||':'||r.month
    OR e.rule_version IS DISTINCT FROM 'production-overhead-correction-v1' OR e.explanation IS DISTINCT FROM r.command->'preview'->>'evidence'
    OR accounting.posting_body_projection(r.posting::jsonb) IS DISTINCT FROM accounting.posting_body_projection(accounting.financial_posting_body(e.id),false) THEN
    RAISE EXCEPTION 'Production correction entry differs from its calculation receipt';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'side',side,'dimensions',dimensions::jsonb,'amount',amount::text)
    ORDER BY account_code,dimensions::jsonb),'[]'::jsonb) INTO actual_matrix FROM accounting.line WHERE entry_id=e.id;
  IF actual_matrix IS DISTINCT FROM expected_lines THEN RAISE EXCEPTION 'Production correction ledger delta mismatch'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_overhead_revision AFTER INSERT ON accounting.production_overhead_revision
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();
CREATE CONSTRAINT TRIGGER complete_overhead_revision_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();
CREATE CONSTRAINT TRIGGER complete_overhead_revision_line AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.verify_overhead_revision();

CREATE TRIGGER immutable_overhead_correction_withdrawal BEFORE UPDATE OR DELETE OR TRUNCATE
ON accounting.production_overhead_correction_withdrawal FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();
CREATE OR REPLACE FUNCTION accounting.guard_correction_withdrawal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM accounting.production_overhead_revision WHERE organization_id=NEW.organization_id AND request_key=NEW.request_key) THEN
    RAISE EXCEPTION 'Confirmed correction request cannot be withdrawn';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
    OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
    OR to_char((NEW.command->'preview'->>'posting_date')::date,'YYYY-MM') IS DISTINCT FROM NEW.month
    OR length(btrim(NEW.actor))<1 OR length(btrim(NEW.reason)) NOT BETWEEN 10 AND 1000 THEN
    RAISE EXCEPTION 'Correction withdrawal must retain request identity and reason';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER correction_withdrawal_decision BEFORE INSERT ON accounting.production_overhead_correction_withdrawal
FOR EACH ROW EXECUTE FUNCTION accounting.guard_correction_withdrawal();
