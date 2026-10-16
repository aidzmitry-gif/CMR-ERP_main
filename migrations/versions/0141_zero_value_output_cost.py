"""Admit authenticated entryless specific-cost output disposals in revisions."""
import runpy
from pathlib import Path

from alembic import op

revision = "0141"
down_revision = "0140"
branch_labels = None
depends_on = None


def _function(ddl, name):
    start = ddl.index(f"CREATE OR REPLACE FUNCTION accounting.{name}")
    end = ddl.index("END $$;", start) + len("END $$;")
    return ddl[start:end]


def _definitions():
    previous = runpy.run_path(str(Path(__file__).with_name("0139_production_output_cost_revision.py")))["DDL"]
    evidence = _function(previous, "output_cost_revision_evidence")
    def replace_once(value, old, new):
        if value.count(old) != 1:
            raise RuntimeError(f"0141 anchor must occur once: {old[:60]}")
        return value.replace(old, new)

    evidence = replace_once(evidence,
        "org integer, output_id integer, cutoff date, excluded_entry integer\n) RETURNS jsonb",
        "org integer, output_id integer, cutoff date, excluded_entry integer, registration_cutoff integer\n) RETURNS jsonb",
    )
    evidence = replace_once(evidence,
        "  allocation_amount numeric;\nBEGIN",
        "  allocation_amount numeric;\n  zero_receipt record;\n  zero_layer jsonb;\n  zero_quantity numeric;\nBEGIN",
    )
    evidence = replace_once(evidence,
        "  IF remainder_qty<0 OR remainder_cost<0 OR (remainder_qty=0 AND remainder_cost<>0) THEN",
        """  -- Entryless receipts have no ledger movement. Re-authenticate their
  -- immutable command at their own registration boundary before allocation.
  FOR zero_receipt IN SELECT z.* FROM accounting.inventory_zero_value_disposal_receipt z
    WHERE z.organization_id=org AND z.operation='inventory_issue' AND z.entry_id IS NULL
      AND (registration_cutoff IS NULL OR z.registration_token<registration_cutoff)
      AND EXISTS (SELECT 1 FROM jsonb_array_elements(z.command::jsonb->'inventory_layers') layer
        WHERE (layer->>'source_entry_id')::integer=output_id AND (layer->>'source_line_id')::integer=origin.id)
    ORDER BY z.posting_date,z.registration_token,z.id
  LOOP
    IF zero_receipt.posting_date>cutoff THEN
      RAISE EXCEPTION 'Output revision cannot ignore a future-dated zero-value receipt';
    END IF;
    IF zero_receipt.digest IS DISTINCT FROM accounting.financial_sha(jsonb_build_object(
      'organization_id',org,'actor',zero_receipt.actor,'command',zero_receipt.command::jsonb))
      OR zero_receipt.basis_digest IS DISTINCT FROM accounting.zero_value_disposal_basis(
        org,zero_receipt.command::jsonb,zero_receipt.registration_token) THEN
      RAISE EXCEPTION 'Output revision zero-value receipt is not historically authenticated';
    END IF;
    FOR zero_layer IN SELECT item.value FROM jsonb_array_elements(zero_receipt.command::jsonb->'inventory_layers') item LOOP
      IF (zero_layer->>'source_entry_id')::integer=output_id
        AND (zero_layer->>'source_line_id')::integer=origin.id THEN
        zero_quantity := (zero_layer->>'quantity')::numeric;
        IF zero_quantity<=0 OR remainder_qty<zero_quantity THEN
          RAISE EXCEPTION 'Output revision zero-value receipt exceeds remaining output quantity';
        END IF;
        remainder_qty := remainder_qty-zero_quantity;
        rows := rows || jsonb_build_array(jsonb_build_object(
          'key','zero:'||zero_receipt.id||':'||zero_receipt.registration_token,
          'account',zero_receipt.command::jsonb->>'destination_account',
          'dimensions',coalesce(zero_receipt.command::jsonb->'destination_dimensions','{}'::jsonb),
          'quantity',zero_quantity,'book',coalesce((SELECT sum((a->>'delta')::numeric)
            FROM jsonb_array_elements(prior_allocation) a
            WHERE a->>'key'='zero:'||zero_receipt.id||':'||zero_receipt.registration_token),0)));
      END IF;
    END LOOP;
  END LOOP;
  IF remainder_qty<0 OR remainder_cost<0 OR (remainder_qty=0 AND remainder_cost<>0) THEN""",
    )
    evidence = replace_once(evidence,
        "AND (r.command->>'posting_date')::date>cutoff)",
        "AND (r.command->>'posting_date')::date>cutoff\n"
        "               AND (registration_cutoff IS NULL OR r.registration_token<registration_cutoff))",
    )
    evidence = replace_once(evidence,
        "ORDER BY r.sequence DESC LIMIT 1;",
        "AND (registration_cutoff IS NULL OR r.registration_token<registration_cutoff)\n"
        "    ORDER BY r.sequence DESC LIMIT 1;",
    )
    evidence = replace_once(evidence,
        "WHERE r.original_entry_id=output_id AND r.organization_id=org;",
        "WHERE r.original_entry_id=output_id AND r.organization_id=org\n"
        "      AND (registration_cutoff IS NULL OR r.registration_token<registration_cutoff);",
    )
    if evidence.count("AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)") != 3:
        raise RuntimeError("0141 requires three monetary history boundaries")
    evidence = evidence.replace(
        "AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)",
        "AND e.id<>output_id AND e.id<>coalesce(excluded_entry,-1)\n"
        "      AND (registration_cutoff IS NULL OR e.id<registration_cutoff)",
    )
    compatibility = """CREATE OR REPLACE FUNCTION accounting.output_cost_revision_evidence(
      org integer, output_id integer, cutoff date, excluded_entry integer
    ) RETURNS jsonb LANGUAGE sql AS $$
      SELECT accounting.output_cost_revision_evidence(org,output_id,cutoff,excluded_entry,NULL)
    $$;"""
    guard = _function(previous, "guard_output_cost_revision")
    guard = replace_once(guard,
        "accounting.output_cost_revision_evidence(NEW.organization_id, NEW.original_entry_id, command_date, NEW.entry_id)",
        "accounting.output_cost_revision_evidence(NEW.organization_id, NEW.original_entry_id, command_date, NEW.entry_id, NEW.registration_token)",
    )
    return evidence + "\n" + compatibility + "\n" + guard


def upgrade():
    op.execute(_definitions())


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt) THEN
        RAISE EXCEPTION 'Cannot downgrade 0141 while zero-value disposal history exists';
      END IF;
    END $$;""")
    previous = runpy.run_path(str(Path(__file__).with_name("0139_production_output_cost_revision.py")))["DDL"]
    op.execute(_function(previous, "output_cost_revision_evidence") + "\n" + _function(previous, "guard_output_cost_revision"))
    op.execute("DROP FUNCTION accounting.output_cost_revision_evidence(integer,integer,date,integer,integer);")
