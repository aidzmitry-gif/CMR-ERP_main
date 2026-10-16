"""Atomically persist one multi-field procurement order save receipt."""

from alembic import op

revision = "0178"
down_revision = "0177"
branch_labels = None
depends_on = None

EDIT_GUARD = r'''CREATE OR REPLACE FUNCTION procurement.guard_order_edit_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb:=NEW.command::jsonb; r jsonb:=NEW.result::jsonb; common jsonb; actual_line jsonb;
        line_action text; line_payload jsonb; line_effect jsonb;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR length(btrim(NEW.actor))=0 OR jsonb_typeof(c) IS DISTINCT FROM 'object'
     OR jsonb_typeof(r) IS DISTINCT FROM 'object'
     OR c->'version' IS DISTINCT FROM '1'::jsonb
     OR c->>'request_key' IS DISTINCT FROM NEW.request_key
     OR c->'order_id' IS DISTINCT FROM to_jsonb(NEW.target_order_id)
     OR c->>'action' IS DISTINCT FROM NEW.action
     OR jsonb_typeof(c->'payload') IS DISTINCT FROM 'object'
     OR encode(sha256(convert_to(procurement.order_command_json(c),'UTF8')),'hex')
        IS DISTINCT FROM NEW.command_hash THEN
    RAISE EXCEPTION 'Order edit command identity mismatch';
  END IF;
  common:=jsonb_build_object('version',1,'organization_id',NEW.organization_id,
    'principal',NEW.actor,'request_key',NEW.request_key,'command_hash',NEW.command_hash,
    'order_id',NEW.target_order_id,'action',NEW.action,'outcome',NEW.outcome);
  IF NEW.action='save' AND
    (c->'payload'='{}'::jsonb OR EXISTS (
       SELECT 1 FROM jsonb_object_keys(c->'payload') AS t(step)
       WHERE step NOT IN ('add_line','header','plan','status'))
     OR (NEW.outcome='applied' AND (
       SELECT coalesce(jsonb_object_agg(step,c->'payload'->step),'{}'::jsonb)
       FROM jsonb_object_keys(r->'effect') AS t(step)) IS DISTINCT FROM c->'payload')
     OR (NEW.outcome='applied' AND jsonb_typeof(r->'effect') IS DISTINCT FROM 'object')) THEN
    RAISE EXCEPTION 'Invalid atomic order save';
  END IF;
  IF NEW.outcome='rejected' THEN
    IF NEW.ownership_id IS NOT NULL OR r->>'code' NOT IN
      ('command_abandoned','source_unavailable','order_not_editable','line_unavailable',
       'transition_not_allowed','transport_method_unavailable','sku_catalog_changed')
       OR r->>'code' IS NULL
       OR r IS DISTINCT FROM common || jsonb_build_object('code',r->>'code','no_business_write',true) THEN
      RAISE EXCEPTION 'Order edit rejected receipt mismatch';
    END IF;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM procurement.purchase_ownership
      WHERE id=NEW.ownership_id AND organization_id=NEW.organization_id
        AND kind='order' AND source_id=NEW.target_order_id)
       OR jsonb_typeof(r->'effect') IS DISTINCT FROM 'object'
       OR r IS DISTINCT FROM common || jsonb_build_object('ownership_id',NEW.ownership_id,'effect',r->'effect') THEN
      RAISE EXCEPTION 'Order edit applied receipt ownership mismatch';
    END IF;
    IF NEW.action IN ('add_line','delete_line') OR (NEW.action='save' AND c#>'{payload,add_line}' IS NOT NULL) THEN
      line_action := CASE WHEN NEW.action='save' THEN 'add_line' ELSE NEW.action END;
      line_payload := CASE WHEN NEW.action='save' THEN c#>'{payload,add_line}' ELSE c->'payload' END;
      line_effect := CASE WHEN NEW.action='save' THEN r#>'{effect,add_line}' ELSE r->'effect' END;
      SELECT snapshot INTO actual_line FROM procurement.order_line_edit_proof
        WHERE root_transaction=txid_current() AND order_id=NEW.target_order_id
          AND action=line_action AND to_jsonb(line_id)=line_effect#>'{line,id}';
      IF actual_line IS NULL OR line_effect IS DISTINCT FROM jsonb_build_object('line',actual_line)
         OR (line_action='add_line' AND line_payload - 'sku_id' - 'sku_title' - 'sku_unit'
             IS DISTINCT FROM actual_line-'id')
         OR (line_action='add_line' AND line_payload ? 'sku_id' AND NOT EXISTS
             (SELECT 1 FROM sku s WHERE s.id=(line_payload->>'sku_id')::integer
                AND s.is_active AND s.code=line_payload->>'sku_code'
                AND s.title=line_payload->>'sku_title' AND s.unit=line_payload->>'sku_unit'))
         OR (line_action='delete_line' AND line_payload IS DISTINCT FROM
           jsonb_build_object('line_id',actual_line->'id')) THEN
        RAISE EXCEPTION 'Order edit receipt lacks matching line mutation proof';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;'''


def upgrade():
    op.execute("ALTER TABLE procurement.purchase_order_edit_command DROP CONSTRAINT ck_purchase_order_edit_command_edit_action")
    op.execute("ALTER TABLE procurement.purchase_order_edit_command ADD CONSTRAINT ck_purchase_order_edit_command_edit_action CHECK (action IN ('add_line','delete_line','header','status','plan','save'))")
    op.execute("DROP INDEX procurement.one_edit_receipt_per_line_action")
    op.execute("""CREATE UNIQUE INDEX one_edit_receipt_per_line_action ON procurement.purchase_order_edit_command
      ((CASE WHEN action='save' THEN 'add_line' ELSE action END),
       (CASE WHEN action='save' THEN result::jsonb#>>'{effect,add_line,line,id}'
             ELSE result::jsonb#>>'{effect,line,id}' END))
      WHERE outcome='applied' AND action IN ('add_line','delete_line','save')""")
    op.execute(EDIT_GUARD)


def downgrade():
    raise RuntimeError("Atomic immutable save receipts cannot be replayed under the previous guard")
