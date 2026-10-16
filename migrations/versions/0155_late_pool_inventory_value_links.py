"""Bind signed V3 inventory values to immutable acquisition layers."""

import re
from pathlib import Path

from alembic import op

revision = "0155"
down_revision = "0154"
branch_labels = None
depends_on = None


_OLD_FUNCTION = "accounting.verify_late_pool_package(target integer)"
_OLD_CREATE = "CREATE FUNCTION " + _OLD_FUNCTION + " RETURNS void"
_NEW_CREATE = "CREATE OR REPLACE FUNCTION " + _OLD_FUNCTION + " RETURNS void"
_OLD_EVIDENCE_CHECK = """OR link.evidence IS DISTINCT FROM (SELECT item->'prospective_evidence'
              FROM jsonb_array_elements(p.preview->'outputs') item
              WHERE (item->>'output_entry_id')::integer=link.output_entry_id)
          OR link.evidence IS DISTINCT FROM revision.preview::jsonb->'ledger_evidence'"""
_NEW_EVIDENCE_CHECK = """OR accounting.pool_output_evidence_projection(link.evidence) IS DISTINCT FROM
            accounting.pool_output_evidence_projection((SELECT item->'prospective_evidence'
              FROM jsonb_array_elements(p.preview->'outputs') item
              WHERE (item->>'output_entry_id')::integer=link.output_entry_id))
          OR link.evidence IS DISTINCT FROM revision.preview::jsonb->'ledger_evidence'"""
_OLD_DECLARE = """      revision accounting.production_output_cost_revision%ROWTYPE; output_item jsonb;"""
_NEW_DECLARE = _OLD_DECLARE + """
      value_link accounting.late_pool_inventory_value_link%ROWTYPE; value_expected integer;"""
_VERIFY_ANCHOR = """      IF p.preview->'command' IS DISTINCT FROM p.command"""

_INVENTORY_LINK_VERIFIER = """
      IF jsonb_typeof(p.calculation->'destinations') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V3 pool package inventory destinations are invalid';
      END IF;
      SELECT count(*) INTO expected
      FROM jsonb_array_elements(p.calculation->'destinations') destination
      WHERE destination->>'kind'='inventory'
        AND CASE WHEN coalesce(destination->>'delta_byn','') ~ '^-?[0-9]{1,16}[.][0-9]{2}$'
                 THEN (destination->>'delta_byn')::numeric END <> 0;
      SELECT count(*) INTO actual FROM accounting.late_pool_inventory_value_link
        WHERE package_id=p.id;
      IF actual <> expected THEN
        RAISE EXCEPTION 'V3 pool package inventory value links are incomplete';
      END IF;
      FOR value_link IN SELECT * FROM accounting.late_pool_inventory_value_link
          WHERE package_id=p.id LOOP
        IF value_link.value_entry_id IS DISTINCT FROM p.late_entry_id
          OR NOT EXISTS (SELECT 1
              FROM accounting.line value_line
              WHERE value_line.id=value_link.value_line_id
                AND value_line.entry_id=value_link.value_entry_id
                AND value_line.account_code ~ '^(10|41)([.]|$)'
                AND value_line.category='asset' AND value_line.cash=false
                AND value_line.currency='BYN' AND value_line.quantity IS NULL
                AND value_line.side IN ('debit','credit') AND value_line.amount > 0)
          OR NOT EXISTS (SELECT 1
              FROM accounting.line acquisition_line
              JOIN accounting.entry acquisition_entry ON acquisition_entry.id=acquisition_line.entry_id
              JOIN accounting.line value_line ON value_line.id=value_link.value_line_id
              WHERE acquisition_line.id=value_link.acquisition_line_id
                AND acquisition_line.entry_id=value_link.acquisition_entry_id
                AND acquisition_entry.organization_id=p.organization_id
                AND acquisition_entry.id < p.late_entry_id
                AND acquisition_line.side='debit' AND acquisition_line.category='asset'
                AND acquisition_line.cash=false AND acquisition_line.currency='BYN'
                AND acquisition_line.quantity IS NOT NULL AND acquisition_line.quantity > 0
                AND acquisition_line.account_code=value_line.account_code
                AND acquisition_line.dimensions::jsonb IS NOT DISTINCT FROM value_line.dimensions::jsonb)
        THEN
          RAISE EXCEPTION 'V3 pool inventory value link has an invalid acquisition origin';
        END IF;
        SELECT count(*) INTO value_expected
        FROM jsonb_array_elements(p.calculation->'destinations') destination
        JOIN accounting.line value_line ON value_line.id=value_link.value_line_id
        WHERE destination->>'kind'='inventory'
          AND coalesce(destination->>'source_entry_id','')=value_link.acquisition_entry_id::text
          AND coalesce(destination->>'source_line_id','')=value_link.acquisition_line_id::text
          AND destination->>'account'=value_line.account_code
          AND destination->'dimensions' IS NOT DISTINCT FROM value_line.dimensions::jsonb
          AND CASE WHEN coalesce(destination->>'delta_byn','') ~ '^-?[0-9]{1,16}[.][0-9]{2}$'
                   THEN (destination->>'delta_byn')::numeric END =
              CASE value_line.side WHEN 'debit' THEN value_line.amount ELSE -value_line.amount END;
        IF value_expected <> 1 THEN
          RAISE EXCEPTION 'V3 pool inventory value link differs from reviewed destination';
        END IF;
      END LOOP;
"""


