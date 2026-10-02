"""Complete physical output controls from their authentic aggregate transfer."""
import runpy
from pathlib import Path

from alembic import op

revision = "crm_rel_001_output_source_01"
down_revision = "crm_rel_001_finished_goods_01"
branch_labels = None
depends_on = None


def frozen_guard():
    ddl = runpy.run_path(str(Path(__file__).with_name("0130_accounting_ledger.py")))["DDL"]
    tools = runpy.run_path(str(Path(__file__).with_name("crm_rel_001_finished_goods_01.py")))
    return tools["function"](ddl, "guard_source_control")


VALIDATOR = """
CREATE OR REPLACE FUNCTION accounting.validate_output_source_completion(
  org integer, source_name text, source_version integer, source_month text, target_entry integer
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE receipt accounting.production_output_transfer_receipt; output_entry accounting.entry;
        debit accounting.line; document record; saved jsonb; ids jsonb; native_ids jsonb; basis_ids jsonb;
BEGIN
  SELECT * INTO receipt FROM accounting.production_output_transfer_receipt
    WHERE entry_id=target_entry AND organization_id=org;
  SELECT * INTO output_entry FROM accounting.entry WHERE id=target_entry;
  IF receipt.entry_id IS NULL OR output_entry.id IS NULL OR source_version IS DISTINCT FROM 1
     OR output_entry.organization_id IS DISTINCT FROM org
     OR source_month IS DISTINCT FROM receipt.month
     OR source_month IS DISTINCT FROM to_char(output_entry.posting_date,'YYYY-MM')
     OR jsonb_typeof(receipt.command::jsonb->'output_document_ids') IS DISTINCT FROM 'array'
     OR jsonb_typeof(receipt.basis::jsonb->'output'->'documents') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Output source completion requires its same-organization/month immutable transfer';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org AND month=source_month AND closed)
     OR NOT EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=org AND month=source_month) THEN
    RAISE EXCEPTION 'Pending output sources cannot be completed in a closed or missing period';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(receipt.command::jsonb->'output_document_ids') v
       WHERE jsonb_typeof(v)<>'number' OR v::text !~ '^[1-9][0-9]*$')
     OR jsonb_array_length(receipt.command::jsonb->'output_document_ids') NOT BETWEEN 1 AND 100 THEN
    RAISE EXCEPTION 'Output source completion document identities are invalid';
  END IF;
  SELECT jsonb_agg(v ORDER BY (v::text)::integer) INTO ids
    FROM jsonb_array_elements(receipt.command::jsonb->'output_document_ids') v;
  SELECT jsonb_agg(to_jsonb(d.id) ORDER BY d.id) INTO native_ids
    FROM production.output_document d JOIN production.output_confirmation c ON c.document_id=d.id
    WHERE d.organization_id=org AND d.order_id=receipt.order_id
      AND c.organization_id=org AND c.order_id=receipt.order_id;
  SELECT jsonb_agg(v->'document_id' ORDER BY (v->>'document_id')::integer) INTO basis_ids
    FROM jsonb_array_elements(receipt.basis::jsonb->'output'->'documents') v;
  IF ids IS DISTINCT FROM native_ids OR ids IS DISTINCT FROM basis_ids
     OR (SELECT count(DISTINCT v) FROM jsonb_array_elements(ids) v)<>jsonb_array_length(ids)
     OR NOT EXISTS (SELECT 1 FROM production.order_ownership WHERE order_id=receipt.order_id AND organization_id=org) THEN
    RAISE EXCEPTION 'Output source completion requires all and only confirmed receipt documents';
  END IF;
  SELECT * INTO debit FROM accounting.line WHERE entry_id=target_entry AND side='debit';
  -- G12 verifies full actual posting/digest, opaque basis crosslinks, complete
  -- finished-goods debit and immutable WIP groups/source at posting boundary.
  PERFORM accounting.validate_shipment_output_layer(org,target_entry,debit.id,debit.account_code,
    output_entry.posting_date,target_entry+1);
  FOR document IN SELECT d.*,c.organization_id AS confirmed_org,c.order_id AS confirmed_order,
      c.quantity AS confirmed_quantity,c.digest AS confirmed_digest
    FROM production.output_document d JOIN production.output_confirmation c ON c.document_id=d.id
    WHERE d.organization_id=org AND d.order_id=receipt.order_id ORDER BY d.id LOOP
    SELECT v INTO STRICT saved FROM jsonb_array_elements(receipt.basis::jsonb->'output'->'documents') v
      WHERE (v->>'document_id')::integer=document.id;
    IF document.confirmed_org IS DISTINCT FROM org OR document.confirmed_order IS DISTINCT FROM receipt.order_id
       OR document.confirmed_digest IS DISTINCT FROM document.digest
       OR accounting.financial_sha(document.snapshot::jsonb) IS DISTINCT FROM document.digest
       OR document.snapshot::jsonb->'command' IS DISTINCT FROM document.command::jsonb
       OR document.snapshot->>'organization_id' IS DISTINCT FROM org::text
       OR document.snapshot->'order_snapshot'->>'order_id' IS DISTINCT FROM receipt.order_id::text
       OR document.command->>'order_id' IS DISTINCT FROM receipt.order_id::text
       OR substring(document.command->>'operation_date',1,7) IS DISTINCT FROM source_month
       OR document.confirmed_quantity IS DISTINCT FROM (document.command->>'quantity')::numeric
       OR document.command->>'warehouse' IS DISTINCT FROM debit.dimensions->>'warehouse'
       OR document.command->>'sku_code' IS DISTINCT FROM debit.dimensions->>'sku'
       OR document.command->>'lot' IS DISTINCT FROM debit.dimensions->>'lot'
       OR saved->>'request_id' IS DISTINCT FROM document.request_id
       OR saved->>'operation_date' IS DISTINCT FROM document.command->>'operation_date'
       OR saved->>'sku_code' IS DISTINCT FROM document.command->>'sku_code'
       OR saved->>'lot' IS DISTINCT FROM document.command->>'lot'
       OR saved->>'state' IS DISTINCT FROM 'accepted'
       OR (saved->>'quantity')::numeric IS DISTINCT FROM document.confirmed_quantity
       OR (saved->>'accepted_quantity')::numeric IS DISTINCT FROM document.confirmed_quantity
       OR (saved->>'rejected_quantity')::numeric IS DISTINCT FROM 0::numeric THEN
      RAISE EXCEPTION 'Output source completion document identity or month differs';
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM production.output_document d
      WHERE d.organization_id=org AND d.order_id=receipt.order_id AND source_name='production:output:'||d.id
        AND to_jsonb(d.id) IN (SELECT value FROM jsonb_array_elements(ids))) THEN
    RAISE EXCEPTION 'Output source completion control is outside the immutable receipt';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.check_output_source_completion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt accounting.production_output_transfer_receipt;
BEGIN
  IF NEW.source NOT LIKE 'production:output:%' OR NEW.entry_id IS NULL THEN RETURN NULL; END IF;
  IF EXISTS (SELECT 1 FROM accounting.entry e WHERE e.id=NEW.entry_id
    AND e.organization_id=NEW.organization_id AND e.source=NEW.source
    AND e.source_version=NEW.version AND to_char(e.posting_date,'YYYY-MM')=NEW.month) THEN
    RETURN NULL;
  END IF;
  SELECT * INTO receipt FROM accounting.production_output_transfer_receipt
    WHERE entry_id=NEW.entry_id AND organization_id=NEW.organization_id;
  IF receipt.entry_id IS NULL OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(receipt.command::jsonb->'output_document_ids') d
    WHERE NOT EXISTS (SELECT 1 FROM accounting.source_control c
      WHERE c.organization_id=receipt.organization_id AND c.source='production:output:'||(d::text)::integer
        AND c.version=1 AND c.month=receipt.month AND c.entry_id=receipt.entry_id)
  ) THEN RAISE EXCEPTION 'Output source completion must resolve the entire receipt document set'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_output_receipt_sources
AFTER UPDATE ON accounting.source_control DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting.check_output_source_completion();
"""


