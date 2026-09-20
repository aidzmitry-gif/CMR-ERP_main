"""Expose complete explicit disposal portions to late-cost calculations."""
import runpy
from pathlib import Path

from alembic import op

revision = "0145"
down_revision = "0144"
branch_labels = None
depends_on = None

DDL = r"""
CREATE FUNCTION accounting.inventory_allocation_cost_stream(
  org integer, inventory_account text, warehouse text, sku text, cutoff date,
  registration_cutoff integer DEFAULT NULL
) RETURNS TABLE (
  event_key text, disposition_entry_id integer, source_entry_id integer, source_line_id integer,
  posting_date date, ordinal integer, quantity numeric, book numeric,
  destination_account text, destination_dimensions jsonb, inventory_dimensions jsonb, valuation_method text
) LANGUAGE plpgsql AS $$
DECLARE saved record; portion record;
BEGIN
  IF org IS NULL OR org<=0 OR inventory_account IS NULL OR warehouse IS NULL OR sku IS NULL OR cutoff IS NULL THEN
    RAISE EXCEPTION 'Explicit allocation stream needs a complete pool identity';
  END IF;
  FOR saved IN
    SELECT e.id, e.posting_date, r.cost, r.command FROM accounting.entry e JOIN (
      SELECT entry_id, cost::jsonb cost, command::jsonb command FROM accounting.inventory_issue_receipt
      UNION ALL
      SELECT entry_id, cost::jsonb cost, command::jsonb command FROM accounting.inventory_sale_receipt
    ) r ON r.entry_id=e.id
    WHERE e.organization_id=org AND r.cost ? 'source_allocation_version'
      AND r.command->>'account'=inventory_account
      AND r.command->>'warehouse'=warehouse AND r.command->>'sku'=sku
      AND (registration_cutoff IS NULL OR e.id<registration_cutoff)
    ORDER BY e.posting_date,e.id
  LOOP
    PERFORM accounting.validate_inventory_allocation_link(saved.id);
    IF saved.posting_date>cutoff THEN
      RAISE EXCEPTION 'Late cost cannot ignore a future explicit allocation';
    END IF;
    FOR portion IN SELECT value, ordinality FROM jsonb_array_elements(saved.cost->'inventory_layers') WITH ORDINALITY LOOP
      disposition_entry_id:=saved.id;
      source_entry_id:=(portion.value->>'source_entry_id')::integer;
      source_line_id:=(portion.value->>'source_line_id')::integer;
      event_key:='allocation'||chr(58)||saved.id||chr(58)||source_entry_id||chr(58)||source_line_id;
      posting_date:=saved.posting_date;
      ordinal:=portion.ordinality;
      quantity:=(portion.value->>'quantity')::numeric;
      book:=(portion.value->>'amount_byn')::numeric;
      destination_account:=saved.command->>'expense_account';
      destination_dimensions:=coalesce(saved.command->'expense_dimensions','{}'::jsonb);
      inventory_dimensions:=portion.value->'dimensions';
      valuation_method:=saved.cost->>'method';
      RETURN NEXT;
    END LOOP;
  END LOOP;
END $$;
"""