def _verify_function(*, inventory_links: bool) -> str:
    """Keep the exact 0154 verifier and add only the new immutable link check."""
    source = Path(__file__).with_name("0153_late_pool_atomic_package.py").read_text(encoding="utf-8")
    match = re.search(r"CREATE FUNCTION accounting\.verify_late_pool_package\(target integer\) "
                      r"RETURNS void.*?END \$\$;", source, re.DOTALL)
    if match is None:
        raise RuntimeError("0155 frozen V3 package verification function is unavailable")
    sql = match.group(0)
    if sql.count(_OLD_EVIDENCE_CHECK) != 1 or sql.count(_OLD_DECLARE) != 1:
        raise RuntimeError("0155 frozen V3 package verification anchors changed")
    sql = sql.replace(_OLD_EVIDENCE_CHECK, _NEW_EVIDENCE_CHECK)
    sql = sql.replace(_OLD_CREATE, _NEW_CREATE, 1)
    if not inventory_links:
        return sql
    if sql.count(_VERIFY_ANCHOR) != 1:
        raise RuntimeError("0155 V3 inventory verification anchor changed")
    sql = sql.replace(_OLD_DECLARE, _NEW_DECLARE, 1)
    return sql.replace(_VERIFY_ANCHOR, _INVENTORY_LINK_VERIFIER + "\n" + _VERIFY_ANCHOR, 1)


def upgrade():
    op.execute("""
    CREATE TABLE accounting.late_pool_inventory_value_link (
      package_id integer NOT NULL REFERENCES accounting.late_pool_package(id),
      value_entry_id integer NOT NULL REFERENCES accounting.entry(id),
      value_line_id integer NOT NULL UNIQUE REFERENCES accounting.line(id),
      acquisition_entry_id integer NOT NULL REFERENCES accounting.entry(id),
      acquisition_line_id integer NOT NULL REFERENCES accounting.line(id),
      PRIMARY KEY (package_id, value_line_id),
      UNIQUE (package_id, acquisition_entry_id, acquisition_line_id)
    );
    CREATE CONSTRAINT TRIGGER complete_late_pool_inventory_value_link
      AFTER INSERT ON accounting.late_pool_inventory_value_link DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_pool_package();
    CREATE TRIGGER immutable_late_pool_inventory_value_link BEFORE UPDATE OR DELETE OR TRUNCATE
      ON accounting.late_pool_inventory_value_link FOR EACH STATEMENT
      EXECUTE FUNCTION accounting.reject_late_pool_mutation();
    """)
    op.execute(_verify_function(inventory_links=True))


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.late_pool_package) THEN
        RAISE EXCEPTION 'Cannot downgrade V3 pool history with immutable inventory value links';
      END IF;
    END $$;
    """)
    op.execute(_verify_function(inventory_links=False))
    op.execute("DROP TABLE accounting.late_pool_inventory_value_link")
