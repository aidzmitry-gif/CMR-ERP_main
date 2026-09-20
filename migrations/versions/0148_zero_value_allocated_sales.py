"""Extend full zero allocations to linked commercial sales."""
import runpy
from pathlib import Path

from alembic import op

revision = "0148"
down_revision = "0147"
branch_labels = None
depends_on = None


def definitions():
    prior = runpy.run_path(str(Path(__file__).with_name("0147_zero_value_allocation_runtime.py")))
    sale = runpy.run_path(str(Path(__file__).with_name("0143_zero_value_sales.py")))
    replace = prior["replace_once"]
    guard = prior["guard_definition"]()
    guard = replace(guard, "AND source=NEW.source AND source_version=NEW.source_version AND operation='inventory_issue')",
                    "AND source=NEW.source AND source_version=NEW.source_version AND operation=NEW.operation "
                    "AND id IS DISTINCT FROM NEW.entry_id)")
    guard = replace(guard, "NEW.operation IS DISTINCT FROM 'inventory_issue' OR NEW.entry_id IS NOT NULL",
                    "NEW.operation NOT IN ('inventory_issue','inventory_sale') "
                    "OR (NEW.operation='inventory_issue' AND NEW.entry_id IS NOT NULL) "
                    "OR (NEW.operation='inventory_sale' AND (NEW.entry_id IS NULL OR NEW.entry_id<>NEW.registration_token))")
    validator = replace(prior["validator_definition"](), "c->>'operation' IS DISTINCT FROM 'inventory_issue'",
                        "coalesce(c->>'operation','') NOT IN ('inventory_issue','inventory_sale')")
    link = prior["_function"](sale["LINK_DDL"], "validate_zero_sale_link")
    link = replace(link, "d:=c->'sale_document';", "d:=CASE WHEN c->>'command_version'='4' THEN c->'document' ELSE c->'sale_document' END;")
    link = replace(link, "c->'command_version' IS DISTINCT FROM '3'::jsonb",
                   "c->'command_version' NOT IN ('3'::jsonb,'4'::jsonb)")
    start = link.index("   OR layer->>'inventory_account'")
    end = link.index("   OR EXISTS (SELECT 1 FROM accounting.line", start)
    legacy = link[start + len("   OR "):end].rstrip()
    link = link[:start] + "   OR (c->>'command_version'='3' AND (" + legacy + "))\n" + link[end:]
    link = replace(link, " FOREACH field IN ARRAY ARRAY['source','source_version','document_date','operation_date','posting_date','policy_id','explanation'] LOOP", """ IF c->>'command_version'='4' THEN
   IF r.cost::jsonb ? 'source_allocation_version' THEN
     RAISE EXCEPTION 'Zero allocation sale must have one quantity representation';
   END IF;
   IF z.basis_digest IS DISTINCT FROM accounting.zero_value_allocation_basis(e.organization_id,c,e.id) THEN
     RAISE EXCEPTION 'Allocated zero sale historical basis changed';
   END IF;
 END IF;
 FOREACH field IN ARRAY ARRAY['source','source_version','document_date','operation_date','posting_date','policy_id','explanation'] LOOP""")
    stream = prior["STREAM"].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    stream = replace(stream, "z.operation IS DISTINCT FROM 'inventory_issue' OR z.entry_id IS NOT NULL",
                     "z.operation NOT IN ('inventory_issue','inventory_sale') "
                     "OR (z.operation='inventory_issue' AND z.entry_id IS NOT NULL) "
                     "OR (z.operation='inventory_sale' AND (z.entry_id IS NULL OR z.entry_id<>z.registration_token))")
    stream = replace(stream, "   IF z.posting_date>cutoff THEN", """   IF z.operation='inventory_sale' THEN
     PERFORM accounting.validate_zero_sale_link(z.entry_id);
   END IF;
   IF z.posting_date>cutoff THEN""")
    return guard, validator, link, stream


def upgrade():
    for ddl in definitions():
        op.execute(ddl)
    op.execute("CREATE FUNCTION accounting.zero_value_allocated_sale_version() RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 4'")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt
        WHERE operation='inventory_sale' AND command::jsonb->>'command_version'='4') THEN
        RAISE EXCEPTION 'Cannot downgrade allocated sale history';
      END IF;
    END $$;""")
    prior = runpy.run_path(str(Path(__file__).with_name("0147_zero_value_allocation_runtime.py")))
    sale = runpy.run_path(str(Path(__file__).with_name("0143_zero_value_sales.py")))
    op.execute(prior["guard_definition"]())
    op.execute(prior["validator_definition"]())
    op.execute(prior["_function"](sale["LINK_DDL"], "validate_zero_sale_link"))
    op.execute(prior["STREAM"].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute("DROP FUNCTION accounting.zero_value_allocated_sale_version()")
