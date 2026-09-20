"""Persist authenticated entryless zero-value inventory issue receipts.

Revision ID: 0140
Revises: 0139
"""
from alembic import op

revision = "0140"
down_revision = "0139"
branch_labels = None
depends_on = None

DDL = r"""
CREATE TABLE accounting.inventory_zero_value_disposal_receipt (
  id SERIAL PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  source VARCHAR(160) NOT NULL, source_version INTEGER NOT NULL, operation VARCHAR(60) NOT NULL,
  entry_id INTEGER UNIQUE REFERENCES accounting.entry(id), registration_token INTEGER NOT NULL UNIQUE,
  posting_date DATE NOT NULL, policy_id INTEGER NOT NULL REFERENCES accounting.policy(id), command JSON NOT NULL,
  basis_digest VARCHAR(64) NOT NULL, digest VARCHAR(64) NOT NULL, actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
  CONSTRAINT uq_inventory_zero_value_disposal_identity UNIQUE (organization_id,source,source_version,operation),
  CONSTRAINT ck_inventory_zero_value_disposal_operation CHECK (operation IN ('inventory_issue','inventory_sale')),
  CONSTRAINT ck_inventory_zero_value_disposal_source_version CHECK (source_version>0),
  CONSTRAINT ck_inventory_zero_value_disposal_registration CHECK (registration_token>0)
);
CREATE OR REPLACE FUNCTION accounting.register_inventory_zero_value_disposal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE seq text; BEGIN
  IF NEW.registration_token IS NOT NULL THEN RAISE EXCEPTION 'Zero-value registration token is database assigned'; END IF;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT pg_get_serial_sequence('accounting.entry','id') INTO seq;
  IF seq IS NULL THEN RAISE EXCEPTION 'Accounting entry identity sequence is unavailable'; END IF;
  EXECUTE format('SELECT nextval(%L)',seq) INTO NEW.registration_token; RETURN NEW;
END $$;
CREATE TRIGGER aa_register_inventory_zero_value_disposal BEFORE INSERT ON accounting.inventory_zero_value_disposal_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.register_inventory_zero_value_disposal();
CREATE OR REPLACE FUNCTION accounting.zero_value_disposal_basis(org integer, p_command jsonb, cutoff_token integer)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE layer jsonb; source_row jsonb; history jsonb; policy_row jsonb; account_row jsonb;
  destination_account_row jsonb; prior_receipts jsonb;
BEGIN
  IF cutoff_token IS NULL OR cutoff_token<=0 OR jsonb_typeof(p_command) IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_command->'inventory_layers') IS DISTINCT FROM 'array' OR jsonb_array_length(p_command->'inventory_layers')<>1 THEN
    RAISE EXCEPTION 'Zero-value basis supports one specific-cost source layer only';
  END IF;
  layer := p_command->'inventory_layers'->0;
  SELECT to_jsonb(l) || jsonb_build_object('entry',to_jsonb(e),'output_receipt',to_jsonb(r)) INTO source_row
    FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      JOIN accounting.production_output_transfer_receipt r ON r.entry_id=e.id
    WHERE e.organization_id=org AND e.id=(layer->>'source_entry_id')::integer
      AND l.id=(layer->>'source_line_id')::integer AND e.operation='production_output_transfer'
      AND l.side='debit' AND l.account_code=layer->>'inventory_account'
      AND l.dimensions::jsonb=layer->'inventory_dimensions'
      AND e.posting_date<=(p_command->>'posting_date')::date AND e.id<cutoff_token;
  SELECT to_jsonb(p) INTO policy_row FROM accounting.policy p WHERE p.id=(p_command->>'policy_id')::integer
    AND p.organization_id=org AND p.effective_from<=(p_command->>'posting_date')::date AND p.inventory_method='specific'
    AND NOT EXISTS (SELECT 1 FROM accounting.policy newer WHERE newer.organization_id=org
      AND newer.effective_from<=(p_command->>'posting_date')::date AND newer.effective_from>p.effective_from);
  SELECT to_jsonb(a) INTO account_row FROM accounting.account a WHERE a.organization_id=org
    AND a.code=layer->>'inventory_account' AND a.valid_from<=(p_command->>'posting_date')::date
    ORDER BY a.valid_from DESC LIMIT 1;
  SELECT coalesce(jsonb_agg(jsonb_build_object('entry_id',e.id,'line_id',l.id,'posting_date',e.posting_date,
      'side',l.side,'amount',l.amount,'quantity',l.quantity,'dimensions',l.dimensions::jsonb) ORDER BY e.posting_date,e.id,l.id),'[]'::jsonb)
    INTO history FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
    WHERE e.organization_id=org AND e.posting_date<=(p_command->>'posting_date')::date
      AND l.account_code=layer->>'inventory_account' AND l.dimensions::jsonb=layer->'inventory_dimensions'
      AND e.id<cutoff_token;
  SELECT to_jsonb(a) INTO destination_account_row FROM accounting.account a WHERE a.organization_id=org
    AND a.code=p_command->>'destination_account' AND a.valid_from<=(p_command->>'posting_date')::date
    ORDER BY a.valid_from DESC LIMIT 1;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',z.id,'registration_token',z.registration_token,
      'posting_date',z.posting_date,'command',z.command::jsonb,'basis_digest',z.basis_digest,'digest',z.digest)
      ORDER BY z.registration_token,z.id),'[]'::jsonb) INTO prior_receipts
    FROM accounting.inventory_zero_value_disposal_receipt z
    CROSS JOIN LATERAL jsonb_array_elements(z.command::jsonb->'inventory_layers') prior_layer
    WHERE z.organization_id=org AND z.registration_token<cutoff_token AND z.posting_date<=(p_command->>'posting_date')::date
      AND (prior_layer->>'source_entry_id')::integer=(layer->>'source_entry_id')::integer
      AND (prior_layer->>'source_line_id')::integer=(layer->>'source_line_id')::integer;
  IF source_row IS NULL OR policy_row IS NULL OR account_row IS NULL OR destination_account_row IS NULL THEN
    RAISE EXCEPTION 'Zero-value basis source, policy or account is unavailable';
  END IF;
  RETURN accounting.financial_sha(jsonb_build_object('organization_id',org,'command',p_command-'basis_digest',
    'source',source_row,'history',history,'prior_receipts',prior_receipts,'policy',policy_row,
    'account',account_row,'destination_account',destination_account_row));
END $$;
CREATE OR REPLACE FUNCTION accounting.guard_inventory_zero_value_disposal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c jsonb:=NEW.command::jsonb; layer jsonb; src accounting.line%ROWTYPE; source_entry accounting.entry%ROWTYPE;
  qty numeric; value numeric; prior numeric; period_row accounting.period%ROWTYPE; calculated_basis text; destination accounting.account%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO period_row FROM accounting.period WHERE organization_id=NEW.organization_id AND month=to_char(NEW.posting_date,'YYYY-MM');
  IF period_row.id IS NULL OR period_row.closed THEN RAISE EXCEPTION 'Zero-value disposal requires an open period'; END IF;
  calculated_basis := accounting.zero_value_disposal_basis(NEW.organization_id,c,NEW.registration_token);
  IF jsonb_typeof(c) IS DISTINCT FROM 'object' OR NEW.operation IS DISTINCT FROM 'inventory_issue' OR NEW.entry_id IS NOT NULL OR NEW.source='' OR NEW.source_version<=0
    OR NEW.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object('organization_id',NEW.organization_id,'actor',NEW.actor,'command',c))
    OR c->>'source' IS DISTINCT FROM NEW.source OR (c->>'source_version')::integer IS DISTINCT FROM NEW.source_version
    OR c->>'operation' IS DISTINCT FROM 'inventory_issue' OR (c->>'policy_id')::integer IS DISTINCT FROM NEW.policy_id
    OR c->>'basis_digest' IS DISTINCT FROM NEW.basis_digest OR NEW.basis_digest IS DISTINCT FROM calculated_basis
    OR c->>'posting_date' IS DISTINCT FROM NEW.posting_date::text
    OR jsonb_typeof(c->'inventory_layers') IS DISTINCT FROM 'array' OR jsonb_array_length(c->'inventory_layers')<>1
    OR NOT EXISTS (SELECT 1 FROM accounting.policy p WHERE p.id=NEW.policy_id AND p.organization_id=NEW.organization_id
      AND p.effective_from<=NEW.posting_date AND p.inventory_method='specific' AND NOT EXISTS
        (SELECT 1 FROM accounting.policy newer WHERE newer.organization_id=NEW.organization_id
          AND newer.effective_from<=NEW.posting_date AND newer.effective_from>p.effective_from))
    OR EXISTS (SELECT 1 FROM accounting.entry e WHERE e.organization_id=NEW.organization_id AND e.source=NEW.source AND e.source_version=NEW.source_version AND e.operation='inventory_issue') THEN
    RAISE EXCEPTION 'Zero-value disposal snapshot or identity is invalid';
  END IF;
  SELECT * INTO destination FROM accounting.account WHERE organization_id=NEW.organization_id AND code=c->>'destination_account'
    AND valid_from<=NEW.posting_date ORDER BY valid_from DESC LIMIT 1;
  IF destination.id IS NULL OR destination.cash OR destination.quantity_tracking
    OR (destination.category IS DISTINCT FROM 'asset' AND destination.category IS DISTINCT FROM 'expense')
    OR (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_object_keys(coalesce(c->'destination_dimensions','{}'::jsonb)) k)
       IS DISTINCT FROM (SELECT coalesce(jsonb_agg(k ORDER BY k),'[]'::jsonb) FROM jsonb_array_elements_text(destination.required_dimensions::jsonb) k) THEN
    RAISE EXCEPTION 'Zero-value disposal destination account or analytics is invalid';
  END IF;
  FOR layer IN SELECT element.value FROM jsonb_array_elements(c->'inventory_layers') AS element(value) LOOP
    IF jsonb_typeof(layer) IS DISTINCT FROM 'object' OR jsonb_typeof(layer->'source_entry_id') IS DISTINCT FROM 'number'
      OR jsonb_typeof(layer->'source_line_id') IS DISTINCT FROM 'number'
      OR jsonb_typeof(layer->'inventory_account') IS DISTINCT FROM 'string'
      OR jsonb_typeof(layer->'inventory_dimensions') IS DISTINCT FROM 'object'
      OR jsonb_typeof(layer->'quantity') IS DISTINCT FROM 'string'
      OR layer->>'quantity' !~ '^(0|[1-9][0-9]{0,17})([.][0-9]{1,6})?$' THEN
      RAISE EXCEPTION 'Zero-value disposal layer schema is invalid';
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_each(layer->'inventory_dimensions') AS dim(key, value)
      WHERE jsonb_typeof(dim.value) IS DISTINCT FROM 'string' OR btrim(dim.value #>> '{}')='')
      OR EXISTS (SELECT 1 FROM jsonb_each(c->'destination_dimensions') AS dim(key, value)
        WHERE jsonb_typeof(dim.value) IS DISTINCT FROM 'string' OR btrim(dim.value #>> '{}')='') THEN
      RAISE EXCEPTION 'Zero-value disposal analytics values are invalid';
    END IF;
    SELECT l.* INTO src FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      JOIN accounting.production_output_transfer_receipt r ON r.entry_id=e.id
      WHERE e.organization_id=NEW.organization_id AND l.id=(layer->>'source_line_id')::integer
        AND e.id=(layer->>'source_entry_id')::integer AND e.operation='production_output_transfer'
        AND l.side='debit' AND l.account_code=layer->>'inventory_account' AND l.dimensions::jsonb=layer->'inventory_dimensions';
    SELECT * INTO source_entry FROM accounting.entry WHERE id=src.entry_id;
    IF src.id IS NULL OR source_entry.posting_date>NEW.posting_date OR source_entry.id>=NEW.registration_token
      OR (layer->>'quantity')::numeric<=0 OR src.quantity<(layer->>'quantity')::numeric THEN
      RAISE EXCEPTION 'Zero-value disposal source output layer is invalid'; END IF;
    IF EXISTS (SELECT 1 FROM accounting.line later_line JOIN accounting.entry later_entry ON later_entry.id=later_line.entry_id
      WHERE later_entry.organization_id=NEW.organization_id AND later_entry.posting_date>NEW.posting_date
        AND later_line.account_code=src.account_code AND later_line.dimensions::jsonb=src.dimensions::jsonb) THEN
      RAISE EXCEPTION 'Zero-value disposal requires no later inventory movements';
    END IF;
    IF EXISTS (SELECT 1 FROM accounting.line other_line JOIN accounting.entry other_entry ON other_entry.id=other_line.entry_id
      WHERE other_entry.organization_id=NEW.organization_id AND other_entry.operation='production_output_transfer'
        AND other_line.side='debit' AND other_line.id<>src.id AND other_line.account_code=src.account_code
        AND other_line.dimensions::jsonb=src.dimensions::jsonb) THEN
      RAISE EXCEPTION 'Zero-value disposal supports one authenticated output origin per analytics layer';
    END IF;
    IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt future_receipt
      CROSS JOIN LATERAL jsonb_array_elements(future_receipt.command::jsonb->'inventory_layers') future_layer
      WHERE future_receipt.organization_id=NEW.organization_id AND future_receipt.posting_date>NEW.posting_date
        AND future_layer->>'inventory_account'=src.account_code
        AND future_layer->'inventory_dimensions'=src.dimensions::jsonb) THEN
      RAISE EXCEPTION 'Zero-value disposal requires no later zero-value receipts';
    END IF;
    SELECT coalesce(sum(CASE WHEN l.side='debit' THEN l.quantity ELSE -l.quantity END),0),
           coalesce(sum(CASE WHEN l.side='debit' THEN l.amount ELSE -l.amount END),0) INTO qty,value
      FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=NEW.organization_id AND e.posting_date<=NEW.posting_date
        AND l.account_code=src.account_code AND l.dimensions::jsonb=src.dimensions::jsonb;
    SELECT coalesce(sum((x->>'quantity')::numeric),0) INTO prior
      FROM accounting.inventory_zero_value_disposal_receipt z CROSS JOIN LATERAL jsonb_array_elements(z.command::jsonb->'inventory_layers') x
      WHERE z.organization_id=NEW.organization_id AND z.posting_date<=NEW.posting_date
        AND (x->>'source_entry_id')::integer=src.entry_id AND (x->>'source_line_id')::integer=src.id;
    IF value<>0 OR qty-prior<(layer->>'quantity')::numeric THEN RAISE EXCEPTION 'Zero-value disposal is not an authenticated zero-cost remaining layer'; END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_zero_value_disposal BEFORE INSERT ON accounting.inventory_zero_value_disposal_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_zero_value_disposal();
CREATE OR REPLACE FUNCTION accounting.guard_entry_against_zero_value_disposal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.operation='inventory_issue' THEN
    PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt z WHERE z.organization_id=NEW.organization_id
      AND z.source=NEW.source AND z.source_version=NEW.source_version AND z.operation=NEW.operation) THEN
      RAISE EXCEPTION 'Entry identity is already reserved by a zero-value disposal receipt';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_entry_against_zero_value_disposal BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.guard_entry_against_zero_value_disposal();
CREATE OR REPLACE FUNCTION accounting.reject_inventory_zero_value_disposal_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Zero-value disposal receipt is immutable'; END $$;
CREATE TRIGGER immutable_inventory_zero_value_disposal BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.inventory_zero_value_disposal_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inventory_zero_value_disposal_mutation();
"""

def upgrade(): op.execute(DDL)

def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt) THEN RAISE EXCEPTION 'Cannot downgrade zero-value disposals with history'; END IF; END $$;
    DROP TRIGGER guard_entry_against_zero_value_disposal ON accounting.entry; DROP FUNCTION accounting.guard_entry_against_zero_value_disposal();
    DROP TABLE accounting.inventory_zero_value_disposal_receipt; DROP FUNCTION accounting.register_inventory_zero_value_disposal(); DROP FUNCTION accounting.guard_inventory_zero_value_disposal(); DROP FUNCTION accounting.zero_value_disposal_basis(integer,jsonb,integer); DROP FUNCTION accounting.reject_inventory_zero_value_disposal_mutation();""")
