"""Authenticated policy finished goods in whole-act shipments.

Historical 41 receipts retain their frozen contract. The saved production basis
digest is opaque: its original envelope is not the transformed receipt basis.
"""
import runpy
from pathlib import Path

from alembic import op

revision = "crm_rel_001_finished_goods_01"
down_revision = "crm_rel_001_joint_01"
branch_labels = None
depends_on = None


def function(ddl, name):
    start = ddl.index(f"CREATE OR REPLACE FUNCTION accounting.{name}(")
    end = ddl.index("END $$;", start) + len("END $$;")
    return ddl[start:end]


def replace_once(value, old, new):
    if value.count(old) != 1:
        raise RuntimeError(f"Finished-goods anchor must occur once: {old[:80]}")
    return value.replace(old, new)


def frozen(name):
    return runpy.run_path(str(Path(__file__).with_name(name)))["DDL"]


def source_query():
    # Reuse only the strict WIP evidence portion, not the disposal/allocation
    # engine (which does not admit whole-act shipment receipts).
    old = function(frozen("0139_production_output_cost_revision.py"), "output_cost_revision_evidence")
    start = old.index("  SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id', e.id")
    end = old.index("  SELECT coalesce(jsonb_agg(jsonb_build_object('dimensions', dims", start)
    query = old[start:end]
    query = replace_once(query, "'posting_date', e.posting_date, 'account'", "'source',e.source,'opening',e.opening,'posting_date', e.posting_date, 'account'")
    # Same registration boundary as 0141; excluded_entry is the shipment anchor.
    query = query.replace("AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)",
                          "AND e.id<>output_id AND e.id<excluded_entry")
    query = query.replace("WHERE r.original_entry_id=output_id AND r.entry_id=e.id)",
                          "WHERE r.original_entry_id=output_id AND r.organization_id=org AND r.entry_id=e.id "
                          "AND r.registration_token<excluded_entry AND (r.command->>'posting_date')::date<=cutoff)")
    return query


