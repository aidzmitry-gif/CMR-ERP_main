"""Admit the exact registered order snapshot in output-transfer WIP evidence."""

import hashlib
import runpy
from pathlib import Path

from alembic import op

revision = "0193"
down_revision = "crm_rel_001_auto_posting_01"
branch_labels = None
depends_on = None

OLD = """        OR (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_object_keys(l.dimensions::jsonb) k)
          IS DISTINCT FROM (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_array_elements_text(required_keys) k))"""

NEW = """        OR (
          (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_object_keys(l.dimensions::jsonb) k)
            IS DISTINCT FROM (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_array_elements_text(required_keys) k)
          AND NOT (
            order_key='order'
            AND (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_object_keys(l.dimensions::jsonb) k)
              IS NOT DISTINCT FROM (SELECT jsonb_agg(k ORDER BY k) FROM (
                SELECT jsonb_array_elements_text(required_keys) AS k
                UNION SELECT unnest(ARRAY['order','order_source','order_id','order_number','order_product',
                  'order_quantity','order_created_at','order_digest','order_stage_at_ownership']::text[])
              ) expected_keys)
            AND EXISTS (
              SELECT 1 FROM production.order_ownership own
              WHERE own.organization_id=org AND own.order_id>0 AND own.order_id::text=l.dimensions->>'order_id'
                AND jsonb_typeof(own.snapshot::jsonb)='object'
                AND own.snapshot::jsonb->'order_id'=to_jsonb(own.order_id)
                AND own.snapshot->>'order_id'=own.order_id::text
                AND jsonb_typeof(own.snapshot::jsonb->'quantity')='number'
                AND own.snapshot->>'quantity' ~ '^[1-9][0-9]{0,9}$'
                AND (CASE WHEN own.snapshot->>'quantity' ~ '^[1-9][0-9]{0,9}$'
                     THEN (own.snapshot->>'quantity')::numeric END)<=2147483647
                AND jsonb_typeof(own.snapshot::jsonb->'number')='string'
                AND length(own.snapshot->>'number') BETWEEN 1 AND 200
                AND nullif(btrim(own.snapshot->>'number'),'') IS NOT NULL
                AND jsonb_typeof(own.snapshot::jsonb->'product')='string'
                AND length(own.snapshot->>'product') BETWEEN 1 AND 200
                AND nullif(btrim(own.snapshot->>'product'),'') IS NOT NULL
                AND jsonb_typeof(own.snapshot::jsonb->'stage')='string'
                AND length(own.snapshot->>'stage') BETWEEN 1 AND 200
                AND nullif(btrim(own.snapshot->>'stage'),'') IS NOT NULL
                AND jsonb_typeof(own.snapshot::jsonb->'created_at')='string'
                AND length(own.snapshot->>'created_at')<=200
                AND position('T' in own.snapshot->>'created_at')>0
                AND own.digest=accounting.financial_sha(own.snapshot::jsonb)
                AND l.dimensions::jsonb @> jsonb_build_object(
                  'order',own.snapshot->>'number','order_source','production','order_id',own.order_id::text,
                  'order_number',own.snapshot->>'number','order_product',own.snapshot->>'product',
                  'order_quantity',own.snapshot->>'quantity','order_created_at',own.snapshot->>'created_at',
                  'order_digest',own.digest,'order_stage_at_ownership',own.snapshot->>'stage')
            )
          )
        ))"""


def previous_function():
    frozen = runpy.run_path(str(Path(__file__).with_name("crm_rel_001_finished_goods_01.py")))
    value = frozen["function"](frozen["definitions"](), "validate_shipment_output_layer")
    if hashlib.sha256(value.encode()).hexdigest() != "54f1835144111c179caa2716996c2c498aaeb822b520dc42f644a0000702d311":
        raise RuntimeError("Frozen output WIP validator changed")
    return value


def definition():
    value = previous_function()
    if value.count(OLD) != 1:
        raise RuntimeError("Expected one output WIP dimension predicate")
    return value.replace(OLD, NEW)


def upgrade():
    op.execute(definition())


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (
        SELECT 1 FROM accounting.production_output_transfer_receipt r,
          LATERAL jsonb_array_elements(r.basis::jsonb->'wip'->'source_lines') source
        WHERE source->'dimensions' ? 'order_digest'
      ) THEN
        RAISE EXCEPTION 'Cannot downgrade accepted owned-order output history; restore a verified backup';
      END IF;
    END $$;""")
    op.execute(previous_function())