def pool_definition():
    previous = runpy.run_path(str(Path(__file__).with_name("0139_production_output_cost_revision.py")))["DDL"]
    start = previous.index("CREATE OR REPLACE FUNCTION accounting.output_pool_revision_rows(")
    end = previous.index("END $$;", start) + len("END $$;")
    definition = previous[start:end]
    begin = definition.index("  FOR movement IN\n")
    finish = definition.index("  LOOP\n", begin)
    stream = """  FOR movement IN
    WITH portions AS MATERIALIZED (
      SELECT * FROM accounting.inventory_allocation_cost_stream(org,origin.account_code,
        origin.dimensions->>'warehouse',origin.dimensions->>'sku',cutoff,registration_cutoff)
      WHERE disposition_entry_id<>coalesce(excluded_entry,-1)
    ), events AS (
      SELECT e.posting_date movement_date,l.id movement_order,e.id movement_id,e.operation,e.digest,e.correction_of,
        l.*,NULL::text allocation_key
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=org AND e.posting_date<=cutoff
        AND e.id<>coalesce(excluded_entry,-1) AND l.account_code=origin.account_code
        AND (registration_cutoff IS NULL OR e.id<registration_cutoff)
        AND l.dimensions->>'warehouse'=origin.dimensions->>'warehouse'
        AND l.dimensions->>'sku'=origin.dimensions->>'sku'
        AND NOT (l.side='credit' AND EXISTS (SELECT 1 FROM portions s WHERE s.disposition_entry_id=e.id))
      UNION ALL
      SELECT s.posting_date,s.ordinal,e.id,e.operation,e.digest,e.correction_of,v.*,s.event_key
      FROM portions s JOIN accounting.entry e ON e.id=s.disposition_entry_id
      CROSS JOIN LATERAL jsonb_populate_record(NULL::accounting.line,jsonb_build_object(
        'entry_id',e.id,'account_code',origin.account_code,'side','credit',
        'quantity',s.quantity,'amount',s.book,'dimensions',s.inventory_dimensions,
        'currency','BYN','category','asset','cash',false)) v
    ) SELECT * FROM events ORDER BY movement_date,movement_id,movement_order
"""
    definition = definition[:begin] + stream + definition[finish:]
    def replace_once(old, new):
        nonlocal definition
        if definition.count(old) != 1:
            raise RuntimeError(f"0145 pool anchor must occur once: {old[:60]}")
        definition = definition.replace(old, new)

    replace_once("org integer, output_id integer, cutoff date, excluded_entry integer\n)",
        "org integer, output_id integer, cutoff date, excluded_entry integer, registration_cutoff integer\n)")
    replace_once("WHERE r.organization_id=org AND r.original_entry_id=output_id;",
        "WHERE r.organization_id=org AND r.original_entry_id=output_id\n"
        "      AND (registration_cutoff IS NULL OR r.registration_token<registration_cutoff);")
    # Explicit portions have no ledger line ID. Their own stable key carries provenance.
    legacy_key = "'disposed:'||movement.movement_id||':'||movement.id"
    if definition.count(legacy_key) != 2:
        raise RuntimeError("0145 requires both weighted disposal key anchors")
    definition = definition.replace(legacy_key, f"coalesce(movement.allocation_key,{legacy_key})")
    return definition + """
CREATE OR REPLACE FUNCTION accounting.output_pool_revision_rows(
  org integer, output_id integer, cutoff date, excluded_entry integer
) RETURNS jsonb LANGUAGE sql AS $$
  SELECT accounting.output_pool_revision_rows(org,output_id,cutoff,excluded_entry,NULL)
$$;
"""


