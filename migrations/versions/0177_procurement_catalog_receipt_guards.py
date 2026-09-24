"""Accept catalog-bound procurement receipts on PostgreSQL without weakening provenance guards."""

from alembic import op

revision = "0177"
down_revision = "0176"
branch_labels = None
depends_on = None

CREATION_GUARD = r'''CREATE OR REPLACE FUNCTION procurement.guard_order_creation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb; d jsonb; b jsonb; item jsonb; actual_lines jsonb; expected jsonb;
        snapshot jsonb; proof_snapshot jsonb; position_count integer; index_number integer; id_key text; o procurement.purchase_order%ROWTYPE;
        owner_row procurement.purchase_ownership%ROWTYPE; request_owner procurement.purchase_ownership%ROWTYPE;
        request_row procurement.purchase_request%ROWTYPE; link_row procurement.order_request_link%ROWTYPE;
BEGIN
  PERFORM id FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  c := NEW.command::jsonb; d := c->'document'; b := c->'request_basis';
  IF jsonb_typeof(c) IS DISTINCT FROM 'object' OR jsonb_typeof(d) IS DISTINCT FROM 'object'
    OR c IS DISTINCT FROM jsonb_build_object('request_key',NEW.request_key,'document',d,
         'ownership_evidence',c->'ownership_evidence','request_basis',b)
    OR (d IS DISTINCT FROM jsonb_build_object('supplier',d->'supplier','eta_date',d->'eta_date',
         'freight_byn',d->'freight_byn','lines',d->'lines')
      AND d IS DISTINCT FROM jsonb_build_object('supplier',d->'supplier','supplier_id',d->'supplier_id',
         'supplier_unp',d->'supplier_unp','eta_date',d->'eta_date',
         'freight_byn',d->'freight_byn','lines',d->'lines'))
    OR NEW.request_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    OR NEW.command_hash !~ '^[0-9a-f]{64}$'
    OR NEW.actor IS NULL OR length(NEW.actor) NOT BETWEEN 1 AND 200
    OR NOT procurement.order_command_text(c->'ownership_evidence',1000)
    OR NOT procurement.order_command_text(d->'supplier',255)
    OR (d ? 'supplier_id' AND (jsonb_typeof(d->'supplier_id') IS DISTINCT FROM 'number'
      OR (d->>'supplier_id') !~ '^[1-9][0-9]*$'
      OR (d->>'supplier_id')::numeric > 2147483647
      OR jsonb_typeof(d->'supplier_unp') IS DISTINCT FROM 'string'
      OR length(d->>'supplier_unp') > 32))
    OR jsonb_typeof(d->'lines') IS DISTINCT FROM 'array'
    OR jsonb_typeof(d->'freight_byn') IS DISTINCT FROM 'string'
    OR (d->>'freight_byn') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
    OR jsonb_typeof(d->'eta_date') NOT IN ('null','string')
    OR (d->>'eta_date' IS NOT NULL AND (d->>'eta_date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
    OR jsonb_typeof(b) NOT IN ('null','object') THEN
    RAISE EXCEPTION 'Invalid order creation command';
  END IF;
  IF jsonb_array_length(d->'lines') NOT BETWEEN 1 AND 200
    OR (d->>'eta_date' IS NOT NULL AND (d->>'eta_date')::date::text IS DISTINCT FROM d->>'eta_date') THEN
    RAISE EXCEPTION 'Invalid order creation line count or date';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(d->'lines') LOOP
    IF (item IS DISTINCT FROM jsonb_build_object('sku_code',item->'sku_code','qty',item->'qty',
        'goods_value_byn',item->'goods_value_byn','weight',item->'weight','volume',item->'volume')
      AND item IS DISTINCT FROM jsonb_build_object('sku_code',item->'sku_code',
        'sku_id',item->'sku_id','sku_title',item->'sku_title','sku_unit',item->'sku_unit',
        'qty',item->'qty','goods_value_byn',item->'goods_value_byn',
        'weight',item->'weight','volume',item->'volume'))
      OR NOT procurement.order_command_text(item->'sku_code',64)
      OR (item ? 'sku_id' AND (jsonb_typeof(item->'sku_id') IS DISTINCT FROM 'number'
        OR (item->>'sku_id') !~ '^[1-9][0-9]*$'
        OR (item->>'sku_id')::numeric > 2147483647
        OR NOT procurement.order_command_text(item->'sku_title',255)
        OR NOT procurement.order_command_text(item->'sku_unit',16)))
      OR jsonb_typeof(item->'qty') IS DISTINCT FROM 'string'
      OR (item->>'qty') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
      OR jsonb_typeof(item->'goods_value_byn') IS DISTINCT FROM 'string'
      OR (item->>'goods_value_byn') !~ '^(0|[1-9][0-9]{0,11})\.[0-9]{2}$'
      OR jsonb_typeof(item->'weight') IS DISTINCT FROM 'string'
      OR (item->>'weight') !~ '^(0|[1-9][0-9]{0,10})\.[0-9]{3}$'
      OR jsonb_typeof(item->'volume') IS DISTINCT FROM 'string'
      OR (item->>'volume') !~ '^(0|[1-9][0-9]{0,9})\.[0-9]{4}$' THEN
      RAISE EXCEPTION 'Invalid order creation line';
    END IF;
    IF (item->>'qty')::numeric <= 0 THEN RAISE EXCEPTION 'Invalid order creation quantity'; END IF;
  END LOOP;
  SELECT count(DISTINCT value->>'sku_code') INTO position_count FROM jsonb_array_elements(d->'lines');
  IF position_count <> jsonb_array_length(d->'lines') THEN RAISE EXCEPTION 'Duplicate order creation SKU'; END IF;
  IF b <> 'null'::jsonb THEN
    IF b IS DISTINCT FROM jsonb_build_object('request_id',b->'request_id','expected_stage','approval',
         'expected_hash',b->'expected_hash','link_evidence',b->'link_evidence')
      OR jsonb_typeof(b->'request_id') IS DISTINCT FROM 'number'
      OR (NEW.command->'request_basis'->>'request_id') !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(b->'expected_hash') IS DISTINCT FROM 'string'
      OR (b->>'expected_hash') !~ '^[0-9a-f]{64}$'
      OR NOT procurement.order_command_text(b->'link_evidence',1000) THEN
      RAISE EXCEPTION 'Invalid order creation request basis';
    END IF;
    IF (b->>'request_id')::numeric > 2147483647 THEN RAISE EXCEPTION 'Invalid order creation request identifier'; END IF;
  END IF;
  IF NEW.command_hash IS DISTINCT FROM encode(sha256(convert_to(procurement.order_command_json(c),'UTF8')),'hex') THEN
    RAISE EXCEPTION 'Order creation command hash mismatch';
  END IF;
  expected := jsonb_build_object('organization_id',NEW.organization_id,'request_key',NEW.request_key,
                                'principal',NEW.actor,'outcome',NEW.outcome);
  IF coalesce(NEW.result->>'organization_id','') !~ '^[1-9][0-9]*$' THEN
    RAISE EXCEPTION 'Invalid order creation result identifier';
  END IF;
  IF NEW.outcome = 'rejected' THEN
    -- Each HTTP command owns one root transaction; a rejection may not leave
    -- an order inserted earlier or later in that transaction (deferred recheck).
    IF NEW.order_id IS NOT NULL OR NEW.ownership_id IS NOT NULL OR NEW.request_id IS NOT NULL
      OR NEW.request_ownership_id IS NOT NULL OR NEW.link_id IS NOT NULL
      OR coalesce(NEW.result->>'code','') NOT IN
         ('request_basis_changed','request_basis_unavailable','request_already_linked',
          'command_abandoned','sku_catalog_changed','supplier_catalog_changed')
      OR (NEW.result->>'code' IN ('request_basis_changed','request_basis_unavailable',
                                 'request_already_linked') AND b = 'null'::jsonb)
      OR EXISTS (SELECT 1 FROM procurement.order_insert_proof WHERE root_transaction=txid_current())
      OR NEW.result::jsonb IS DISTINCT FROM expected || jsonb_build_object('code',NEW.result->>'code','no_business_write',true) THEN
      RAISE EXCEPTION 'Invalid rejected order creation outcome';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.outcome IS DISTINCT FROM 'created' THEN RAISE EXCEPTION 'Invalid order creation outcome'; END IF;
  SELECT * INTO o FROM procurement.purchase_order WHERE id=NEW.order_id;
  SELECT * INTO owner_row FROM procurement.purchase_ownership WHERE id=NEW.ownership_id;
  IF o.id IS NULL OR owner_row.id IS NULL OR owner_row.kind IS DISTINCT FROM 'order'
    OR owner_row.source_id IS DISTINCT FROM o.id OR owner_row.organization_id IS DISTINCT FROM NEW.organization_id
    OR owner_row.actor IS DISTINCT FROM NEW.actor OR owner_row.evidence IS DISTINCT FROM c->>'ownership_evidence'
    OR o.status IS DISTINCT FROM 'draft' OR o.received_at IS NOT NULL
    OR o.supplier_id IS DISTINCT FROM (d->>'supplier_id')::integer
    OR o.transport_method_code IS NOT NULL OR o.target_arrival_date IS NOT NULL
    OR o.supplier IS DISTINCT FROM d->>'supplier' OR o.freight_byn IS DISTINCT FROM (d->>'freight_byn')::numeric
    OR o.eta_date::text IS DISTINCT FROM d->>'eta_date'
    OR owner_row.snapshot::jsonb IS DISTINCT FROM jsonb_build_object('number',o.number,'supplier',o.supplier,
         'supplier_id',o.supplier_id,'status','draft','eta_date',d->'eta_date')
    OR (d ? 'supplier_id' AND NOT EXISTS (SELECT 1 FROM procurement.supplier s
        WHERE s.id=o.supplier_id AND s.status='active' AND s.name=d->>'supplier'
          AND s.unp=d->>'supplier_unp')) THEN
    RAISE EXCEPTION 'Order creation initial ownership/header mismatch';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM procurement.order_insert_proof WHERE order_id=o.id AND root_transaction=txid_current()) THEN
    RAISE EXCEPTION 'Order creation package must originate in this transaction';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('id',id,'sku_code',sku_code,'qty',qty::text,
    'goods_value_byn',goods_value_byn::text,'weight',weight::text,'volume',volume::text) ORDER BY id)
    INTO actual_lines FROM procurement.purchase_order_line WHERE order_id=o.id;
  IF (SELECT jsonb_agg(value - 'id' ORDER BY ordinal)
      FROM jsonb_array_elements(actual_lines) WITH ORDINALITY AS lines(value,ordinal)) IS DISTINCT FROM
     (SELECT jsonb_agg(value - 'sku_id' - 'sku_title' - 'sku_unit' ORDER BY ordinal)
      FROM jsonb_array_elements(d->'lines') WITH ORDINALITY AS lines(value,ordinal)) THEN
    RAISE EXCEPTION 'Order creation initial lines mismatch';
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(d->'lines') LOOP
    IF item ? 'sku_id' AND NOT EXISTS (SELECT 1 FROM sku s
        WHERE s.id=(item->>'sku_id')::integer AND s.is_active
          AND s.code=item->>'sku_code' AND s.title=item->>'sku_title'
          AND s.unit=item->>'sku_unit') THEN
      RAISE EXCEPTION 'Order creation catalog SKU changed';
    END IF;
  END LOOP;
  snapshot := 'null'::jsonb;
  IF b = 'null'::jsonb THEN
    IF NEW.request_id IS NOT NULL OR NEW.request_ownership_id IS NOT NULL OR NEW.link_id IS NOT NULL THEN
      RAISE EXCEPTION 'Unexpected order creation request link';
    END IF;
  ELSE
    SELECT * INTO request_row FROM procurement.purchase_request WHERE id=NEW.request_id;
    SELECT * INTO request_owner FROM procurement.purchase_ownership WHERE id=NEW.request_ownership_id;
    SELECT * INTO link_row FROM procurement.order_request_link WHERE id=NEW.link_id;
    SELECT proof.snapshot INTO proof_snapshot FROM procurement.order_request_transition_proof proof
      WHERE proof.request_id=NEW.request_id AND proof.root_transaction=txid_current();
    snapshot := jsonb_build_object('request_id',request_row.id,'ownership_id',request_owner.id,
      'number',request_row.number,'supplier',request_row.supplier,'supplier_id',request_row.supplier_id,
      'item',request_row.item,'qty',request_row.qty::text,'amount',request_row.amount::text,
      'due_date',request_row.due_date,'stage','approval');
    IF request_row.id IS NULL OR request_owner.id IS NULL OR link_row.id IS NULL
      OR NEW.request_id IS DISTINCT FROM (b->>'request_id')::integer OR request_row.stage IS DISTINCT FROM 'po'
      OR request_owner.kind IS DISTINCT FROM 'request' OR request_owner.source_id IS DISTINCT FROM NEW.request_id
      OR request_owner.organization_id IS DISTINCT FROM NEW.organization_id
      OR link_row.organization_id IS DISTINCT FROM NEW.organization_id OR link_row.actor IS DISTINCT FROM NEW.actor
      OR link_row.order_ownership_id IS DISTINCT FROM NEW.ownership_id
      OR link_row.request_ownership_id IS DISTINCT FROM NEW.request_ownership_id
      OR link_row.evidence IS DISTINCT FROM b->>'link_evidence'
      OR (SELECT count(*) FROM procurement.order_request_link WHERE request_ownership_id=NEW.request_ownership_id) <> 1
      OR proof_snapshot IS DISTINCT FROM snapshot
      OR encode(sha256(convert_to(procurement.order_command_json(snapshot),'UTF8')),'hex') IS DISTINCT FROM b->>'expected_hash' THEN
      RAISE EXCEPTION 'Order creation approved request/link mismatch';
    END IF;
  END IF;
  expected := expected || jsonb_build_object('order_id',o.id,'ownership_id',NEW.ownership_id,'number',o.number,
    'status','draft','supplier',o.supplier,'eta_date',d->'eta_date','freight_byn',d->'freight_byn',
    'lines',actual_lines,'request_id',NEW.request_id,'request_ownership_id',NEW.request_ownership_id,
    'link_id',NEW.link_id,'request_snapshot',snapshot);
  IF NEW.result::jsonb IS DISTINCT FROM expected THEN RAISE EXCEPTION 'Order creation result mismatch'; END IF;
  FOREACH id_key IN ARRAY ARRAY['order_id','ownership_id','request_id','request_ownership_id','link_id'] LOOP
    IF NEW.result->>id_key IS NOT NULL AND (NEW.result->>id_key) !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'Invalid order creation result identifier';
    END IF;
  END LOOP;
  FOR index_number IN 0..jsonb_array_length(actual_lines)-1 LOOP
    IF coalesce(NEW.result->'lines'->index_number->>'id','') !~ '^[1-9][0-9]*$' THEN
      RAISE EXCEPTION 'Invalid order creation result line identifier';
    END IF;
  END LOOP;
  IF b <> 'null'::jsonb THEN
    FOREACH id_key IN ARRAY ARRAY['request_id','ownership_id','supplier_id'] LOOP
      IF NEW.result->'request_snapshot'->>id_key IS NOT NULL
        AND (NEW.result->'request_snapshot'->>id_key) !~ '^[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'Invalid order creation snapshot identifier';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;'''

