"""Versioned, entryless WMS-bound zero material allocations."""
import runpy
from pathlib import Path

from alembic import op

revision = "0150"
down_revision = "0149"
branch_labels = None
depends_on = None


# Frozen full historical basis, derived from revision 0146.
MATERIAL_BASIS = r"""
CREATE FUNCTION accounting.zero_value_material_allocation_basis(org integer, c jsonb, cutoff_token integer)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE b jsonb; m wms.stock_movement%ROWTYPE; i wms.production_material_issue%ROWTYPE; d jsonb; layer jsonb; field text; day date; source_row jsonb; sources jsonb:='[]'::jsonb;
  policy_row jsonb; account_row jsonb; destination_row jsonb; history jsonb; zeros jsonb;
  issues jsonb; sales jsonb; outputs jsonb; revisions jsonb; total numeric:=0; seen text[]:=ARRAY[]::text[]; identity text;
BEGIN
  IF org IS NULL OR org<=0 OR cutoff_token IS NULL OR cutoff_token<=0
    OR jsonb_typeof(c) IS DISTINCT FROM 'object' OR c->>'command_version' IS DISTINCT FROM '5'
    OR jsonb_typeof(c->'command_version') IS DISTINCT FROM 'number'
    OR jsonb_typeof(c->'valuation_method') IS DISTINCT FROM 'string'
    OR c->>'valuation_method' NOT IN ('fifo','weighted_average') OR NOT c ? 'valuation_method'
    OR jsonb_typeof(c->'operation') IS DISTINCT FROM 'string'
    OR c->>'operation' NOT IN ('inventory_issue','inventory_sale') OR NOT c ? 'operation'
    OR jsonb_typeof(c->'document') IS DISTINCT FROM 'object'
    OR jsonb_typeof(c->'inventory_layers') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'V5 material allocation basis requires a complete versioned command';
  END IF;
  IF jsonb_array_length(c->'inventory_layers') NOT BETWEEN 1 AND 1000 THEN
    RAISE EXCEPTION 'V5 material allocation basis requires bounded source layers';
  END IF;
  PERFORM 1 FROM accounting.organization WHERE id=org FOR UPDATE;
  d:=c->'document';
 b:=c->'material_binding';
 IF jsonb_typeof(b) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'V5 material binding must be an object';
 END IF;
 IF (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(b) k) IS DISTINCT FROM
    ARRAY['binding_id','lot','movement_id','order_id','quantity','request_key','sku','warehouse'] THEN
   RAISE EXCEPTION 'V5 material binding fields are invalid';
 END IF;
 FOREACH field IN ARRAY ARRAY['binding_id','order_id','movement_id'] LOOP
   IF jsonb_typeof(b->field) IS DISTINCT FROM 'number' OR b->>field !~ '^[1-9][0-9]*$' THEN
     RAISE EXCEPTION 'V5 material binding identities must be positive integers';
   END IF;
 END LOOP;
 FOREACH field IN ARRAY ARRAY['request_key','warehouse','sku','lot','quantity'] LOOP
   IF jsonb_typeof(b->field) IS DISTINCT FROM 'string' OR coalesce(b->>field,'')='' THEN
     RAISE EXCEPTION 'V5 material binding text is invalid';
   END IF;
 END LOOP;
 IF b->>'quantity' !~ '^(0|[1-9][0-9]*)[.][0-9]{6}$' OR (b->>'quantity')::numeric<=0 THEN
   RAISE EXCEPTION 'V5 material binding quantity must have six decimals';
 END IF;
 SELECT * INTO i FROM wms.production_material_issue WHERE id=(b->>'binding_id')::integer AND organization_id=org
   AND order_id=(b->>'order_id')::integer AND movement_id=(b->>'movement_id')::integer AND request_key=b->>'request_key' FOR UPDATE;
 SELECT * INTO m FROM wms.stock_movement WHERE id=(b->>'movement_id')::integer AND organization_id=org FOR UPDATE;
 IF i.id IS NULL OR m.id IS NULL OR c->>'source' IS DISTINCT FROM ('production:material:'||org||':'||i.request_key)
   OR m.kind IS DISTINCT FROM 'out' OR m.reason IS DISTINCT FROM 'production_issue'
   OR m.warehouse IS DISTINCT FROM b->>'warehouse' OR m.sku_code IS DISTINCT FROM b->>'sku' OR m.batch_ref IS DISTINCT FROM b->>'lot'
   OR m.qty IS DISTINCT FROM (b->>'quantity')::numeric THEN RAISE EXCEPTION 'V5 material binding is not authenticated'; END IF;

 IF c->>'operation' IS DISTINCT FROM 'inventory_issue'
   OR c->>'source_version' IS DISTINCT FROM '1'
   OR c->>'operation_date' IS DISTINCT FROM i.operation_date::text
   OR c->>'document_date' IS DISTINCT FROM i.operation_date::text
   OR m.doc_ref IS DISTINCT FROM ('production_material:'||i.request_key)
   OR d->>'warehouse' IS DISTINCT FROM m.warehouse OR d->>'sku' IS DISTINCT FROM m.sku_code
   OR d->>'lot' IS DISTINCT FROM m.batch_ref OR (d->>'quantity')::numeric IS DISTINCT FROM m.qty
   OR i.snapshot::jsonb->'movement' IS DISTINCT FROM jsonb_build_object(
     'id',m.id,'organization_id',m.organization_id,'sku_code',m.sku_code,'warehouse',m.warehouse,
     'kind',m.kind,'qty',to_char(m.qty,'FM9999999999999999990.00'),'reason',m.reason,
     'location_id',m.location_id,'lot',m.batch_ref,'doc_ref',m.doc_ref) THEN
   RAISE EXCEPTION 'V5 document differs from immutable material movement';
 END IF;

  FOREACH field IN ARRAY ARRAY['source','source_version','document_date','operation_date','posting_date','policy_id','explanation'] LOOP
    IF NOT c ? field OR c->field IS DISTINCT FROM d->field THEN
      RAISE EXCEPTION 'V5 material allocation document metadata differ';
    END IF;
  END LOOP;
  FOREACH field IN ARRAY ARRAY['source_version','policy_id'] LOOP
    IF jsonb_typeof(c->field) IS DISTINCT FROM 'number' OR c->>field !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'V5 material allocation identities must be positive integers';
    END IF;
  END LOOP;
  IF jsonb_typeof(c->'source') IS DISTINCT FROM 'string' OR c->>'source' !~ '^[^[:space:]]{1,160}$'
    OR jsonb_typeof(c->'basis_digest') IS DISTINCT FROM 'string' OR c->>'basis_digest' !~ '^[0-9a-f]{64}$'
    OR jsonb_typeof(c->'explanation') IS DISTINCT FROM 'string' OR length(btrim(c->>'explanation')) NOT BETWEEN 1 AND 1000
    OR c->'destination_account' IS DISTINCT FROM d->'expense_account'
    OR c->'destination_dimensions' IS DISTINCT FROM d->'expense_dimensions'
    OR jsonb_typeof(c->'destination_account') IS DISTINCT FROM 'string'
    OR jsonb_typeof(c->'destination_dimensions') IS DISTINCT FROM 'object'
    OR jsonb_typeof(d->'quantity') IS DISTINCT FROM 'string'
    OR d->>'quantity' !~ '^(0|[1-9][0-9]{0,17})([.][0-9]{1,6})?$'
    OR (d->>'quantity')::numeric<=0 THEN
    RAISE EXCEPTION 'V5 material allocation document quantity or destination is invalid';
  END IF;
  FOREACH field IN ARRAY ARRAY['account','warehouse','sku'] LOOP
    IF jsonb_typeof(d->field) IS DISTINCT FROM 'string' OR coalesce(btrim(d->>field),'')='' THEN
      RAISE EXCEPTION 'V5 material allocation inventory pool is incomplete';
    END IF;
  END LOOP;
  IF jsonb_typeof(d->'lot') IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'V5 material allocation lot must be explicit or empty'; END IF;
  FOREACH field IN ARRAY ARRAY['document_date','operation_date','posting_date'] LOOP
    IF jsonb_typeof(c->field) IS DISTINCT FROM 'string' OR c->>field !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      OR to_char((c->>field)::date,'YYYY-MM-DD') IS DISTINCT FROM c->>field THEN
      RAISE EXCEPTION 'V5 material allocation date is invalid';
    END IF;
  END LOOP;
  day:=(c->>'posting_date')::date;
  SELECT to_jsonb(p) INTO policy_row FROM accounting.policy p WHERE p.organization_id=org
    AND p.id=(c->>'policy_id')::integer AND p.inventory_method=c->>'valuation_method' AND p.effective_from<=day
    AND NOT EXISTS (SELECT 1 FROM accounting.policy n WHERE n.organization_id=org AND n.effective_from<=day AND n.effective_from>p.effective_from);
  SELECT to_jsonb(a) INTO account_row FROM accounting.account a WHERE a.organization_id=org AND a.code=d->>'account'
    AND a.valid_from<=day ORDER BY a.valid_from DESC LIMIT 1;
  SELECT to_jsonb(a) INTO destination_row FROM accounting.account a WHERE a.organization_id=org AND a.code=c->>'destination_account'
    AND a.valid_from<=day ORDER BY a.valid_from DESC LIMIT 1;
  IF policy_row IS NULL OR account_row IS NULL OR destination_row IS NULL
    OR account_row->>'category' IS DISTINCT FROM 'asset' OR account_row->'cash' IS DISTINCT FROM 'false'::jsonb
    OR account_row->'quantity_tracking' IS DISTINCT FROM 'true'::jsonb
    OR destination_row->'cash' IS DISTINCT FROM 'false'::jsonb OR destination_row->'quantity_tracking' IS DISTINCT FROM 'false'::jsonb
    OR destination_row->>'category' IS DISTINCT FROM 'asset'
    OR policy_row->'production_costing'->>'wip_account' IS DISTINCT FROM c->>'destination_account' THEN
    RAISE EXCEPTION 'V5 material allocation applicable policy or owned accounts are unavailable';
  END IF;
  IF (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_object_keys(c->'destination_dimensions') k)
    IS DISTINCT FROM (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_array_elements_text(destination_row->'required_dimensions') k)
    OR EXISTS (SELECT 1 FROM jsonb_each(c->'destination_dimensions') x WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string'
      OR length(btrim(x.value #>> '{}')) NOT BETWEEN 1 AND 200) THEN
    RAISE EXCEPTION 'V5 material allocation destination analytics are invalid';
  END IF;
  FOR layer IN SELECT value FROM jsonb_array_elements(c->'inventory_layers') LOOP
    IF jsonb_typeof(layer) IS DISTINCT FROM 'object'
      OR jsonb_typeof(layer->'source_entry_id') IS DISTINCT FROM 'number' OR layer->>'source_entry_id' !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(layer->'source_line_id') IS DISTINCT FROM 'number' OR layer->>'source_line_id' !~ '^[1-9][0-9]*$'
      OR layer->'inventory_account' IS DISTINCT FROM d->'account'
      OR jsonb_typeof(layer->'inventory_dimensions') IS DISTINCT FROM 'object'
      OR layer->'inventory_dimensions'->'warehouse' IS DISTINCT FROM d->'warehouse'
      OR layer->'inventory_dimensions'->'sku' IS DISTINCT FROM d->'sku'
      OR jsonb_typeof(layer->'inventory_dimensions'->'lot') IS DISTINCT FROM 'string'
      OR coalesce(btrim(layer->'inventory_dimensions'->>'lot'),'')=''
      OR (d->>'lot'<>'' AND layer->'inventory_dimensions'->'lot' IS DISTINCT FROM d->'lot')
      OR jsonb_typeof(layer->'quantity') IS DISTINCT FROM 'string'
      OR layer->>'quantity' !~ '^(0|[1-9][0-9]{0,17})([.][0-9]{1,6})?$' OR (layer->>'quantity')::numeric<=0 THEN
      RAISE EXCEPTION 'V5 material allocation source identity or quantity is invalid';
    END IF;
    identity:=(layer->>'source_entry_id')||':'||(layer->>'source_line_id');
    IF identity=ANY(seen) THEN RAISE EXCEPTION 'V5 material allocation repeats an origin'; END IF;
    seen:=array_append(seen,identity); total:=total+(layer->>'quantity')::numeric;
    SELECT jsonb_build_object('entry',to_jsonb(e),'line',to_jsonb(l)) INTO source_row
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=org AND e.id=(layer->>'source_entry_id')::integer AND l.id=(layer->>'source_line_id')::integer
        AND e.id<cutoff_token AND e.posting_date<=day AND e.operation='inventory_purchase'
        AND l.side='debit' AND l.account_code=d->>'account' AND l.dimensions::jsonb=layer->'inventory_dimensions'
        AND l.quantity>=(layer->>'quantity')::numeric AND l.currency='BYN' AND l.category='asset' AND NOT l.cash;
    IF source_row IS NULL THEN RAISE EXCEPTION 'V5 material allocation source is not a prior inventory purchase'; END IF;
    sources:=sources||jsonb_build_array(source_row);
  END LOOP;
  IF total IS DISTINCT FROM (d->>'quantity')::numeric THEN RAISE EXCEPTION 'V5 material allocation quantity is not conserved'; END IF;
  -- Include all registrations in this pool, also future-dated ones: chronological
  -- replay must reject them, not hide them from the approval fingerprint.
  SELECT coalesce(jsonb_agg(jsonb_build_object('entry',to_jsonb(e),'line',to_jsonb(l)) ORDER BY e.posting_date,e.id,l.id),'[]'::jsonb)
    INTO history FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.id<cutoff_token AND l.account_code=d->>'account'
      AND l.dimensions->>'warehouse'=d->>'warehouse' AND l.dimensions->>'sku'=d->>'sku';
  SELECT coalesce(jsonb_agg(to_jsonb(z) ORDER BY z.registration_token,z.id),'[]'::jsonb) INTO zeros
    FROM accounting.inventory_zero_value_disposal_receipt z WHERE z.organization_id=org AND z.registration_token<cutoff_token
      AND EXISTS (SELECT 1 FROM jsonb_array_elements(z.command::jsonb->'inventory_layers') x
        WHERE x->>'inventory_account'=d->>'account' AND x->'inventory_dimensions'->>'warehouse'=d->>'warehouse'
          AND x->'inventory_dimensions'->>'sku'=d->>'sku');
  SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.entry_id),'[]'::jsonb) INTO issues FROM accounting.inventory_issue_receipt r
    WHERE r.organization_id=org AND r.entry_id<cutoff_token AND (
      (r.command->>'account'=d->>'account' AND r.command->>'warehouse'=d->>'warehouse' AND r.command->>'sku'=d->>'sku')
      OR EXISTS (SELECT 1 FROM accounting.line l WHERE l.entry_id=r.entry_id AND l.account_code=d->>'account'
        AND l.dimensions->>'warehouse'=d->>'warehouse' AND l.dimensions->>'sku'=d->>'sku'));
  SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.entry_id),'[]'::jsonb) INTO sales FROM accounting.inventory_sale_receipt r
    WHERE r.organization_id=org AND r.entry_id<cutoff_token AND (
      (r.command->>'account'=d->>'account' AND r.command->>'warehouse'=d->>'warehouse' AND r.command->>'sku'=d->>'sku')
      OR EXISTS (SELECT 1 FROM accounting.line l WHERE l.entry_id=r.entry_id AND l.account_code=d->>'account'
        AND l.dimensions->>'warehouse'=d->>'warehouse' AND l.dimensions->>'sku'=d->>'sku'));
  SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.entry_id),'[]'::jsonb) INTO outputs FROM accounting.production_output_transfer_receipt r
    WHERE r.organization_id=org AND r.entry_id<cutoff_token
      AND EXISTS (SELECT 1 FROM accounting.line l WHERE l.entry_id=r.entry_id AND l.side='debit'
        AND l.account_code=d->>'account' AND l.dimensions->>'warehouse'=d->>'warehouse' AND l.dimensions->>'sku'=d->>'sku');
  SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.registration_token),'[]'::jsonb) INTO revisions
    FROM accounting.production_output_cost_revision r WHERE r.organization_id=org AND r.registration_token<cutoff_token
      AND EXISTS (SELECT 1 FROM accounting.line l WHERE l.entry_id=r.original_entry_id AND l.side='debit'
        AND l.account_code=d->>'account' AND l.dimensions->>'warehouse'=d->>'warehouse' AND l.dimensions->>'sku'=d->>'sku');
  RETURN accounting.financial_sha(jsonb_build_object('organization_id',org,'command',c-'basis_digest',
    'policy',policy_row,'inventory_account',account_row,'destination_account',destination_row,
    'binding',to_jsonb(i),'movement',to_jsonb(m),'sources',sources,'history',history,'zero_receipts',zeros,'issue_receipts',issues,'sale_receipts',sales,
    'output_receipts',outputs,'cost_revisions',revisions));
END $$;
"""


