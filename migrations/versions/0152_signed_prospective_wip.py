"""Project signed WIP cost changes without changing any posted history."""
import runpy
from pathlib import Path

from alembic import op

revision = "0152"
down_revision = "0151"
branch_labels = None
depends_on = None


def signed_definition():
    previous = runpy.run_path(str(Path(__file__).with_name("0151_late_material_output_cost.py")))
    sql = previous["prospective_evidence_definition"]()
    replacements = [
        ("accounting.preview_output_cost_with_wip(", "accounting.preview_output_cost_with_signed_wip("),
        ("^[0-9]{1,16}\\.[0-9]{2}$", "^-?[0-9]{1,16}\\.[0-9]{2}$"),
        ("(p->>'amount_byn')::numeric<=0", "(p->>'amount_byn')::numeric=0"),
        ("'account',wip,'side','debit',\n    'amount',(p->>'amount_byn')::numeric",
         "'account',wip,'side',CASE WHEN (p->>'amount_byn')::numeric>0 THEN 'debit' ELSE 'credit' END,\n"
         "    'amount',abs((p->>'amount_byn')::numeric)"),
        ("FROM jsonb_array_elements(prospective) p);",
         "FROM jsonb_array_elements(prospective) p);\n"
         "  IF source_cost<0 THEN RAISE EXCEPTION 'Prospective WIP cost cannot be negative'; END IF;"),
    ]
    for old, new in replacements:
        if sql.count(old) != 1:
            raise RuntimeError("0152 frozen prospective SQL anchor changed")
        sql = sql.replace(old, new, 1)
    return sql


def upgrade():
    op.execute(signed_definition())


def downgrade():
    op.execute("DROP FUNCTION accounting.preview_output_cost_with_signed_wip(integer,integer,date,integer,jsonb,integer)")