EDIT_GUARD = r'''CREATE OR REPLACE FUNCTION procurement.guard_order_edit_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c jsonb:=NEW.command::jsonb; r jsonb:=NEW.result::jsonb; common jsonb; actual_line jsonb;
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
    IF NEW.action IN ('add_line','delete_line') THEN
      SELECT snapshot INTO actual_line FROM procurement.order_line_edit_proof
        WHERE root_transaction=txid_current() AND order_id=NEW.target_order_id
          AND action=NEW.action AND to_jsonb(line_id)=r#>'{effect,line,id}';
      IF actual_line IS NULL OR r->'effect' IS DISTINCT FROM jsonb_build_object('line',actual_line)
         OR (NEW.action='add_line' AND (c->'payload') - 'sku_id' - 'sku_title' - 'sku_unit'
             IS DISTINCT FROM actual_line-'id')
         OR (NEW.action='add_line' AND c->'payload' ? 'sku_id' AND NOT EXISTS
             (SELECT 1 FROM sku s WHERE s.id=(c#>>'{payload,sku_id}')::integer
                AND s.is_active AND s.code=c#>>'{payload,sku_code}'
                AND s.title=c#>>'{payload,sku_title}' AND s.unit=c#>>'{payload,sku_unit}'))
         OR (NEW.action='delete_line' AND c->'payload' IS DISTINCT FROM
           jsonb_build_object('line_id',actual_line->'id')) THEN
        RAISE EXCEPTION 'Order edit receipt lacks matching line mutation proof';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;'''


def upgrade():
    op.execute(CREATION_GUARD)
    op.execute(EDIT_GUARD)


def downgrade():
    raise RuntimeError(
        "Catalog-bound immutable procurement receipts cannot be replayed under the old guard"
    )
