-- Recompute monetary allocation from actual ledger rows, never from supplied totals.
CREATE OR REPLACE FUNCTION accounting.verify_production_cost_review(
  book integer, review_month text, review_policy integer, posting_day date,
  reviewed jsonb, review_command jsonb, excluded_entries integer[], allow_empty boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE p accounting.policy%ROWTYPE; settings jsonb; classes jsonb; bindings jsonb; saved jsonb;
  actual_sources jsonb; actual_ids jsonb; classified_ids jsonb; expected_matrix jsonb;
  expected_balances jsonb; saved_balances jsonb; expected_allocations jsonb; saved_allocations jsonb;
  first_day date; last_day date; item jsonb; saved_order jsonb; order_row production.production_order%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  first_day := (review_month||'-01')::date;
  last_day := (first_day + interval '1 month - 1 day')::date;
  SELECT * INTO p FROM accounting.policy WHERE organization_id=book AND effective_from<=last_day
    ORDER BY effective_from DESC LIMIT 1;
  -- The API validates/stores a typed policy, while the optional finished-goods
  -- field may be omitted from older JSON rows. Rebuild the canonical shape
  -- used by the Python source snapshot before comparing it with the review.
  settings := jsonb_build_object(
    'overhead_accounts', p.production_costing::jsonb->'overhead_accounts',
    'wip_account', p.production_costing::jsonb->>'wip_account',
    'finished_goods_account', p.production_costing::jsonb->>'finished_goods_account',
    'pool_dimensions', p.production_costing::jsonb->'pool_dimensions',
    'order_dimension', p.production_costing::jsonb->>'order_dimension',
    'rounding', p.production_costing::jsonb->>'rounding',
    'reference', p.production_costing::jsonb->>'reference'
  );
  saved := reviewed->'snapshot'->'source'->'snapshot';
  classes := review_command->'classifications';
  bindings := review_command->'orders';
  IF p.id IS DISTINCT FROM review_policy OR p.effective_from>first_day OR settings IS NULL
    OR posting_day IS NULL OR posting_day<first_day OR posting_day>last_day
    OR excluded_entries IS NULL OR array_position(excluded_entries,NULL) IS NOT NULL OR allow_empty IS NULL
    OR p.allocation_basis IS DISTINCT FROM 'direct_cost'
    OR settings->>'rounding' IS DISTINCT FROM 'largest_remainder_cent'
    OR settings->>'order_dimension' IS DISTINCT FROM 'order'
    OR settings->'pool_dimensions' NOT IN ('[]'::jsonb,'["department"]'::jsonb)
    OR saved->'settings' IS DISTINCT FROM settings
    OR saved->>'organization_id' IS DISTINCT FROM book::text
    OR saved->>'month' IS DISTINCT FROM review_month OR saved->>'policy_id' IS DISTINCT FROM p.id::text
    OR reviewed->'snapshot'->>'organization_id' IS DISTINCT FROM book::text
    OR reviewed->'snapshot'->>'month' IS DISTINCT FROM review_month
    OR reviewed->'snapshot'->>'status' IS DISTINCT FROM 'reviewed_allocation_preview'
    OR reviewed->'snapshot'->'posted' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'final_cost_certified' IS DISTINCT FROM 'false'::jsonb
    OR reviewed->'snapshot'->'review' IS DISTINCT FROM review_command
    OR jsonb_typeof(classes) IS DISTINCT FROM 'array' OR jsonb_array_length(classes)=0
    OR jsonb_typeof(bindings) IS DISTINCT FROM 'array' OR (NOT allow_empty AND jsonb_array_length(bindings)=0) THEN
    RAISE EXCEPTION 'Invalid production overhead policy or review structure';
  END IF;
  SELECT jsonb_agg(l.id ORDER BY l.id), jsonb_agg(jsonb_build_object(
    'entry_id',s.id,'line_id',l.id,'entry_digest',s.digest,'source',s.source,'source_version',s.source_version,
    'operation',s.operation,'posting_date',s.posting_date::text,'operation_date',s.operation_date::text,
    'opening',s.opening,'correction_of',s.correction_of,'account',l.account_code,'account_title',l.account_title,
    'dimensions',l.dimensions::jsonb,'side',l.side,'amount_byn',l.amount::text) ORDER BY s.posting_date,s.id,l.id)
    INTO actual_ids,actual_sources
  FROM accounting.line l JOIN accounting.entry s ON s.id=l.entry_id
  WHERE s.organization_id=book AND NOT (s.id=ANY(excluded_entries)) AND s.posting_date<=last_day
    AND (l.account_code=settings->>'wip_account' OR settings->'overhead_accounts' ? l.account_code);
  SELECT jsonb_agg((c->>'line_id')::integer ORDER BY (c->>'line_id')::integer) INTO classified_ids FROM jsonb_array_elements(classes) c;
  IF classified_ids IS DISTINCT FROM actual_ids OR actual_sources IS DISTINCT FROM saved->'lines' THEN
    RAISE EXCEPTION 'Production overhead source lines differ from ledger or classification';
  END IF;
  WITH balances AS (
    SELECT l.account_code,l.dimensions::jsonb AS dimensions,
      sum(CASE WHEN s.posting_date<first_day OR s.opening THEN l.amount*CASE WHEN l.side='debit' THEN 1 ELSE -1 END ELSE 0 END) AS opening,
      sum(CASE WHEN s.posting_date>=first_day AND NOT s.opening AND l.side='debit' THEN l.amount ELSE 0 END) AS debit,
      sum(CASE WHEN s.posting_date>=first_day AND NOT s.opening AND l.side='credit' THEN l.amount ELSE 0 END) AS credit
    FROM accounting.line l JOIN accounting.entry s ON s.id=l.entry_id
    WHERE s.organization_id=book AND NOT (s.id=ANY(excluded_entries)) AND s.posting_date<=last_day
      AND (l.account_code=settings->>'wip_account' OR settings->'overhead_accounts' ? l.account_code)
    GROUP BY l.account_code,l.dimensions::jsonb
  ), objects AS (SELECT jsonb_build_object('account',account_code,'dimensions',dimensions,
      'role',CASE WHEN account_code=settings->>'wip_account' THEN 'wip' ELSE 'overhead' END,
      'opening_byn',opening::numeric(38,2)::text,'debit_byn',debit::numeric(38,2)::text,
      'credit_byn',credit::numeric(38,2)::text,'closing_byn',(opening+debit-credit)::numeric(38,2)::text) AS value FROM balances)
  SELECT jsonb_agg(value ORDER BY value) INTO expected_balances FROM objects;
  SELECT jsonb_agg(value ORDER BY value) INTO saved_balances FROM jsonb_array_elements(saved->'balances');
  IF expected_balances IS DISTINCT FROM saved_balances THEN
    RAISE EXCEPTION 'Production overhead saved balances differ from ledger';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c WHERE
      c->>'role' NOT IN ('direct_cost','overhead','excluded') OR c->>'role' IS NULL
      OR length(btrim(coalesce(c->>'evidence','')))<10 OR length(c->>'evidence')>1000)
    OR (SELECT count(*) FROM jsonb_array_elements(bindings)) IS DISTINCT FROM
       (SELECT count(DISTINCT b->>'analytical_order') FROM jsonb_array_elements(bindings) b)
    OR (SELECT count(*) FROM jsonb_array_elements(bindings)) IS DISTINCT FROM
       (SELECT count(DISTINCT (b->>'order_id')::integer) FROM jsonb_array_elements(bindings) b) THEN
    RAISE EXCEPTION 'Invalid production overhead classification or order bindings';
  END IF;
  IF jsonb_typeof(reviewed->'snapshot'->'production_orders') IS DISTINCT FROM 'array'
    OR jsonb_array_length(reviewed->'snapshot'->'production_orders') IS DISTINCT FROM jsonb_array_length(bindings) THEN
    RAISE EXCEPTION 'Production overhead order snapshots are incomplete';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(bindings) LOOP
    SELECT o.* INTO order_row FROM production.production_order o JOIN production.order_ownership own ON own.order_id=o.id
      WHERE o.id=(item->>'order_id')::integer AND own.organization_id=book FOR UPDATE OF o;
    IF NOT FOUND OR length(btrim(coalesce(item->>'evidence','')))<10 OR length(item->>'evidence')>1000
      OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer
          WHERE c->>'role'='direct_cost' AND l.dimensions->>'order'=item->>'analytical_order') THEN
      RAISE EXCEPTION 'Production overhead target is not a reviewed owned order';
    END IF;
    SELECT value INTO saved_order FROM jsonb_array_elements(reviewed->'snapshot'->'production_orders')
      WHERE value->>'order_id'=order_row.id::text;
    IF NOT FOUND OR saved_order IS DISTINCT FROM jsonb_build_object('order_id',order_row.id,
        'number',order_row.number,'product',order_row.product,'quantity',order_row.qty,'stage',order_row.stage,
        'created_at',saved_order->'created_at')
      OR (saved_order->>'created_at')::timestamptz IS DISTINCT FROM order_row.created_at THEN
      RAISE EXCEPTION 'Production overhead order snapshot differs from its source';
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer
      JOIN accounting.entry s ON s.id=l.entry_id
      WHERE c->>'role'<>'excluded' AND (
        s.opening OR s.posting_date<first_day OR s.posting_date>posting_day OR l.currency<>'BYN' OR l.cash OR l.quantity IS NOT NULL
        OR (c->>'role'='direct_cost' AND (l.account_code IS DISTINCT FROM settings->>'wip_account'
          OR l.category<>'asset' OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(bindings) b WHERE b->>'analytical_order'=l.dimensions->>'order')))
        OR (c->>'role'='overhead' AND NOT (settings->'overhead_accounts' ? l.account_code))
        OR l.dimensions::jsonb IS DISTINCT FROM
          (CASE WHEN settings->'pool_dimensions'='[]'::jsonb THEN '{}'::jsonb ELSE jsonb_build_object('department',l.dimensions->>'department') END
           || CASE WHEN c->>'role'='direct_cost' THEN jsonb_build_object('order',l.dimensions->>'order') ELSE '{}'::jsonb END))) THEN
    RAISE EXCEPTION 'Production overhead included source has invalid date, role or analytics';
  END IF;
  -- Integer quotient/remainder avoids floating or finite-scale division in tie ranking.
  WITH classified AS (
    SELECT l.*, c->>'role' AS role,
      CASE WHEN settings->'pool_dimensions'='[]'::jsonb THEN '{}'::jsonb ELSE jsonb_build_object('department',l.dimensions->>'department') END AS pool,
      l.amount*100*CASE WHEN l.side='debit' THEN 1 ELSE -1 END AS cents
    FROM jsonb_array_elements(classes) c JOIN accounting.line l ON l.id=(c->>'line_id')::integer WHERE c->>'role'<>'excluded'
  ), direct AS (
    SELECT pool,b->>'analytical_order' AS analytical,(b->>'order_id')::integer AS order_id,sum(cents) AS basis
    FROM classified c JOIN jsonb_array_elements(bindings) b ON b->>'analytical_order'=c.dimensions->>'order'
    WHERE role='direct_cost' GROUP BY pool,b->>'analytical_order',(b->>'order_id')::integer
  ), overhead AS (
    SELECT account_code,pool,sum(cents) AS cents FROM classified WHERE role='overhead' GROUP BY account_code,pool
  ), totals AS (SELECT pool,sum(basis) AS total FROM direct GROUP BY pool),
  quotas AS (
    SELECT h.account_code,h.pool,h.cents,d.analytical,d.order_id,d.basis,t.total,
      div(h.cents*d.basis,t.total) AS floor,mod(h.cents*d.basis,t.total) AS remainder
    FROM overhead h JOIN totals t ON t.pool=h.pool JOIN direct d ON d.pool=h.pool WHERE h.cents>0 AND t.total>0
  ), ranked AS (
    SELECT *,row_number() OVER (PARTITION BY account_code,pool ORDER BY remainder DESC,order_id) AS rank,
      cents-sum(floor) OVER (PARTITION BY account_code,pool) AS residual FROM quotas
  ), expected AS (
    SELECT settings->>'wip_account' AS account,'debit' AS side,pool||jsonb_build_object('order',analytical) AS dimensions,
      (floor+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100 AS amount FROM ranked
    UNION ALL SELECT account_code,'credit',pool,cents/100 FROM overhead WHERE cents>0
  ), allocations AS (
    SELECT jsonb_build_object('account',account_code,'pool_dimensions',pool,'allocation',jsonb_build_object(
      'amount_byn',max(cents)::numeric/100,'basis','direct_cost','rounding','largest_remainder_cent',
      'shares',jsonb_agg(jsonb_build_object('order_id',order_id,'basis_amount',(basis/100)::numeric(38,6)::text,
        'amount_byn',((floor+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100)::numeric(38,2)::text) ORDER BY order_id),
      'status','arithmetic_preview','posted',false,'source_movements_verified',false,'final_cost_certified',false)) AS value
    FROM ranked GROUP BY account_code,pool
  ), allocation_strings AS (
    SELECT jsonb_set(value,'{allocation,amount_byn}',to_jsonb((value->'allocation'->>'amount_byn')::numeric(38,2)::text)) AS value FROM allocations
  ), invalid AS (
    SELECT 1 FROM direct WHERE basis<0 UNION ALL SELECT 1 FROM overhead h LEFT JOIN totals t ON t.pool=h.pool
      WHERE h.cents<0 OR (h.cents>0 AND coalesce(t.total,0)<=0)
  )
  SELECT (SELECT CASE WHEN EXISTS(SELECT 1 FROM invalid) THEN NULL ELSE coalesce(jsonb_agg(jsonb_build_array(account,side,dimensions,amount)
    ORDER BY account,side,dimensions,amount),'[]'::jsonb) END FROM expected WHERE amount>0),
    (SELECT jsonb_agg(value ORDER BY value) FROM allocation_strings) INTO expected_matrix,expected_allocations;
  SELECT jsonb_agg(value ORDER BY value) INTO saved_allocations FROM jsonb_array_elements(reviewed->'snapshot'->'allocations');
  IF expected_allocations IS DISTINCT FROM saved_allocations THEN
    RAISE EXCEPTION 'Production overhead saved allocation differs from independent calculation';
  END IF;
  IF expected_matrix IS NULL OR (NOT allow_empty AND expected_matrix='[]'::jsonb) THEN
    RAISE EXCEPTION 'Production overhead posting differs from independently allocated ledger costs';
  END IF;
  IF reviewed->>'digest' IS DISTINCT FROM accounting.financial_sha(reviewed->'snapshot')
    OR reviewed->'snapshot'->'source'->>'digest' IS DISTINCT FROM accounting.financial_sha(saved)
    OR review_command->>'expected_source_digest' IS DISTINCT FROM accounting.financial_sha(saved) THEN
    RAISE EXCEPTION 'Production overhead saved review digest is invalid';
  END IF;
  RETURN expected_matrix;
END $$;

-- Compare an independently verified target with actual applied ledger movements.
-- The revision admission guard supplies the complete, validated predecessor chain.
CREATE OR REPLACE FUNCTION accounting.production_cost_delta(
  book integer, desired jsonb, applied_entries integer[]
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE actual jsonb; result jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=book FOR UPDATE;
  IF applied_entries IS NULL OR cardinality(applied_entries)=0
    OR array_position(applied_entries,NULL) IS NOT NULL
    OR cardinality(applied_entries)<>(SELECT count(DISTINCT id) FROM unnest(applied_entries) id)
    OR cardinality(applied_entries)<>(SELECT count(*) FROM accounting.entry WHERE id=ANY(applied_entries)
        AND organization_id=book AND operation IN ('production_overhead','production_overhead_correction')) THEN
    RAISE EXCEPTION 'Cost correction requires unique existing allocation entries of this organization';
  END IF;
  IF jsonb_typeof(desired) IS DISTINCT FROM 'array' OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(desired) row WHERE jsonb_typeof(row) IS DISTINCT FROM 'array'
      OR jsonb_array_length(row)<>4 OR jsonb_typeof(row->0) IS DISTINCT FROM 'string'
      OR length(row->>0)=0 OR row->>1 NOT IN ('debit','credit') OR row->>1 IS NULL
      OR jsonb_typeof(row->2) IS DISTINCT FROM 'object' OR jsonb_typeof(row->3) IS DISTINCT FROM 'number'
      OR (row->>3)::numeric<=0 OR (row->>3)::numeric*100<>trunc((row->>3)::numeric*100)) THEN
    RAISE EXCEPTION 'Cost correction requires an exact positive BYN target matrix';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_array(l.account_code,l.side,l.dimensions::jsonb,l.amount)),'[]'::jsonb)
    INTO actual FROM accounting.line l WHERE l.entry_id=ANY(applied_entries);
  IF coalesce((SELECT sum((row->>3)::numeric*CASE WHEN row->>1='debit' THEN 1 ELSE -1 END)
      FROM jsonb_array_elements(desired) row),0)<>0
    OR coalesce((SELECT sum((row->>3)::numeric*CASE WHEN row->>1='debit' THEN 1 ELSE -1 END)
      FROM jsonb_array_elements(actual) row),0)<>0 THEN
    RAISE EXCEPTION 'Cost correction target and applied entries must each balance';
  END IF;
  WITH movements AS (
    SELECT row->>0 AS account,row->2 AS dimensions,(row->>3)::numeric*100*
      CASE WHEN row->>1='debit' THEN 1 ELSE -1 END AS cents FROM jsonb_array_elements(desired) row
    UNION ALL
    SELECT row->>0,row->2,(row->>3)::numeric*100*
      CASE WHEN row->>1='debit' THEN -1 ELSE 1 END FROM jsonb_array_elements(actual) row
  ), differences AS (
    SELECT account,dimensions,sum(cents) AS cents FROM movements GROUP BY account,dimensions
  )
  SELECT coalesce(jsonb_agg(jsonb_build_array(account,CASE WHEN cents>0 THEN 'debit' ELSE 'credit' END,dimensions,abs(cents)/100)
    ORDER BY account,dimensions),'[]'::jsonb) INTO result FROM differences WHERE cents<>0;
  RETURN result;
END $$;

-- Initial posting keeps its strict entry/receipt contract. Correction admission
-- reuses the independent source calculation and supplies its own validated chain.
CREATE OR REPLACE FUNCTION accounting.verify_production_overhead(target integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.production_overhead_receipt%ROWTYPE; e accounting.entry%ROWTYPE;
  expected_matrix jsonb; actual_matrix jsonb;
BEGIN
  SELECT * INTO r FROM accounting.production_overhead_receipt WHERE entry_id=target;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF r.entry_id IS NULL OR e.id IS NULL THEN RAISE EXCEPTION 'Missing production overhead entry or receipt'; END IF;
  expected_matrix := accounting.verify_production_cost_review(e.organization_id,r.month,e.policy_id,e.posting_date,
    r.review::jsonb,r.command::jsonb->'review',ARRAY[target],false);
  SELECT jsonb_agg(jsonb_build_array(account_code,side,dimensions::jsonb,amount)
    ORDER BY account_code,side,dimensions::jsonb,amount) INTO actual_matrix FROM accounting.line WHERE entry_id=target;
  IF expected_matrix IS DISTINCT FROM actual_matrix THEN
    RAISE EXCEPTION 'Production overhead posting differs from independently allocated ledger costs';
  END IF;
END $$;