def evidence_definition(*, upgraded=True):
    """Retain 0143's zero-sale history and pass the registration boundary to pools."""
    namespace = runpy.run_path(str(Path(__file__).with_name("0141_zero_value_output_cost.py")))
    evidence = namespace["_definitions"]()

    def replace_once(old, new):
        nonlocal evidence
        if evidence.count(old) != 1:
            raise RuntimeError(f"0145 evidence anchor must occur once: {old[:60]}")
        evidence = evidence.replace(old, new)

    replace_once("z.operation='inventory_issue' AND z.entry_id IS NULL",
        "((z.operation='inventory_issue' AND z.entry_id IS NULL) OR "
        "(z.operation='inventory_sale' AND z.entry_id=z.registration_token))")
    replace_once("    IF zero_receipt.posting_date>cutoff THEN", """    IF zero_receipt.operation='inventory_sale' THEN
      PERFORM accounting.validate_zero_sale_link(zero_receipt.entry_id);
    END IF;
    IF zero_receipt.posting_date>cutoff THEN""")
    if upgraded:
        replace_once("accounting.output_pool_revision_rows(org,output_id,cutoff,excluded_entry)",
            "accounting.output_pool_revision_rows(org,output_id,cutoff,excluded_entry,registration_cutoff)")
        begin = evidence.index("  FOR movement IN\n")
        finish = evidence.index("  LOOP\n", begin)
        evidence = evidence[:begin] + """  FOR movement IN
    WITH portions AS MATERIALIZED (
      SELECT * FROM accounting.inventory_allocation_cost_stream(org,origin.account_code,
        origin.dimensions->>'warehouse',origin.dimensions->>'sku',cutoff,registration_cutoff)
      WHERE disposition_entry_id<>coalesce(excluded_entry,-1)
    ), events AS (
      SELECT e.id movement_id,e.operation,e.digest,l.*,NULL::text allocation_key,l.id movement_order
      FROM accounting.entry e JOIN accounting.line l ON l.entry_id=e.id
      WHERE e.organization_id=org AND e.posting_date<=cutoff
        AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)
        AND (registration_cutoff IS NULL OR e.id<registration_cutoff)
        AND l.account_code=origin.account_code AND l.dimensions::jsonb=origin.dimensions::jsonb
        AND NOT EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r
                        WHERE r.entry_id=e.id AND r.organization_id=org)
        AND NOT (l.side='debit' AND e.operation='production_output_transfer' AND EXISTS (
          SELECT 1 FROM accounting.production_output_transfer_receipt r
          WHERE r.entry_id=e.id AND r.organization_id=org AND r.digest=e.digest))
        AND NOT (l.side='credit' AND EXISTS (SELECT 1 FROM portions s WHERE s.disposition_entry_id=e.id))
      UNION ALL
      SELECT e.id,e.operation,e.digest,v.*,s.event_key,s.ordinal
      FROM portions s JOIN accounting.entry e ON e.id=s.disposition_entry_id
      CROSS JOIN LATERAL jsonb_populate_record(NULL::accounting.line,jsonb_build_object(
        'entry_id',e.id,'account_code',origin.account_code,'side','credit',
        'quantity',s.quantity,'amount',s.book,'dimensions',s.inventory_dimensions,
        'currency','BYN','category','asset','cash',false)) v
      WHERE s.source_entry_id=output_id AND s.source_line_id=origin.id
    ) SELECT * FROM events ORDER BY movement_id,movement_order
""" + evidence[finish:]
        legacy_key = "'disposed:'||movement.movement_id||':'||movement.id"
        if evidence.count(legacy_key) != 2:
            raise RuntimeError("0145 requires both legacy disposal key anchors")
        evidence = evidence.replace(legacy_key, f"coalesce(movement.allocation_key,{legacy_key})")
        replace_once("    saved := NULL;", """    IF movement.allocation_key IS NULL AND EXISTS (
      SELECT 1 FROM accounting.entry other_entry JOIN accounting.line other_line ON other_line.entry_id=other_entry.id
      WHERE other_entry.organization_id=org AND other_entry.id<>output_id
        AND other_entry.posting_date<=cutoff
        AND (registration_cutoff IS NULL OR other_entry.id<registration_cutoff)
        AND other_line.account_code=origin.account_code AND other_line.side='debit'
        AND other_line.quantity>0 AND other_line.dimensions::jsonb=origin.dimensions::jsonb
    ) THEN RAISE EXCEPTION 'Ambiguous legacy output disposal requires source allocation'; END IF;
    saved := NULL;""")
    return evidence


def upgrade():
    op.execute(DDL)
    op.execute(pool_definition())
    op.execute(evidence_definition())


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_issue_receipt WHERE cost::jsonb ? 'source_allocation_version')
        OR EXISTS (SELECT 1 FROM accounting.inventory_sale_receipt WHERE cost::jsonb ? 'source_allocation_version') THEN
        RAISE EXCEPTION 'Cannot downgrade 0145 with explicit inventory disposal history';
      END IF;
      IF EXISTS (SELECT 1 FROM accounting.production_output_cost_revision r
        CROSS JOIN LATERAL jsonb_array_elements(r.preview::jsonb->'ledger_evidence'->'allocation') a
        WHERE a->>'key' LIKE ('allocation'||chr(58)||'%')) THEN
        RAISE EXCEPTION 'Cannot downgrade 0145 with allocated late-cost history';
      END IF;
    END $$;""")
    previous = runpy.run_path(str(Path(__file__).with_name("0139_production_output_cost_revision.py")))["DDL"]
    start = previous.index("CREATE OR REPLACE FUNCTION accounting.output_pool_revision_rows(")
    end = previous.index("END $$;", start) + len("END $$;")
    op.execute(previous[start:end])
    op.execute(evidence_definition(upgraded=False))
    op.execute("DROP FUNCTION accounting.output_pool_revision_rows(integer,integer,date,integer,integer)")
    op.execute("DROP FUNCTION accounting.inventory_allocation_cost_stream(integer,text,text,text,date,integer)")
