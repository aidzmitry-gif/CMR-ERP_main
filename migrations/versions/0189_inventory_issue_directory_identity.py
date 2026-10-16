"""Bind new accountant inventory issues to warehouse and SKU directories."""

import runpy
from pathlib import Path

from alembic import op

revision = "0189"
down_revision = "0188"
branch_labels = None
depends_on = None


def _current_validator():
    """Rebuild the validator installed by 0150, before the V6 extension."""
    _, validator, _, _ = runpy.run_path(
        str(Path(__file__).with_name("0148_zero_value_allocated_sales.py"))
    )["definitions"]()
    validator = (validator.replace("='4' THEN", " IN ('4','5') THEN", 1)
        .replace("c->'command_version'::text IS DISTINCT FROM '4'", "c->'command_version'::text NOT IN ('4','5')")
        .replace("V4 supports integer versioned issues only", "V4/V5 support integer versioned issues only"))
    return validator


def _validator_with_v6():
    validator = _current_validator()
    anchor = "BEGIN\n"
    if validator.count(anchor) != 1:
        raise RuntimeError("0189 zero-value validator anchor changed")
    branch = """BEGIN
  IF c->>'command_version'='6' THEN
    IF jsonb_typeof(c->'command_version') IS DISTINCT FROM 'number'
       OR c->'command_version'::text IS DISTINCT FROM '6'
       OR c->>'operation' IS DISTINCT FROM 'inventory_issue'
       OR jsonb_typeof(c->'document') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'V6 requires one complete directory-bound inventory issue';
    END IF;
    c := jsonb_set(c,'{command_version}','2'::jsonb);
  END IF;
"""
    return validator.replace(anchor, branch, 1)


DIRECTORY_DDL = r"""
CREATE FUNCTION accounting.validate_inventory_issue_directory_document(org integer, d jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE w jsonb; s jsonb;
BEGIN
  IF org IS NULL OR org<=0 OR jsonb_typeof(d) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Inventory issue directory document is invalid';
  END IF;
  w:=d->'warehouse_identity'; s:=d->'sku_identity';
  IF jsonb_typeof(w) IS DISTINCT FROM 'object' OR jsonb_typeof(s) IS DISTINCT FROM 'object'
     OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(w) k)
        IS DISTINCT FROM ARRAY['id','name','title']
     OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(s) k)
        IS DISTINCT FROM ARRAY['code','id','title','unit']
     OR jsonb_typeof(w->'id') IS DISTINCT FROM 'number' OR (w->'id')::text !~ '^[1-9][0-9]{0,9}$'
     OR jsonb_typeof(s->'id') IS DISTINCT FROM 'number' OR (s->'id')::text !~ '^[1-9][0-9]{0,9}$'
     OR (w->>'id')::numeric>2147483647 OR (s->>'id')::numeric>2147483647
     OR jsonb_typeof(w->'name') IS DISTINCT FROM 'string'
     OR jsonb_typeof(w->'title') IS DISTINCT FROM 'string'
     OR jsonb_typeof(s->'code') IS DISTINCT FROM 'string'
     OR jsonb_typeof(s->'title') IS DISTINCT FROM 'string'
     OR jsonb_typeof(s->'unit') IS DISTINCT FROM 'string'
     OR d->'warehouse' IS DISTINCT FROM w->'name' OR d->'sku' IS DISTINCT FROM s->'code' THEN
    RAISE EXCEPTION 'Inventory issue directory snapshot is incomplete or inconsistent';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM wms.warehouse_directory x
      WHERE x.id=(w->>'id')::integer AND x.organization_id=org AND x.is_active
        AND x.name=w->>'name' AND x.title=w->>'title') THEN
    RAISE EXCEPTION 'Inventory issue warehouse directory snapshot changed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.sku x
      WHERE x.id=(s->>'id')::integer AND x.is_active
        AND x.code=s->>'code' AND x.title=s->>'title' AND x.unit=s->>'unit') THEN
    RAISE EXCEPTION 'Inventory issue SKU directory snapshot changed';
  END IF;
END $$;

CREATE FUNCTION accounting.guard_inventory_issue_directory_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.command::jsonb ? 'warehouse_identity' OR NEW.command::jsonb ? 'sku_identity' THEN
    PERFORM accounting.validate_inventory_issue_directory_document(NEW.organization_id,NEW.command::jsonb);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inventory_issue_directory_receipt
BEFORE INSERT ON accounting.inventory_issue_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_inventory_issue_directory_receipt();

CREATE FUNCTION accounting.guard_zero_value_issue_directory_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c jsonb:=NEW.command::jsonb;
BEGIN
  IF NEW.operation='inventory_issue' AND c->>'command_version' IN ('4','6') THEN
    PERFORM accounting.validate_inventory_issue_directory_document(NEW.organization_id,c->'document');
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_zero_value_issue_directory_receipt
BEFORE INSERT ON accounting.inventory_zero_value_disposal_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_zero_value_issue_directory_receipt();

CREATE FUNCTION accounting.inventory_issue_directory_version()
RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 1';
"""


def upgrade():
    op.execute(_validator_with_v6())
    op.execute(DIRECTORY_DDL)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_issue_receipt
          WHERE command::jsonb ? 'warehouse_identity' OR command::jsonb ? 'sku_identity')
         OR EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt
          WHERE command::jsonb->>'command_version'='6'
             OR (operation='inventory_issue' AND command::jsonb->>'command_version'='4'
                 AND command::jsonb->'document' ? 'warehouse_identity')) THEN
        RAISE EXCEPTION 'Cannot downgrade 0189 with directory-bound inventory issue history';
      END IF;
    END $$;
    DROP TRIGGER guard_inventory_issue_directory_receipt ON accounting.inventory_issue_receipt;
    DROP TRIGGER guard_zero_value_issue_directory_receipt ON accounting.inventory_zero_value_disposal_receipt;
    DROP FUNCTION accounting.guard_inventory_issue_directory_receipt();
    DROP FUNCTION accounting.guard_zero_value_issue_directory_receipt();
    DROP FUNCTION accounting.validate_inventory_issue_directory_document(integer,jsonb);
    DROP FUNCTION accounting.inventory_issue_directory_version();""")
    op.execute(_current_validator())