HELPER = """
CREATE OR REPLACE FUNCTION accounting.validate_shipment_output_layer(
  org integer, output_id integer, output_line integer, account text, cutoff date, excluded_entry integer
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE receipt accounting.production_output_transfer_receipt; output_entry accounting.entry; origin accounting.line;
        p accounting.policy; basis jsonb; posting jsonb; wip text; order_key text; order_value text;
        required_keys jsonb; source_rows jsonb; source_cost numeric; expected_source jsonb;
        live_trace jsonb; saved_trace jsonb; revision_row accounting.production_output_cost_revision;
        correction accounting.entry; previous_id integer:=NULL; sequence_no integer:=0;
        previous_token integer:=0; matrix jsonb; actual_matrix jsonb; credits jsonb; groups jsonb;
BEGIN
  SELECT * INTO receipt FROM accounting.production_output_transfer_receipt
    WHERE organization_id=org AND entry_id=output_id;
  SELECT * INTO output_entry FROM accounting.entry WHERE id=output_id;
  SELECT * INTO origin FROM accounting.line WHERE id=output_line AND entry_id=output_id;
  IF receipt.entry_id IS NULL OR output_entry.id IS NULL OR origin.id IS NULL THEN
    RAISE EXCEPTION 'Shipment finished goods require an immutable output receipt';
  END IF;
  basis:=receipt.basis::jsonb; posting:=receipt.posting::jsonb;
  SELECT * INTO p FROM accounting.policy WHERE organization_id=org AND effective_from<=output_entry.posting_date
    ORDER BY effective_from DESC LIMIT 1;
  IF output_entry.organization_id IS DISTINCT FROM org OR output_entry.posting_date>cutoff OR output_entry.id>=excluded_entry
     OR output_entry.operation IS DISTINCT FROM 'production_output_transfer' OR output_entry.source_version IS DISTINCT FROM 1
     OR output_entry.source IS DISTINCT FROM 'production:output-transfer:'||org||':'||receipt.order_id
     OR output_entry.actor IS DISTINCT FROM receipt.actor OR output_entry.opening OR output_entry.correction_of IS NOT NULL
     OR output_entry.rule_version IS DISTINCT FROM 'production-output-transfer-v1'
     OR p.id IS NULL OR p.id IS DISTINCT FROM output_entry.policy_id
     OR p.production_costing->>'finished_goods_account' IS DISTINCT FROM account
     OR basis->>'organization_id' IS DISTINCT FROM org::text OR basis->>'policy_id' IS DISTINCT FROM p.id::text
     OR receipt.command->>'policy_id' IS DISTINCT FROM p.id::text
     OR receipt.command->>'order_id' IS DISTINCT FROM receipt.order_id::text
     OR basis->'order'->>'order_id' IS DISTINCT FROM receipt.order_id::text
     OR basis->>'month' IS DISTINCT FROM receipt.month
     OR receipt.command->>'analytical_order' IS DISTINCT FROM basis->>'analytical_order'
     OR receipt.command->>'warehouse' IS DISTINCT FROM basis->>'warehouse'
     OR receipt.command->>'basis_digest' IS DISTINCT FROM receipt.basis_digest
     OR basis->>'basis_digest' IS DISTINCT FROM receipt.basis_digest
     OR receipt.command->>'digest' IS DISTINCT FROM receipt.digest
     OR output_entry.digest IS DISTINCT FROM receipt.digest OR accounting.financial_sha(posting) IS DISTINCT FROM receipt.digest
     OR accounting.posting_body_projection(accounting.financial_posting_body(output_entry.id),false)
        IS DISTINCT FROM accounting.posting_body_projection(posting,false) THEN
    RAISE EXCEPTION 'Shipment output receipt provenance differs from its complete posting';
  END IF;
  IF (SELECT count(*) FROM accounting.line WHERE entry_id=output_id AND side='debit')<>1
     OR origin.side IS DISTINCT FROM 'debit' OR origin.account_code IS DISTINCT FROM account
     OR origin.currency IS DISTINCT FROM 'BYN' OR origin.cash OR origin.category IS DISTINCT FROM 'asset'
     OR (origin.quantity>0 AND origin.amount>0) IS NOT TRUE
     OR origin.amount IS DISTINCT FROM (basis->>'candidate_transfer_byn')::numeric
     OR origin.amount IS DISTINCT FROM (basis->'wip'->>'balance_byn')::numeric
     OR origin.quantity IS DISTINCT FROM (basis->'output'->>'accepted_quantity')::numeric
     OR origin.quantity IS DISTINCT FROM (basis->'output'->>'planned_quantity')::numeric
     OR origin.quantity IS DISTINCT FROM (basis->'output'->>'confirmed_quantity')::numeric
     OR (basis->'output'->>'rejected_quantity')::numeric IS DISTINCT FROM 0::numeric
     OR (basis->'output'->>'pending_quantity')::numeric IS DISTINCT FROM 0::numeric
     OR basis->'target'->>'finished_goods_account' IS DISTINCT FROM account
     OR origin.dimensions->>'warehouse' IS DISTINCT FROM receipt.command->>'warehouse'
     OR origin.dimensions->>'sku' IS DISTINCT FROM basis->'output'->>'sku_code'
     OR origin.dimensions->>'lot' IS DISTINCT FROM basis->'output'->>'lot'
     OR nullif(btrim(origin.dimensions->>'warehouse'),'') IS NULL
     OR nullif(btrim(origin.dimensions->>'sku'),'') IS NULL OR nullif(btrim(origin.dimensions->>'lot'),'') IS NULL THEN
    RAISE EXCEPTION 'Shipment output requires one complete positive finished-goods debit';
  END IF;
  wip:=basis->'wip'->>'account'; order_value:=receipt.command->>'analytical_order';
  order_key:=p.production_costing->>'order_dimension';
  required_keys:=(p.production_costing->'pool_dimensions')::jsonb||jsonb_build_array(order_key);
  IF wip IS DISTINCT FROM p.production_costing->>'wip_account' OR wip IS NULL
     OR nullif(btrim(order_key),'') IS NULL OR nullif(btrim(order_value),'') IS NULL
     OR jsonb_typeof(basis->'wip'->'source_lines') IS DISTINCT FROM 'array'
     OR jsonb_typeof(basis->'wip'->'groups') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment output source policy is unavailable';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('dimensions',dimensions::jsonb,'amount',amount)
      ORDER BY dimensions::jsonb::text),'[]'::jsonb) INTO credits FROM accounting.line
    WHERE entry_id=output_id AND side='credit';
  SELECT coalesce(jsonb_agg(jsonb_build_object('dimensions',g->'dimensions','amount',(g->>'balance_byn')::numeric)
      ORDER BY (g->'dimensions')::text),'[]'::jsonb) INTO groups FROM jsonb_array_elements(basis->'wip'->'groups') g;
  IF credits IS DISTINCT FROM groups OR jsonb_array_length(groups)=0
     OR EXISTS (SELECT 1 FROM accounting.line WHERE entry_id=output_id AND side='credit'
          AND (account_code<>wip OR quantity IS NOT NULL OR currency<>'BYN' OR cash OR category<>'asset' OR amount<=0))
     OR (SELECT sum((g->>'amount')::numeric) FROM jsonb_array_elements(groups) g) IS DISTINCT FROM origin.amount THEN
    RAISE EXCEPTION 'Shipment output WIP credits differ from immutable groups';
  END IF;
  expected_source:=basis->'wip'->'source_lines';
  FOR revision_row IN SELECT * FROM accounting.production_output_cost_revision
    WHERE organization_id=org AND original_entry_id=output_id AND registration_token<excluded_entry
      AND (command->>'posting_date')::date<=cutoff ORDER BY sequence LOOP
    sequence_no:=sequence_no+1;
    matrix:=revision_row.preview::jsonb->'ledger_evidence'->'matrix';
    IF revision_row.sequence<>sequence_no OR revision_row.previous_id IS DISTINCT FROM previous_id
       OR revision_row.registration_token<=previous_token OR jsonb_typeof(matrix) IS DISTINCT FROM 'array' THEN
      RAISE EXCEPTION 'Shipment output revision chain is not verified';
    END IF;
    IF revision_row.entry_id IS NULL THEN
      IF matrix<>'[]'::jsonb OR revision_row.posting IS NOT NULL THEN
        RAISE EXCEPTION 'Shipment empty output revision contains posting';
      END IF;
    ELSE
      SELECT * INTO correction FROM accounting.entry WHERE id=revision_row.entry_id;
      SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'dimensions',dimensions::jsonb,
          'side',side,'amount',amount) ORDER BY account_code,dimensions::jsonb::text),'[]'::jsonb)
        INTO actual_matrix FROM accounting.line WHERE entry_id=revision_row.entry_id;
      IF correction.id IS NULL OR correction.organization_id IS DISTINCT FROM org
         OR correction.operation IS DISTINCT FROM 'production_output_cost_correction'
         OR correction.correction_of IS DISTINCT FROM output_id OR correction.actor IS DISTINCT FROM revision_row.actor
         OR correction.source IS DISTINCT FROM 'production:output-cost-revision:'||org||':'||output_id||':'||revision_row.sequence
         OR revision_row.registration_token<=correction.id OR actual_matrix IS DISTINCT FROM matrix
         OR accounting.financial_sha(revision_row.posting::jsonb) IS DISTINCT FROM correction.digest
         OR accounting.posting_body_projection(accounting.financial_posting_body(correction.id),false)
            IS DISTINCT FROM accounting.posting_body_projection(revision_row.posting::jsonb,false) THEN
        RAISE EXCEPTION 'Shipment output revision differs from authenticated posting';
      END IF;
    END IF;
    expected_source:=revision_row.preview::jsonb->'ledger_evidence'->'source_lines';
    previous_id:=revision_row.id; previous_token:=revision_row.registration_token;
  END LOOP;
  -- Strict source query is inserted here from the immutable 0139 definition.
  __SOURCE_QUERY__
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(source_rows) r,
      LATERAL jsonb_each(r->'dimensions') d WHERE jsonb_typeof(d.value)<>'string' OR nullif(btrim(d.value#>>'{}'),'') IS NULL)
     OR jsonb_typeof(expected_source) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment output WIP trace is unavailable';
  END IF;
  IF sequence_no=0 THEN
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(expected_source) r WHERE
      (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(r) k) IS DISTINCT FROM
        ARRAY['amount_byn','dimensions','entry_id','line_id','opening','posting_date','side','source']::text[]) THEN
      RAISE EXCEPTION 'Shipment original output trace format is invalid';
    END IF;
    SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id',r->'entry_id','line_id',r->'line_id',
      'source',r->'source','opening',r->'opening','posting_date',r->'posting_date','side',r->'side',
      'amount',(r->>'amount')::numeric,'dimensions',r->'dimensions') ORDER BY (r->>'entry_id')::integer,(r->>'line_id')::integer),'[]'::jsonb)
      INTO live_trace FROM jsonb_array_elements(source_rows) r;
    SELECT coalesce(jsonb_agg((r-'amount_byn')||jsonb_build_object('amount',(r->>'amount_byn')::numeric)
      ORDER BY (r->>'entry_id')::integer,(r->>'line_id')::integer),'[]'::jsonb)
      INTO saved_trace FROM jsonb_array_elements(expected_source) r;
  ELSE
    SELECT coalesce(jsonb_agg(r-ARRAY['source','opening'] ORDER BY (r->>'entry_id')::integer,(r->>'line_id')::integer),'[]'::jsonb)
      INTO live_trace FROM jsonb_array_elements(source_rows) r;
    SELECT coalesce(jsonb_agg(r ORDER BY (r->>'entry_id')::integer,(r->>'line_id')::integer),'[]'::jsonb)
      INTO saved_trace FROM jsonb_array_elements(expected_source) r;
  END IF;
  IF live_trace IS DISTINCT FROM saved_trace THEN
    RAISE EXCEPTION 'Shipment output WIP source basis is stale';
  END IF;
  IF sequence_no=0 AND source_cost IS DISTINCT FROM origin.amount THEN
    RAISE EXCEPTION 'Shipment output amount differs from its original WIP source';
  END IF;
END $$;
"""


