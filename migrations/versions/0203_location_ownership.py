"""Persist warehouse location ownership without guessing legacy owners."""

import sqlalchemy as sa
from alembic import op

revision = "0203"
down_revision = "0202"
branch_labels = None
depends_on = None


_PREVIOUS_OUTPUT_GUARD = "CREATE OR REPLACE FUNCTION production.guard_output_document_insert() RETURNS trigger\nLANGUAGE plpgsql AS $$\nDECLARE o record;\nDECLARE s record;\nDECLARE p record;\nDECLARE c jsonb := NEW.command::jsonb;\nDECLARE snap jsonb := NEW.snapshot::jsonb;\nBEGIN\n  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output organization is missing'; END IF;\n  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output order is missing'; END IF;\n  IF NOT EXISTS (SELECT 1 FROM production.order_ownership\n      WHERE order_id=NEW.order_id AND organization_id=NEW.organization_id)\n    OR o.completed_at IS NOT NULL OR o.stage='done' THEN\n    RAISE EXCEPTION 'Output order is not available in this organization';\n  END IF;\n  SELECT * INTO s FROM public.sku WHERE code=c->>'sku_code' FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output SKU is missing'; END IF;\n  SELECT * INTO p FROM wms.location WHERE id=(c->>'location_id')::integer FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output receiving place is missing'; END IF;\n  IF NOT s.is_active OR NULLIF(btrim(s.unit),'') IS NULL OR NOT p.is_active\n    OR p.warehouse IS DISTINCT FROM c->>'warehouse'\n    OR c->'order_id' IS DISTINCT FROM to_jsonb(NEW.order_id)\n    OR c->>'request_id' IS DISTINCT FROM NEW.request_id\n    OR jsonb_typeof(c) IS DISTINCT FROM 'object'\n    OR jsonb_typeof(c->'quantity') IS DISTINCT FROM 'string'\n    OR coalesce(c->>'quantity','') !~ '^[0-9]{1,12}(\\.[0-9]{1,2})?$'\n    OR (c->>'quantity')::numeric<=0\n    OR NULLIF(btrim(NEW.actor),'') IS NULL\n    OR NEW.digest !~ '^[a-f0-9]{64}$'\n    OR snap IS DISTINCT FROM jsonb_build_object(\n      'organization_id', NEW.organization_id, 'principal', NEW.actor,\n      'command', c, 'posted', false, 'confirmation_available', false,\n      'order_snapshot', jsonb_build_object('order_id', o.id, 'number', o.number,\n        'product', o.product, 'quantity', o.qty, 'stage', o.stage,\n        'created_at', snap->'order_snapshot'->'created_at'),\n      'sku_snapshot', jsonb_build_object('id',s.id,'code',s.code,'title',s.title,'unit',s.unit),\n      'receiving_place', jsonb_build_object('location_id',p.id,'warehouse',p.warehouse,\n        'code',p.code,'zone',p.zone,'title',p.title))\n    OR (snap->'order_snapshot'->>'created_at')::timestamptz IS DISTINCT FROM o.created_at THEN\n    RAISE EXCEPTION 'Output document does not match its source';\n  END IF;\n  RETURN NEW;\nEND $$;"

_OWNED_OUTPUT_GUARD = "CREATE OR REPLACE FUNCTION production.guard_output_document_insert() RETURNS trigger\nLANGUAGE plpgsql AS $$\nDECLARE o record;\nDECLARE s record;\nDECLARE p record;\nDECLARE c jsonb := NEW.command::jsonb;\nDECLARE snap jsonb := NEW.snapshot::jsonb;\nBEGIN\n  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output organization is missing'; END IF;\n  SELECT * INTO o FROM production.production_order WHERE id=NEW.order_id FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output order is missing'; END IF;\n  IF NOT EXISTS (SELECT 1 FROM production.order_ownership\n      WHERE order_id=NEW.order_id AND organization_id=NEW.organization_id)\n    OR o.completed_at IS NOT NULL OR o.stage='done' THEN\n    RAISE EXCEPTION 'Output order is not available in this organization';\n  END IF;\n  SELECT * INTO s FROM public.sku WHERE code=c->>'sku_code' FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output SKU is missing'; END IF;\n  SELECT * INTO p FROM wms.location WHERE id=(c->>'location_id')::integer FOR UPDATE;\n  IF NOT FOUND THEN RAISE EXCEPTION 'Output receiving place is missing'; END IF;\n  IF NOT s.is_active OR NULLIF(btrim(s.unit),'') IS NULL OR NOT p.is_active\n    OR p.organization_id IS DISTINCT FROM NEW.organization_id\n    OR NOT EXISTS (SELECT 1 FROM wms.warehouse_directory w\n      WHERE w.organization_id=NEW.organization_id AND w.name=p.warehouse AND w.is_active)\n    OR p.warehouse IS DISTINCT FROM c->>'warehouse'\n    OR c->'order_id' IS DISTINCT FROM to_jsonb(NEW.order_id)\n    OR c->>'request_id' IS DISTINCT FROM NEW.request_id\n    OR jsonb_typeof(c) IS DISTINCT FROM 'object'\n    OR jsonb_typeof(c->'quantity') IS DISTINCT FROM 'string'\n    OR coalesce(c->>'quantity','') !~ '^[0-9]{1,12}(\\.[0-9]{1,2})?$'\n    OR (c->>'quantity')::numeric<=0\n    OR NULLIF(btrim(NEW.actor),'') IS NULL\n    OR NEW.digest !~ '^[a-f0-9]{64}$'\n    OR snap IS DISTINCT FROM jsonb_build_object(\n      'organization_id', NEW.organization_id, 'principal', NEW.actor,\n      'command', c, 'posted', false, 'confirmation_available', false,\n      'order_snapshot', jsonb_build_object('order_id', o.id, 'number', o.number,\n        'product', o.product, 'quantity', o.qty, 'stage', o.stage,\n        'created_at', snap->'order_snapshot'->'created_at'),\n      'sku_snapshot', jsonb_build_object('id',s.id,'code',s.code,'title',s.title,'unit',s.unit),\n      'receiving_place', jsonb_build_object('location_id',p.id,'warehouse',p.warehouse,\n        'code',p.code,'zone',p.zone,'title',p.title))\n    OR (snap->'order_snapshot'->>'created_at')::timestamptz IS DISTINCT FROM o.created_at THEN\n    RAISE EXCEPTION 'Output document does not match its source';\n  END IF;\n  RETURN NEW;\nEND $$;"


def upgrade() -> None:
    op.add_column("location", sa.Column("organization_id", sa.Integer(), nullable=True), schema="wms")
    op.create_check_constraint("wms_location_org_positive", "location", "organization_id > 0", schema="wms")
    op.create_foreign_key("fk_wms_location_warehouse", "location", "warehouse_directory",
                         ["organization_id", "warehouse"], ["organization_id", "name"],
                         source_schema="wms", referent_schema="wms")
    op.create_index("ix_wms_location_organization_id", "location", ["organization_id"], schema="wms")
    op.execute(_OWNED_OUTPUT_GUARD)


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM wms.location WHERE organization_id IS NOT NULL)"
    )).scalar_one():
        raise RuntimeError("Location ownership must be preserved before downgrading 0203")
    op.execute(_PREVIOUS_OUTPUT_GUARD)
    op.drop_index("ix_wms_location_organization_id", table_name="location", schema="wms")
    op.drop_constraint("fk_wms_location_warehouse", "location", schema="wms", type_="foreignkey")
    op.drop_constraint("wms_location_org_positive", "location", schema="wms", type_="check")
    op.drop_column("location", "organization_id", schema="wms")
