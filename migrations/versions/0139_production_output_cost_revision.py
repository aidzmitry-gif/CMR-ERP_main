"""Immutable reviewed revisions for finished-goods output cost.

Revision ID: 0139
Revises: 0138
"""
from alembic import op

revision = "0139"
down_revision = "0138"
branch_labels = None
depends_on = None


DDL = r"""
CREATE TABLE accounting.production_output_cost_revision (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  original_entry_id INTEGER NOT NULL REFERENCES accounting.production_output_transfer_receipt(entry_id),
  sequence INTEGER NOT NULL,
  previous_id INTEGER REFERENCES accounting.production_output_cost_revision(id),
  entry_id INTEGER UNIQUE REFERENCES accounting.entry(id),
  registration_token INTEGER NOT NULL UNIQUE,
  month VARCHAR(7) NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  command JSON NOT NULL,
  preview JSON NOT NULL,
  posting JSON,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
  CONSTRAINT uq_output_cost_revision_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_output_cost_revision_sequence UNIQUE (original_entry_id, sequence)
);

CREATE OR REPLACE FUNCTION accounting.register_output_cost_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE entry_sequence text;
BEGIN
  IF NEW.registration_token IS NOT NULL THEN
    RAISE EXCEPTION 'Output cost revision registration token is database assigned';
  END IF;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT pg_get_serial_sequence('accounting.entry', 'id') INTO entry_sequence;
  IF entry_sequence IS NULL THEN
    RAISE EXCEPTION 'Accounting entry identity sequence is unavailable';
  END IF;
  EXECUTE format('SELECT nextval(%L)', entry_sequence) INTO NEW.registration_token;
  RETURN NEW;
END $$;
CREATE TRIGGER register_output_cost_revision
BEFORE INSERT ON accounting.production_output_cost_revision
FOR EACH ROW EXECUTE FUNCTION accounting.register_output_cost_revision();


-- Derive allocations independently of the submitted preview and correction.
CREATE OR REPLACE FUNCTION accounting.output_pool_revision_rows(
  org integer, output_id integer, cutoff date, excluded_entry integer
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  origin accounting.line%ROWTYPE;
  movement record;
  destination accounting.line%ROWTYPE;
  saved jsonb;
  balances jsonb := '{}'::jsonb;
  rows jsonb := '[]'::jsonb;
  prior jsonb;
  key text;
  pool_quantity numeric := 0;
  participation numeric := 0;
  adjustment numeric := 0;
  share numeric;
  adjusted_share numeric;
  qty numeric;
  balance record;
BEGIN
  SELECT * INTO STRICT origin FROM accounting.line WHERE entry_id=output_id AND side='debit';
  SELECT coalesce(jsonb_agg(a),'[]'::jsonb) INTO prior
    FROM accounting.production_output_cost_revision r
    CROSS JOIN LATERAL jsonb_array_elements(r.preview::jsonb->'ledger_evidence'->'allocation') a
    WHERE r.organization_id=org AND r.original_entry_id=output_id;
  FOR movement IN
    SELECT e.id movement_id,e.operation,e.digest,e.correction_of,l.*
    FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=cutoff
      AND e.id<>coalesce(excluded_entry,-1) AND l.account_code=origin.account_code
      AND l.dimensions->>'warehouse'=origin.dimensions->>'warehouse'
      AND l.dimensions->>'sku'=origin.dimensions->>'sku'
    ORDER BY e.posting_date,e.id,l.id
  LOOP
    IF movement.currency<>'BYN' OR movement.cash OR movement.category<>'asset'
       OR nullif(movement.dimensions->>'lot','') IS NULL THEN
      RAISE EXCEPTION 'Malformed weighted-average output pool movement';
    END IF;
    key := movement.dimensions::jsonb::text;
    IF movement.quantity IS NULL THEN
      IF movement.operation<>'production_output_cost_correction' OR NOT EXISTS (
        SELECT 1 FROM accounting.production_output_cost_revision r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org
      ) THEN RAISE EXCEPTION 'Pool value movement lacks an immutable output revision'; END IF;
      IF movement.correction_of=output_id THEN
        adjustment := adjustment + CASE WHEN movement.side='debit' THEN movement.amount ELSE -movement.amount END;
      END IF;
      CONTINUE;
    END IF;
    IF movement.quantity<=0 THEN RAISE EXCEPTION 'Invalid pool movement quantity'; END IF;
    qty := coalesce((balances->>key)::numeric,0);
    IF movement.side='debit' THEN
      IF movement.operation<>'production_output_transfer' OR NOT EXISTS (
        SELECT 1 FROM accounting.production_output_transfer_receipt r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org AND r.digest=movement.digest
      ) THEN RAISE EXCEPTION 'Pool acquisition lacks an immutable output receipt'; END IF;
      balances := jsonb_set(balances,ARRAY[key],to_jsonb(qty+movement.quantity));
      pool_quantity := pool_quantity+movement.quantity;
      IF movement.id=origin.id THEN participation := origin.quantity; END IF;
      CONTINUE;
    END IF;
    IF qty<movement.quantity OR pool_quantity<movement.quantity THEN
      RAISE EXCEPTION 'Pool disposition exceeds physical quantity';
    END IF;
    saved := NULL;
    IF movement.operation='inventory_sale' THEN
      SELECT to_jsonb(r) INTO saved FROM accounting.inventory_sale_receipt r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org AND r.digest=movement.digest;
    ELSIF movement.operation='inventory_issue' THEN
      SELECT to_jsonb(r) INTO saved FROM accounting.inventory_issue_receipt r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org AND r.digest=movement.digest;
    END IF;
    IF saved IS NULL THEN RAISE EXCEPTION 'Pool disposition lacks its immutable receipt'; END IF;
    SELECT * INTO STRICT destination FROM accounting.line WHERE entry_id=movement.movement_id AND side='debit'
      AND account_code=saved->'command'->>'expense_account'
      AND dimensions::jsonb=coalesce(saved->'command'->'expense_dimensions','{}'::jsonb);
    IF destination.quantity IS NOT NULL OR destination.currency<>'BYN' OR destination.cash
       OR destination.amount IS DISTINCT FROM (SELECT sum(amount) FROM accounting.line
         WHERE entry_id=movement.movement_id AND side='credit' AND account_code=origin.account_code) THEN
      RAISE EXCEPTION 'Pool disposition destination differs from receipt';
    END IF;
    share := participation*movement.quantity/pool_quantity;
    adjusted_share := round(adjustment*movement.quantity/pool_quantity,2);
    participation := participation-share;
    adjustment := adjustment-adjusted_share;
    IF share<>0 OR adjusted_share<>0 THEN
      rows := rows || jsonb_build_array(jsonb_build_object(
        'key','disposed:'||movement.movement_id||':'||movement.id,
        'account',destination.account_code,'dimensions',destination.dimensions::jsonb,
        'quantity',share,'adjustment',adjusted_share+coalesce((SELECT sum((a->>'delta')::numeric)
          FROM jsonb_array_elements(prior) a
          WHERE a->>'key'='disposed:'||movement.movement_id||':'||movement.id),0)));
    END IF;
    pool_quantity := pool_quantity-movement.quantity;
    balances := jsonb_set(balances,ARRAY[key],to_jsonb(qty-movement.quantity));
  END LOOP;
  IF pool_quantity=0 AND (participation<>0 OR adjustment<>0) THEN
    RAISE EXCEPTION 'Empty pool retains output contribution';
  END IF;
  -- Attribute the surviving contribution to the actual remaining physical lots.
  FOR balance IN SELECT k,v::numeric qty FROM jsonb_each_text(balances) b(k,v)
    WHERE v::numeric>0 ORDER BY k
  LOOP
    share := participation*balance.qty/pool_quantity;
    adjusted_share := round(adjustment*balance.qty/pool_quantity,2);
    rows := rows || jsonb_build_array(jsonb_build_object('key',
      CASE WHEN balance.k=origin.dimensions::jsonb::text THEN 'remaining' ELSE 'remaining:'||balance.k END,
      'account',origin.account_code,'dimensions',balance.k::jsonb,
      'quantity',share,'adjustment',adjusted_share));
    participation := participation-share;
    adjustment := adjustment-adjusted_share;
    pool_quantity := pool_quantity-balance.qty;
  END LOOP;
  -- Original contribution is allocated independently of physical lot credits.
  WITH quotas AS (
    SELECT r,ord,div(origin.amount*100*(r->>'quantity')::numeric,origin.quantity) cents,
      mod(origin.amount*100*(r->>'quantity')::numeric,origin.quantity) fraction
    FROM jsonb_array_elements(rows) WITH ORDINALITY t(r,ord)
  ), ranked AS (
    SELECT *,row_number() OVER (ORDER BY fraction DESC,ord) rank,
      origin.amount*100-sum(cents) OVER () residual FROM quotas
  ) SELECT coalesce(jsonb_agg((r-'adjustment') || jsonb_build_object('applied_delta',(r->>'adjustment')::numeric,'book',
      (cents+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100+(r->>'adjustment')::numeric)
      ORDER BY ord),'[]'::jsonb) INTO rows FROM ranked;
  RETURN rows;
END $$;

-- Prior allocations are immutable, database-verified deltas. Apply them to
-- current dispositions, including sales registered between revisions.
CREATE OR REPLACE FUNCTION accounting.output_cost_revision_evidence(
  org integer, output_id integer, cutoff date, excluded_entry integer
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  receipt accounting.production_output_transfer_receipt%ROWTYPE;
  origin accounting.line%ROWTYPE;
  movement record;
  destination accounting.line%ROWTYPE;
  saved jsonb;
  wip text;
  order_key text;
  order_value text;
  required_keys jsonb;
  source_rows jsonb;
  source_groups jsonb;
  rows jsonb := '[]'::jsonb;
  allocation jsonb;
  matrix jsonb;
  remainder_qty numeric;
  remainder_cost numeric;
  source_cost numeric;
  inventory_credit numeric;
  prior_allocation jsonb;
  previous_source jsonb;
  valuation_method text;
  allocation_amount numeric;
BEGIN
  SELECT * INTO STRICT receipt FROM accounting.production_output_transfer_receipt
    WHERE entry_id=output_id AND organization_id=org;
  IF EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r WHERE r.original_entry_id=output_id
               AND (r.command->>'posting_date')::date>cutoff) THEN
    RAISE EXCEPTION 'Output revisions cannot precede their existing revision chain';
  END IF;
  SELECT coalesce(jsonb_agg(a),'[]'::jsonb) INTO prior_allocation
    FROM accounting.production_output_cost_revision r
    CROSS JOIN LATERAL jsonb_array_elements(r.preview::jsonb->'ledger_evidence'->'allocation') a
    WHERE r.original_entry_id=output_id AND r.organization_id=org;
  SELECT r.preview::jsonb->'ledger_evidence'->'source_lines' INTO previous_source
    FROM accounting.production_output_cost_revision r WHERE r.original_entry_id=output_id AND r.organization_id=org
    ORDER BY r.sequence DESC LIMIT 1;
  SELECT * INTO STRICT origin FROM accounting.line
    WHERE entry_id=output_id AND side='debit';
  SELECT inventory_method INTO valuation_method FROM accounting.policy
    WHERE id=(receipt.basis->>'policy_id')::integer AND organization_id=org;
  IF origin.quantity IS NULL OR origin.quantity<=0 OR origin.currency<>'BYN'
     OR origin.cash OR origin.category<>'asset' THEN
    RAISE EXCEPTION 'Output revision origin is not a finished-goods layer';
  END IF;
  wip := receipt.basis->'wip'->>'account';
  order_value := receipt.command->>'analytical_order';
  SELECT production_costing->>'order_dimension',
         (production_costing->'pool_dimensions')::jsonb ||
           jsonb_build_array(production_costing->>'order_dimension')
    INTO order_key, required_keys FROM accounting.policy
    WHERE id=(receipt.basis->>'policy_id')::integer AND organization_id=org;
  IF wip IS NULL OR order_key IS NULL OR order_value IS NULL OR required_keys IS NULL THEN
    RAISE EXCEPTION 'Output revision source policy is unavailable';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id', e.id, 'line_id', l.id,
      'posting_date', e.posting_date, 'account', l.account_code, 'side', l.side,
      'amount', l.amount, 'dimensions', l.dimensions::jsonb) ORDER BY e.posting_date,e.id,l.id),'[]'::jsonb),
      coalesce(sum(CASE WHEN l.side='debit' THEN l.amount ELSE -l.amount END),0)
    INTO source_rows, source_cost
    FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=cutoff
      AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)
      AND NOT EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r
                      WHERE r.original_entry_id=output_id AND r.entry_id=e.id)
      AND l.account_code=wip AND l.dimensions->>order_key=order_value;
  IF EXISTS (
    SELECT 1 FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=cutoff
      AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)
      AND NOT EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r
                      WHERE r.original_entry_id=output_id AND r.entry_id=e.id)
      AND l.account_code=wip AND l.dimensions->>order_key=order_value
      AND (l.currency<>'BYN' OR l.cash OR l.quantity IS NOT NULL OR l.category<>'asset'
        OR jsonb_typeof(l.dimensions::jsonb)<>'object'
        OR (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_object_keys(l.dimensions::jsonb) k)
          IS DISTINCT FROM (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_array_elements_text(required_keys) k))
  ) THEN RAISE EXCEPTION 'Malformed output revision WIP evidence'; END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('dimensions', dims, 'amount', amount) ORDER BY dims::text),'[]'::jsonb)
    INTO source_groups FROM (
      SELECT r->'dimensions' dims, sum(CASE WHEN r->>'side'='debit'
        THEN (r->>'amount')::numeric ELSE -(r->>'amount')::numeric END) amount
      FROM jsonb_array_elements(source_rows) r GROUP BY r->'dimensions'
    ) g;
  IF source_cost<0 OR EXISTS (SELECT 1 FROM jsonb_array_elements(source_groups) g WHERE (g->>'amount')::numeric<0) THEN
    RAISE EXCEPTION 'Negative output revision source analytic balance';
  END IF;
  IF valuation_method='weighted_average' THEN
    rows := accounting.output_pool_revision_rows(org,output_id,cutoff,excluded_entry);
  ELSE
  remainder_qty := origin.quantity;
  remainder_cost := origin.amount + coalesce((SELECT sum((a->>'delta')::numeric)
    FROM jsonb_array_elements(prior_allocation) a WHERE a->>'key'='remaining'),0);
  FOR movement IN
    SELECT e.id movement_id,e.operation,e.digest,l.*
    FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=cutoff
      AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)
      AND NOT EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r
                      WHERE r.original_entry_id=output_id AND r.entry_id=e.id)
      AND l.account_code=origin.account_code AND l.dimensions::jsonb=origin.dimensions::jsonb
    ORDER BY e.id,l.id
  LOOP
    IF movement.side<>'credit' OR movement.quantity IS NULL OR movement.quantity<=0
       OR movement.currency<>'BYN' OR movement.cash OR movement.category<>'asset' THEN
      RAISE EXCEPTION 'Unverified output layer movement';
    END IF;
    saved := NULL;
    IF movement.operation='inventory_sale' THEN
      SELECT to_jsonb(r) INTO saved FROM accounting.inventory_sale_receipt r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org AND r.digest=movement.digest;
    ELSIF movement.operation='inventory_issue' THEN
      SELECT to_jsonb(r) INTO saved FROM accounting.inventory_issue_receipt r
        WHERE r.entry_id=movement.movement_id AND r.organization_id=org AND r.digest=movement.digest;
    END IF;
    IF saved IS NULL THEN RAISE EXCEPTION 'Output disposal lacks its immutable receipt'; END IF;
    SELECT * INTO STRICT destination FROM accounting.line
      WHERE entry_id=movement.movement_id AND side='debit'
        AND account_code=saved->'command'->>'expense_account'
        AND dimensions::jsonb=coalesce(saved->'command'->'expense_dimensions','{}'::jsonb);
    SELECT sum(amount) INTO inventory_credit FROM accounting.line
      WHERE entry_id=movement.movement_id AND side='credit' AND account_code=origin.account_code;
    IF destination.quantity IS NOT NULL OR destination.currency<>'BYN' OR destination.cash
       OR destination.amount IS DISTINCT FROM inventory_credit THEN
      RAISE EXCEPTION 'Output disposal destination differs from receipt';
    END IF;
    remainder_qty := remainder_qty-movement.quantity;
    remainder_cost := remainder_cost-movement.amount;
    rows := rows || jsonb_build_array(jsonb_build_object('key', 'disposed:'||movement.movement_id||':'||movement.id,
      'account',destination.account_code,'dimensions',destination.dimensions::jsonb,
      'quantity',movement.quantity,'book',movement.amount + coalesce((SELECT sum((a->>'delta')::numeric)
        FROM jsonb_array_elements(prior_allocation) a
        WHERE a->>'key'='disposed:'||movement.movement_id||':'||movement.id),0)));
  END LOOP;
  IF remainder_qty<0 OR remainder_cost<0 OR (remainder_qty=0 AND remainder_cost<>0) THEN
    RAISE EXCEPTION 'Output disposition quantity or book cost is invalid';
  END IF;
  rows := jsonb_build_array(jsonb_build_object('key','remaining','account',origin.account_code,
    'dimensions',origin.dimensions::jsonb,'quantity',remainder_qty,'book',remainder_cost)) || rows;
  END IF;
  -- Pool corrections distribute the cumulative additional cost itself, not
  -- the difference of two independently rounded allocations of full cost.
  allocation_amount := CASE WHEN valuation_method='weighted_average'
    THEN abs(source_cost-origin.amount) ELSE source_cost END;
  WITH quotas AS (
    SELECT r,ord,div(allocation_amount*100*(r->>'quantity')::numeric,origin.quantity) cents,
      mod(allocation_amount*100*(r->>'quantity')::numeric,origin.quantity) fraction
    FROM jsonb_array_elements(rows) WITH ORDINALITY t(r,ord)
  ), ranked AS (
    SELECT *,row_number() OVER (ORDER BY fraction DESC,ord) rank,
      allocation_amount*100-sum(cents) OVER () residual FROM quotas
  ), valued AS (
    SELECT *, CASE WHEN valuation_method='weighted_average' THEN
      (r->>'book')::numeric-(r->>'applied_delta')::numeric
      +sign(source_cost-origin.amount)*(cents+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100
      ELSE (cents+CASE WHEN rank<=residual THEN 1 ELSE 0 END)/100 END desired
    FROM ranked
  ) SELECT jsonb_agg(r || jsonb_build_object('desired',desired,
      'delta',desired-(r->>'book')::numeric)
      ORDER BY ord) INTO allocation FROM valued;
  WITH contributions AS (
    SELECT r->>'account' account,r->'dimensions' dimensions,(r->>'delta')::numeric delta
      FROM jsonb_array_elements(allocation) r
    UNION ALL
    SELECT wip,g->'dimensions',-(g->>'amount')::numeric FROM jsonb_array_elements(source_groups) g
    UNION ALL
    SELECT wip,l.dimensions::jsonb,l.amount FROM accounting.line l
      WHERE l.entry_id=output_id AND l.side='credit' AND previous_source IS NULL
    UNION ALL
    SELECT wip,r->'dimensions',CASE WHEN r->>'side'='debit' THEN (r->>'amount')::numeric
      ELSE -(r->>'amount')::numeric END FROM jsonb_array_elements(previous_source) r
  ), grouped AS (
    SELECT account,dimensions,sum(delta) delta FROM contributions GROUP BY account,dimensions
  ) SELECT coalesce(jsonb_agg(jsonb_build_object('account',account,'dimensions',dimensions,
      'side',CASE WHEN delta>0 THEN 'debit' ELSE 'credit' END,'amount',abs(delta))
      ORDER BY account,dimensions::text),'[]'::jsonb) INTO matrix FROM grouped WHERE delta<>0;
  RETURN jsonb_build_object('source_lines',source_rows,'allocation',allocation,'matrix',matrix);
END $$;

-- A revision is never a caller-provided allocation assertion.  The source
-- amount and required correction are re-derived from immutable ledger rows;
-- this trigger intentionally leaves confirmation unavailable until an
-- application command can produce the constrained entry package below.
CREATE OR REPLACE FUNCTION accounting.guard_output_cost_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  original accounting.production_output_transfer_receipt%ROWTYPE;
  original_entry accounting.entry%ROWTYPE;
  correction_entry accounting.entry%ROWTYPE;
  previous accounting.production_output_cost_revision%ROWTYPE;
  wip_account text;
  order_dimension text;
  analytical_order text;
  command_date date;
  latest_sequence integer;
  original_cost numeric;
  invalid_count integer;
  evidence jsonb;
  actual_matrix jsonb;
  declared_matrix jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO original FROM accounting.production_output_transfer_receipt
    WHERE entry_id=NEW.original_entry_id AND organization_id=NEW.organization_id FOR UPDATE;
  IF NOT FOUND OR NEW.month IS DISTINCT FROM original.month
     OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.command->>'original_entry_id' IS DISTINCT FROM NEW.original_entry_id::text THEN
    RAISE EXCEPTION 'Output cost revision must bind the original receipt and request identity';
  END IF;
  BEGIN
    command_date := (NEW.command->>'posting_date')::date;
  EXCEPTION WHEN others THEN
    RAISE EXCEPTION 'Output cost revision command must retain a valid posting date';
  END;
  IF to_char(command_date,'YYYY-MM') IS DISTINCT FROM NEW.month THEN
    RAISE EXCEPTION 'Output cost revision command date must belong to the original period';
  END IF;
  wip_account := original.basis->'wip'->>'account';
  SELECT production_costing->>'order_dimension' INTO order_dimension
    FROM accounting.policy WHERE id=(original.basis->>'policy_id')::integer
      AND organization_id=NEW.organization_id;
  analytical_order := original.command->>'analytical_order';
  -- Output transfer policy convention requires the named analytic order.
  IF wip_account IS NULL OR order_dimension IS NULL OR analytical_order IS NULL THEN
    RAISE EXCEPTION 'Original output receipt lacks a source-bound WIP identity';
  END IF;
  SELECT * INTO original_entry FROM accounting.entry WHERE id=NEW.original_entry_id;
  SELECT amount INTO original_cost FROM accounting.line
    WHERE entry_id=NEW.original_entry_id AND side='debit' AND quantity IS NOT NULL;
  IF original_entry.organization_id IS DISTINCT FROM NEW.organization_id OR original_cost IS NULL
     OR original_entry.posting_date > command_date THEN
    RAISE EXCEPTION 'Original output receipt ledger package is invalid';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id
               AND month>=NEW.month AND closed) OR original_entry.policy_id IS DISTINCT FROM
      (SELECT id FROM accounting.policy WHERE organization_id=NEW.organization_id AND effective_from<=command_date
       ORDER BY effective_from DESC LIMIT 1) THEN
    RAISE EXCEPTION 'Output cost revision requires the original policy and an open period';
  END IF;
  PERFORM 1 FROM accounting.production_output_cost_revision
    WHERE original_entry_id=NEW.original_entry_id FOR UPDATE;
  SELECT coalesce(max(sequence),0) INTO latest_sequence
    FROM accounting.production_output_cost_revision
    WHERE original_entry_id=NEW.original_entry_id;
  IF NEW.sequence <= 0 OR NEW.sequence <> latest_sequence + 1 THEN
    RAISE EXCEPTION 'Output cost revision sequence must append exactly once';
  END IF;
  IF NEW.sequence = 1 THEN
    IF NEW.previous_id IS NOT NULL THEN
      RAISE EXCEPTION 'First output cost revision cannot have a predecessor';
    END IF;
  ELSE
    SELECT * INTO previous FROM accounting.production_output_cost_revision
      WHERE id=NEW.previous_id AND organization_id=NEW.organization_id
        AND original_entry_id=NEW.original_entry_id AND sequence=NEW.sequence-1 FOR UPDATE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Output cost revision predecessor must be the immediately prior verified revision';
    END IF;
  END IF;
  evidence := accounting.output_cost_revision_evidence(NEW.organization_id, NEW.original_entry_id, command_date, NEW.entry_id);
  IF NEW.preview::jsonb->'ledger_evidence' IS DISTINCT FROM evidence THEN
    RAISE EXCEPTION 'Output revision preview differs from authenticated ledger evidence';
  END IF;
  IF evidence->'matrix'='[]'::jsonb THEN
    IF NEW.entry_id IS NOT NULL OR NEW.posting IS NOT NULL THEN
      RAISE EXCEPTION 'Empty correction matrix must not create an entry';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO correction_entry FROM accounting.entry WHERE id=NEW.entry_id;
  IF correction_entry.organization_id IS DISTINCT FROM NEW.organization_id
     OR correction_entry.operation IS DISTINCT FROM 'production_output_cost_correction'
     OR correction_entry.correction_of IS DISTINCT FROM NEW.original_entry_id
     OR correction_entry.source IS DISTINCT FROM ('production:output-cost-revision:'||NEW.organization_id||':'||NEW.original_entry_id||':'||NEW.sequence)
     OR correction_entry.source_version <> 1 OR correction_entry.actor IS DISTINCT FROM NEW.actor
     OR (NEW.sequence>1 AND correction_entry.id<=previous.registration_token)
     OR correction_entry.posting_date IS DISTINCT FROM command_date
     OR correction_entry.policy_id IS DISTINCT FROM original_entry.policy_id
     OR correction_entry.opening OR NEW.posting IS NULL
     OR EXISTS (SELECT 1 FROM jsonb_each(to_jsonb(correction_entry)) f
       WHERE f.key IN ('source','source_version','operation','document_date','operation_date',
                       'posting_date','policy_id','rule_version','explanation','opening','correction_of')
         AND NEW.posting::jsonb->f.key IS DISTINCT FROM f.value) THEN
    RAISE EXCEPTION 'Output cost revision ledger entry is not source-bound to its original output';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'dimensions',dimensions::jsonb,
      'side',side,'amount',amount) ORDER BY account_code,dimensions::jsonb::text),'[]'::jsonb),
      count(*) FILTER (WHERE quantity IS NOT NULL OR currency<>'BYN' OR cash OR cash_activity IS NOT NULL
        OR original_amount IS NOT NULL OR rate IS NOT NULL OR rate_scale IS NOT NULL
        OR rate_date IS NOT NULL OR rate_source IS NOT NULL)
    INTO actual_matrix, invalid_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',r->>'account','dimensions',r->'dimensions',
      'side',r->>'side','amount',(r->>'amount')::numeric)
      ORDER BY r->>'account',(r->'dimensions')::text),'[]'::jsonb)
    INTO declared_matrix FROM jsonb_array_elements(NEW.posting::jsonb->'lines') r;
  IF actual_matrix IS DISTINCT FROM evidence->'matrix' OR declared_matrix IS DISTINCT FROM actual_matrix
      OR invalid_count<>0 OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.posting::jsonb->'lines') r
        WHERE r->>'currency' IS DISTINCT FROM 'BYN' OR r->>'quantity' IS NOT NULL
          OR r->>'original_amount' IS NOT NULL OR r->>'rate' IS NOT NULL
          OR r->>'rate_scale' IS NOT NULL OR r->>'rate_date' IS NOT NULL
          OR r->>'rate_source' IS NOT NULL OR r->>'cash_activity' IS NOT NULL
      ) THEN
    RAISE EXCEPTION 'Output correction matrix differs from authenticated destinations';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_output_cost_revision
BEFORE INSERT ON accounting.production_output_cost_revision
FOR EACH ROW EXECUTE FUNCTION accounting.guard_output_cost_revision();


-- Check the whole package at transaction end as lines may be inserted after
-- the receipt. The receipt INSERT guard alone cannot enforce completeness.
CREATE OR REPLACE FUNCTION accounting.check_output_cost_revision_complete() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  target integer;
  e accounting.entry%ROWTYPE;
  receipt accounting.production_output_cost_revision%ROWTYPE;
  actual jsonb;
  invalid integer;
BEGIN
  IF TG_TABLE_NAME='entry' THEN target := NEW.id;
  ELSE target := NEW.entry_id; END IF;
  IF target IS NULL THEN RETURN NULL; END IF;
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF NOT FOUND OR e.operation<>'production_output_cost_correction' THEN RETURN NULL; END IF;
  SELECT * INTO receipt FROM accounting.production_output_cost_revision WHERE entry_id=target;
  IF NOT FOUND OR receipt.organization_id IS DISTINCT FROM e.organization_id THEN
    RAISE EXCEPTION 'Output cost correction requires its complete revision receipt';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'dimensions',dimensions::jsonb,
      'side',side,'amount',amount) ORDER BY account_code,dimensions::jsonb::text),'[]'::jsonb),
      count(*) FILTER (WHERE quantity IS NOT NULL OR currency<>'BYN' OR cash OR cash_activity IS NOT NULL
        OR original_amount IS NOT NULL OR rate IS NOT NULL OR rate_scale IS NOT NULL
        OR rate_date IS NOT NULL OR rate_source IS NOT NULL)
    INTO actual,invalid FROM accounting.line WHERE entry_id=target;
  IF actual IS DISTINCT FROM receipt.preview::jsonb->'ledger_evidence'->'matrix' OR invalid<>0 THEN
    RAISE EXCEPTION 'Output correction matrix differs from authenticated destinations at commit';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER output_cost_revision_entry_complete
AFTER INSERT ON accounting.entry DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_output_cost_revision_complete();
CREATE CONSTRAINT TRIGGER output_cost_revision_line_complete
AFTER INSERT ON accounting.line DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_output_cost_revision_complete();
CREATE CONSTRAINT TRIGGER output_cost_revision_receipt_complete
AFTER INSERT ON accounting.production_output_cost_revision DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_output_cost_revision_complete();

CREATE OR REPLACE FUNCTION accounting.reject_output_cost_revision_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Production output cost revisions are immutable'; END $$;
CREATE TRIGGER immutable_output_cost_revision
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.production_output_cost_revision
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_output_cost_revision_mutation();
"""


def upgrade():
    op.execute(DDL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.production_output_cost_revision) THEN
        RAISE EXCEPTION 'Cannot downgrade output cost revisions while accounting history exists';
      END IF;
    END $$;
    DROP TRIGGER output_cost_revision_entry_complete ON accounting.entry;
    DROP TRIGGER output_cost_revision_line_complete ON accounting.line;
    DROP TABLE accounting.production_output_cost_revision;
    DROP FUNCTION accounting.check_output_cost_revision_complete();
    DROP FUNCTION accounting.guard_output_cost_revision();
    DROP FUNCTION accounting.register_output_cost_revision();
    DROP FUNCTION accounting.reject_output_cost_revision_mutation();
    DROP FUNCTION accounting.output_cost_revision_evidence(integer,integer,date,integer);
    DROP FUNCTION accounting.output_pool_revision_rows(integer,integer,date,integer);
    """)