def definitions():
    old = frozen("0130_accounting_ledger.py")
    costs = function(old, "validate_shipment_costs")
    allowed = "(bucket.account ~ '^43([.]|$)' AND bucket.account=policy.production_costing->>'finished_goods_account')"
    costs = replace_once(costs, "bucket.account !~ '^41([.]|$)' OR nullif(bucket.lot,'') IS NULL",
                         f"(bucket.account !~ '^41([.]|$)' AND ({allowed}) IS NOT TRUE) OR nullif(bucket.lot,'') IS NULL")
    costs = replace_once(costs, "AND NOT(e.source=r.source OR starts_with(e.source,r.source||':part:'))",
                         "AND NOT(e.source=r.source OR starts_with(e.source,r.source||':part:'))\n"
                         "        AND (bucket.account ~ '^41([.]|$)' OR e.id<r.anchor_entry_id)")
    costs = replace_once(costs, "      value_only:=movement.quantity IS NULL;", """      IF bucket.account ~ '^43([.]|$)' AND movement.side='debit' AND movement.quantity IS NOT NULL THEN
        PERFORM accounting.validate_shipment_output_layer(r.organization_id,movement.entry_id,movement.id,
          bucket.account,posting_day,r.anchor_entry_id);
      END IF;
      value_only:=movement.quantity IS NULL;""")
    eligible = "(l.account_code ~ '^41([.]|$)' OR (l.account_code ~ '^43([.]|$)' AND " \
               "l.account_code=(SELECT production_costing->>'finished_goods_account' FROM accounting.policy " \
               "WHERE id=(r.command->>'policy_id')::integer AND organization_id=r.organization_id)) OR l.account_code ~ '^90[.]4([.]|$)')"
    costs = replace_once(costs, "l.account_code ~ '^(41|90[.]4)([.]|$)'", eligible)
    receipt = function(old, "validate_shipment_receipt")
    receipt = replace_once(receipt, "inventory_line:=line_row.account_code ~ '^41([.]|$)';",
                           "inventory_line:=line_row.account_code ~ '^41([.]|$)' OR "
                           "(line_row.account_code ~ '^43([.]|$)' AND line_row.account_code="
                           "(SELECT production_costing->>'finished_goods_account' FROM accounting.policy "
                           "WHERE id=entry_row.policy_id AND organization_id=r.organization_id));")
    receipt = replace_once(receipt, "l.account_code !~ '^(41|90[.]4)([.]|$)'", "NOT " + eligible)
    return HELPER.replace("  __SOURCE_QUERY__", source_query()) + costs + "\n" + receipt


def upgrade():
    op.execute(definitions())


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.shipment_accounting_receipt r
          CROSS JOIN LATERAL jsonb_array_elements(r.command::jsonb->'allocations') a
          WHERE a->>'account' ~ '^43([.]|$)') THEN
        RAISE EXCEPTION 'Cannot downgrade finished-goods shipment history; restore a verified backup instead';
      END IF;
    END $$;""")
    old = frozen("0130_accounting_ledger.py")
    op.execute(function(old, "validate_shipment_costs"))
    op.execute(function(old, "validate_shipment_receipt"))
    op.execute("DROP FUNCTION accounting.validate_shipment_output_layer(integer,integer,integer,text,date,integer)")