def definitions():
    guard = frozen_guard()
    tools = runpy.run_path(str(Path(__file__).with_name("crm_rel_001_finished_goods_01.py")))
    guard = tools["replace_once"](guard,
        "  IF NEW.entry_id IS NOT NULL AND NOT EXISTS (",
        "  IF NEW.entry_id IS NOT NULL AND NEW.source LIKE 'production:output:%'\n"
        "     AND EXISTS (SELECT 1 FROM accounting.entry e WHERE e.id=NEW.entry_id AND e.source<>NEW.source) THEN\n"
        "    PERFORM accounting.validate_output_source_completion(NEW.organization_id,NEW.source,NEW.version,NEW.month,NEW.entry_id);\n"
        "  ELSIF NEW.entry_id IS NOT NULL AND NOT EXISTS (")
    return VALIDATOR + guard


def upgrade():
    op.execute(definitions())


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.source_control c JOIN accounting.entry e ON e.id=c.entry_id
        WHERE c.source LIKE 'production:output:%' AND e.source<>c.source) THEN
        RAISE EXCEPTION 'Cannot downgrade output-source completion with linked production history';
      END IF;
    END $$;
    DROP TRIGGER complete_output_receipt_sources ON accounting.source_control;
    DROP FUNCTION accounting.check_output_source_completion();""")
    op.execute(frozen_guard())
    op.execute("DROP FUNCTION accounting.validate_output_source_completion(integer,text,integer,text,integer)")
