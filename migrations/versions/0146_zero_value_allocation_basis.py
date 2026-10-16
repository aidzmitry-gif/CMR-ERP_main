"""Bind V4 zero allocations to complete historical evidence; no write enablement."""
from alembic import op

revision = "0146"
down_revision = "0145"
branch_labels = None
depends_on = None

DDL = r"""
CREATE FUNCTION accounting.zero_value_allocation_basis(org integer, c jsonb, cutoff_token integer)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE d jsonb; layer jsonb; field text; day date; source_row jsonb; sources jsonb:='[]'::jsonb;
  policy_row jsonb; account_row jsonb; destination_row jsonb; history jsonb; zeros jsonb;
  issues jsonb; sales jsonb; outputs jsonb; revisions jsonb; total numeric:=0; seen text[]:=ARRAY[]::text[]; identity text;
BEGIN
  IF org IS NULL OR org<=0 OR cutoff_token IS NULL OR cutoff_token<=0
    OR jsonb_typeof(c) IS DISTINCT FROM 'object' OR c->>'command_version' IS DISTINCT FROM '4'
    OR jsonb_typeof(c->'command_version') IS DISTINCT FROM 'number'
    OR jsonb_typeof(c->'valuation_method') IS DISTINCT FROM 'string'
    OR c->>'valuation_method' NOT IN ('fifo','weighted_average') OR NOT c ? 'valuation_method'
    OR jsonb_typeof(c->'operation') IS DISTINCT FROM 'string'
    OR c->>'operation' NOT IN ('inventory_issue','inventory_sale') OR NOT c ? 'operation'
    OR jsonb_typeof(c->'document') IS DISTINCT FROM 'object'
    OR jsonb_typeof(c->'inventory_layers') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'V4 allocation basis requires a complete versioned command';
  END IF;
  IF jsonb_array_length(c->'inventory_layers') NOT BETWEEN 1 AND 1000 THEN
    RAISE EXCEPTION 'V4 allocation basis requires bounded source layers';
  END IF;
  PERFORM 1 FROM accounting.organization WHERE id=org FOR UPDATE;
  d:=c->'document';
  FOREACH field IN ARRAY ARRAY['source','source_version','document_date','operation_date','posting_date','policy_id','explanation'] LOOP
    IF NOT c ? field OR c->field IS DISTINCT FROM d->field THEN
      RAISE EXCEPTION 'V4 allocation document metadata differ';
    END IF;
  END LOOP;
  FOREACH field IN ARRAY ARRAY['source_version','policy_id'] LOOP
    IF jsonb_typeof(c->field) IS DISTINCT FROM 'number' OR c->>field !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'V4 allocation identities must be positive integers';
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
    RAISE EXCEPTION 'V4 allocation document quantity or destination is invalid';
  END IF;
  FOREACH field IN ARRAY ARRAY['account','warehouse','sku'] LOOP
    IF jsonb_typeof(d->field) IS DISTINCT FROM 'string' OR coalesce(btrim(d->>field),'')='' THEN
      RAISE EXCEPTION 'V4 allocation inventory pool is incomplete';
    END IF;
  END LOOP;
  IF jsonb_typeof(d->'lot') IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'V4 allocation lot must be explicit or empty'; END IF;
  FOREACH field IN ARRAY ARRAY['document_date','operation_date','posting_date'] LOOP
    IF jsonb_typeof(c->field) IS DISTINCT FROM 'string' OR c->>field !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      OR to_char((c->>field)::date,'YYYY-MM-DD') IS DISTINCT FROM c->>field THEN
      RAISE EXCEPTION 'V4 allocation date is invalid';
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
    OR destination_row->>'category' IS DISTINCT FROM 'expense' THEN
    RAISE EXCEPTION 'V4 allocation applicable policy or owned accounts are unavailable';
  END IF;
  IF (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_object_keys(c->'destination_dimensions') k)
    IS DISTINCT FROM (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_array_elements_text(destination_row->'required_dimensions') k)
    OR EXISTS (SELECT 1 FROM jsonb_each(c->'destination_dimensions') x WHERE jsonb_typeof(x.value) IS DISTINCT FROM 'string'
      OR length(btrim(x.value #>> '{}')) NOT BETWEEN 1 AND 200) THEN
    RAISE EXCEPTION 'V4 allocation destination analytics are invalid';
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
      RAISE EXCEPTION 'V4 allocation source identity or quantity is invalid';
    END IF;
    identity:=(layer->>'source_entry_id')||':'||(layer->>'source_line_id');
    IF identity=ANY(seen) THEN RAISE EXCEPTION 'V4 allocation repeats an origin'; END IF;
    seen:=array_append(seen,identity); total:=total+(layer->>'quantity')::numeric;
    SELECT jsonb_build_object('entry',to_jsonb(e),'line',to_jsonb(l),'output_receipt',to_jsonb(r)) INTO source_row
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      JOIN accounting.production_output_transfer_receipt r ON r.entry_id=e.id AND r.organization_id=e.organization_id AND r.digest=e.digest
      WHERE e.organization_id=org AND e.id=(layer->>'source_entry_id')::integer AND l.id=(layer->>'source_line_id')::integer
        AND e.id<cutoff_token AND e.posting_date<=day AND e.operation='production_output_transfer'
        AND l.side='debit' AND l.account_code=d->>'account' AND l.dimensions::jsonb=layer->'inventory_dimensions'
        AND l.quantity>=(layer->>'quantity')::numeric AND l.currency='BYN' AND l.category='asset' AND NOT l.cash;
    IF source_row IS NULL THEN RAISE EXCEPTION 'V4 allocation source is not a prior authenticated output'; END IF;
    sources:=sources||jsonb_build_array(source_row);
  END LOOP;
  IF total IS DISTINCT FROM (d->>'quantity')::numeric THEN RAISE EXCEPTION 'V4 allocation quantity is not conserved'; END IF;
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
    'sources',sources,'history',history,'zero_receipts',zeros,'issue_receipts',issues,'sale_receipts',sales,
    'output_receipts',outputs,'cost_revisions',revisions));
END $$;
"""


def upgrade():
    op.execute(DDL)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE command::jsonb->>'command_version'='4') THEN
        RAISE EXCEPTION 'Cannot downgrade 0146 with V4 zero-value history';
      END IF;
    END $$;
    DROP FUNCTION accounting.zero_value_allocation_basis(integer,jsonb,integer);""")