def upgrade():
    current = runpy.run_path(str(Path(__file__).with_name("0148_zero_value_allocated_sales.py")))
    guard, validator, link, stream = current["definitions"]()
    raw_identity_guard = r"""BEGIN
  IF NEW.command->>'command_version'='5' THEN
    IF EXISTS (SELECT 1 FROM (VALUES
      (NEW.command->'command_version'),(NEW.command->'source_version'),(NEW.command->'policy_id'),
      (NEW.command->'material_binding'->'binding_id'),(NEW.command->'material_binding'->'order_id'),
      (NEW.command->'material_binding'->'movement_id'),
      (NEW.command->'document'->'source_version'),(NEW.command->'document'->'policy_id')
    ) raw(value) WHERE (raw.value::text ~ '^[1-9][0-9]*$') IS DISTINCT FROM true)
    OR EXISTS (SELECT 1 FROM json_array_elements(NEW.command->'inventory_layers') x
      WHERE ((x->'source_entry_id')::text ~ '^[1-9][0-9]*$') IS DISTINCT FROM true
         OR ((x->'source_line_id')::text ~ '^[1-9][0-9]*$') IS DISTINCT FROM true) THEN
      RAISE EXCEPTION 'V5 source identities require canonical JSON integer tokens';
    END IF;
  END IF;
"""
    if guard.count("BEGIN\n") != 1:
        raise RuntimeError("0150 raw JSON guard anchor changed")
    guard = guard.replace("BEGIN\n", raw_identity_guard, 1)
    guard = guard.replace("='4' THEN", " IN ('4','5') THEN", 1)
    guard = guard.replace("accounting.zero_value_allocation_basis(NEW.organization_id,NEW.command::jsonb,NEW.registration_token)",
        "(CASE WHEN NEW.command::jsonb->>'command_version'='5' THEN accounting.zero_value_material_allocation_basis(NEW.organization_id,NEW.command::jsonb,NEW.registration_token) ELSE accounting.zero_value_allocation_basis(NEW.organization_id,NEW.command::jsonb,NEW.registration_token) END)")
    validator = (validator.replace("='4' THEN", " IN ('4','5') THEN", 1)
        .replace("c->'command_version'::text IS DISTINCT FROM '4'", "c->'command_version'::text NOT IN ('4','5')")
        .replace("V4 supports integer versioned issues only", "V4/V5 support integer versioned issues only"))
    op.execute(MATERIAL_BASIS)
    op.execute(validator)
    op.execute(guard)
    op.execute(link)
    # V5 enters the same chronological stream as V4, but authenticates against
    # its material-specific fingerprint.  The legacy branch must not replay it.
    stream = stream.replace("command_version'='4'", "command_version' IN ('4','5')")
    stream = stream.replace("accounting.zero_value_allocation_basis(org,c,z.registration_token)",
        "(CASE WHEN c->>'command_version'='5' THEN accounting.zero_value_material_allocation_basis(org,c,z.registration_token) ELSE accounting.zero_value_allocation_basis(org,c,z.registration_token) END)")
    op.execute(stream)
    previous = runpy.run_path(str(Path(__file__).with_name("0147_zero_value_allocation_runtime.py")))
    costs = previous["cost_definitions"]()
    anchor = "z.command::jsonb->>'command_version' IS DISTINCT FROM '4'"
    if costs.count(anchor) != 1:
        raise RuntimeError("0150 legacy quantity exclusion anchor changed")
    op.execute(costs.replace(anchor, "coalesce(z.command::jsonb->>'command_version','') NOT IN ('4','5')"))
    op.execute("CREATE FUNCTION accounting.production_material_zero_allocation_version() RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 5'")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE command::jsonb->>'command_version'='5') THEN RAISE EXCEPTION 'Cannot downgrade V5 material zero allocation history'; END IF; END $$;""")
    current = runpy.run_path(str(Path(__file__).with_name("0148_zero_value_allocated_sales.py")))
    for ddl in current["definitions"]():
        op.execute(ddl)
    previous = runpy.run_path(str(Path(__file__).with_name("0147_zero_value_allocation_runtime.py")))
    op.execute(previous["cost_definitions"]())
    op.execute("DROP FUNCTION accounting.production_material_zero_allocation_version(); DROP FUNCTION accounting.zero_value_material_allocation_basis(integer,jsonb,integer)")
