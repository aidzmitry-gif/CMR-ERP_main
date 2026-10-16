"""Authenticate V4 issue receipts and replay complete zero-cost allocations."""
import runpy
from pathlib import Path

from alembic import op

revision = "0147"
down_revision = "0146"
branch_labels = None
depends_on = None


def _function(ddl, name):
    start = ddl.index(f"CREATE OR REPLACE FUNCTION accounting.{name}")
    return ddl[start:ddl.index("END $$;", start) + len("END $$;")]


def guard_definition():
    definitions = runpy.run_path(str(Path(__file__).with_name("0143_zero_value_sales.py")))["definitions"]()
    guard = _function(definitions, "guard_inventory_zero_value_disposal")
    anchor = "BEGIN\n  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;"
    v4 = """BEGIN
  IF NEW.command::jsonb->>'command_version'='4' THEN
    PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
    IF NOT EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id
      AND month=to_char(NEW.posting_date,'YYYY-MM') AND NOT closed) THEN
      RAISE EXCEPTION 'V4 zero-value allocation requires an open period';
    END IF;
    IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id
      AND month>=to_char(NEW.posting_date,'YYYY-MM') AND closed) THEN
      RAISE EXCEPTION 'V4 zero-value allocation would change a closed period';
    END IF;
    IF EXISTS (SELECT 1 FROM accounting.entry WHERE organization_id=NEW.organization_id
      AND source=NEW.source AND source_version=NEW.source_version AND operation='inventory_issue') THEN
      RAISE EXCEPTION 'Entry identity is already reserved by a V4 zero-value allocation';
    END IF;
    IF NEW.operation IS DISTINCT FROM 'inventory_issue' OR NEW.entry_id IS NOT NULL
      OR NEW.command::jsonb->>'operation' IS DISTINCT FROM NEW.operation
      OR NEW.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object('organization_id',NEW.organization_id,'actor',NEW.actor,'command',NEW.command::jsonb))
      OR NEW.basis_digest IS DISTINCT FROM accounting.zero_value_allocation_basis(NEW.organization_id,NEW.command::jsonb,NEW.registration_token)
      OR NEW.command::jsonb->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
      OR NEW.command::jsonb->>'source' IS DISTINCT FROM NEW.source
      OR (NEW.command::jsonb->>'source_version')::integer IS DISTINCT FROM NEW.source_version
      OR (NEW.command::jsonb->>'policy_id')::integer IS DISTINCT FROM NEW.policy_id
      OR (NEW.command::jsonb->>'posting_date')::date IS DISTINCT FROM NEW.posting_date THEN
      RAISE EXCEPTION 'V4 zero-value allocation receipt is not authenticated';
    END IF;
    RETURN NEW;
  END IF;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;"""
    if guard.count(anchor) != 1:
        raise RuntimeError("0147 guard anchor changed")
    return guard.replace(anchor, v4)


STREAM = r"""
CREATE FUNCTION accounting.zero_allocation_cost_stream(
 org integer, account text, warehouse text, sku text, cutoff date, registration_cutoff integer
) RETURNS TABLE(event_key text, receipt_id integer, registration_token integer,
 posting_date date, ordinal integer, source_entry_id integer, source_line_id integer,
 quantity numeric, inventory_dimensions jsonb, destination_account text, destination_dimensions jsonb,
 digest text) LANGUAGE plpgsql AS $$
DECLARE z record; p record; c jsonb;
BEGIN
 PERFORM 1 FROM accounting.organization WHERE id=org FOR UPDATE;
 FOR z IN SELECT r.* FROM accounting.inventory_zero_value_disposal_receipt r
   WHERE r.organization_id=org AND r.command::jsonb->>'command_version'='4'
     AND (registration_cutoff IS NULL OR r.registration_token<registration_cutoff)
     AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.command::jsonb->'inventory_layers') x
       WHERE x->>'inventory_account'=account AND x->'inventory_dimensions'->>'warehouse'=warehouse
         AND x->'inventory_dimensions'->>'sku'=sku)
   ORDER BY r.posting_date,r.registration_token,r.id
 LOOP
   c:=z.command::jsonb;
   IF z.operation IS DISTINCT FROM 'inventory_issue' OR z.entry_id IS NOT NULL
     OR c->>'operation' IS DISTINCT FROM z.operation OR c->>'source' IS DISTINCT FROM z.source
     OR (c->>'source_version')::integer IS DISTINCT FROM z.source_version
     OR (c->>'policy_id')::integer IS DISTINCT FROM z.policy_id
     OR c->>'posting_date' IS DISTINCT FROM z.posting_date::text
     OR c->>'basis_digest' IS DISTINCT FROM z.basis_digest
     OR z.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object(
       'organization_id',org,'actor',z.actor,'command',c))
     OR z.basis_digest IS DISTINCT FROM accounting.zero_value_allocation_basis(org,c,z.registration_token) THEN
     RAISE EXCEPTION 'Zero allocation stream receipt authentication failed';
   END IF;
   IF z.posting_date>cutoff THEN RAISE EXCEPTION 'Late cost cannot ignore a future zero allocation'; END IF;
   FOR p IN SELECT value,ordinality FROM jsonb_array_elements(c->'inventory_layers') WITH ORDINALITY LOOP
     receipt_id:=z.id; registration_token:=z.registration_token; posting_date:=z.posting_date;
     ordinal:=p.ordinality; source_entry_id:=(p.value->>'source_entry_id')::integer;
     source_line_id:=(p.value->>'source_line_id')::integer; quantity:=(p.value->>'quantity')::numeric;
     event_key:='zeroallocation:'||z.id||':'||z.registration_token||':'||source_entry_id||':'||source_line_id;
     inventory_dimensions:=p.value->'inventory_dimensions'; destination_account:=c->>'destination_account';
     destination_dimensions:=c->'destination_dimensions'; digest:=z.digest;
     RETURN NEXT;
   END LOOP;
 END LOOP;
END $$;
"""


def replace_once(value, old, new):
    if value.count(old) != 1:
        raise RuntimeError(f"0147 expected one anchor: {old[:100]}")
    return value.replace(old, new)


def validator_definition():
    definitions = runpy.run_path(str(Path(__file__).with_name("0143_zero_value_sales.py")))["definitions"]()
    sql = _function(definitions, "validate_zero_value_disposal_command")
    return replace_once(sql, "BEGIN\n", """BEGIN
  IF c->>'command_version'='4' THEN
    IF jsonb_typeof(c->'command_version') IS DISTINCT FROM 'number'
      OR c->'command_version'::text IS DISTINCT FROM '4'
      OR c->>'operation' IS DISTINCT FROM 'inventory_issue' THEN
      RAISE EXCEPTION 'V4 supports integer versioned issues only';
    END IF;
    -- The receipt guard authenticates the complete V4 document with 0146.
    RETURN;
  END IF;
""")


def cost_definitions():
    previous = runpy.run_path(str(Path(__file__).with_name("0145_inventory_allocation_cost_stream.py")))
    results = []
    for pool in (True, False):
        sql = previous["pool_definition" if pool else "evidence_definition"]()
        # All events enter the same chronological arithmetic as monetary disposals.
        sql = replace_once(sql, "), events AS (", """), zeros AS MATERIALIZED (
      SELECT * FROM accounting.zero_allocation_cost_stream(org,origin.account_code,
        origin.dimensions->>'warehouse',origin.dimensions->>'sku',cutoff,registration_cutoff)
    ), events AS (""")
        end = "    ) SELECT * FROM events ORDER BY "
        prefix = ("z.posting_date,z.ordinal,z.registration_token,'zero_value_allocation',z.digest,NULL::integer,v.*,z.event_key"
                  if pool else "z.registration_token,'zero_value_allocation',z.digest,v.*,z.event_key,z.ordinal")
        zero_select = """      UNION ALL
      SELECT """ + prefix + """
      FROM zeros z CROSS JOIN LATERAL jsonb_populate_record(NULL::accounting.line,jsonb_build_object(
        'account_code',origin.account_code,'side','credit','quantity',z.quantity,'amount',0,
        'dimensions',z.inventory_dimensions,'currency','BYN','category','asset','cash',false)) v
""" + ("" if pool else "      WHERE z.source_entry_id=output_id AND z.source_line_id=origin.id\n")
        sql = replace_once(sql, end, zero_select + end)
        start = sql.index("    saved := NULL;")
        finish_marker = "    share :=" if pool else "    remainder_qty := remainder_qty-movement.quantity;"
        finish = sql.index(finish_marker, start)
        old_validation = sql[start:finish]
        branch = """    IF movement.operation='zero_value_allocation' THEN
      SELECT z.destination_account,z.destination_dimensions INTO STRICT destination.account_code,destination.dimensions
        FROM accounting.zero_allocation_cost_stream(org,origin.account_code,
          origin.dimensions->>'warehouse',origin.dimensions->>'sku',cutoff,registration_cutoff) z
        WHERE z.event_key=movement.allocation_key;
    ELSE
""" + old_validation + "    END IF;\n"
        sql = sql[:start] + branch + sql[finish:]
        if not pool:
            # Keep the legacy single-layer branch intact, but never replay V4 twice.
            sql = replace_once(sql, "WHERE z.organization_id=org", "WHERE z.command::jsonb->>'command_version' IS DISTINCT FROM '4' AND z.organization_id=org")
        results.append(sql)
    return "\n".join(results)


def upgrade():
    op.execute(STREAM)
    op.execute(cost_definitions())
    op.execute(validator_definition())
    op.execute(guard_definition())
    op.execute("CREATE FUNCTION accounting.zero_value_allocation_runtime_version() RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 4'")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE command::jsonb->>'command_version'='4') THEN
        RAISE EXCEPTION 'Cannot downgrade 0147 with V4 zero-value history';
      END IF;
    END $$;""")
    previous = runpy.run_path(str(Path(__file__).with_name("0145_inventory_allocation_cost_stream.py")))
    op.execute(previous["pool_definition"]())
    op.execute(previous["evidence_definition"]())
    op.execute("DROP FUNCTION accounting.zero_allocation_cost_stream(integer,text,text,text,date,integer)")
    op.execute(runpy.run_path(str(Path(__file__).with_name("0143_zero_value_sales.py")))["definitions"]())
    op.execute("DROP FUNCTION accounting.zero_value_allocation_runtime_version()")
