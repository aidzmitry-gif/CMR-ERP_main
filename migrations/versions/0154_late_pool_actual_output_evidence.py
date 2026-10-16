"""Keep reviewed V3 output matrices separate from their posted source identities."""

import re
from pathlib import Path

from alembic import op

revision = "0154"
down_revision = "0153"
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

_EVIDENCE_PROJECTION = """
CREATE FUNCTION accounting.pool_output_evidence_projection(evidence jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE matrix jsonb; allocation jsonb;
BEGIN
  IF jsonb_typeof(evidence) IS DISTINCT FROM 'object'
     OR jsonb_typeof(evidence->'matrix') IS DISTINCT FROM 'array'
     OR jsonb_typeof(evidence->'allocation') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'V3 pool output evidence is malformed';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'account',item->>'account','side',item->>'side','dimensions',item->'dimensions',
      'amount',(item->>'amount')::numeric) ORDER BY item->>'account',item->>'side',
      (item->'dimensions')::text,(item->>'amount')::numeric),'[]'::jsonb) INTO matrix
  FROM jsonb_array_elements(evidence->'matrix') item;
  SELECT coalesce(jsonb_agg(jsonb_build_object(
      'key',item->>'key','account',item->>'account','dimensions',item->'dimensions',
      'quantity',(item->>'quantity')::numeric,'book',(item->>'book')::numeric,
      'desired',(item->>'desired')::numeric,'delta',(item->>'delta')::numeric)
      ORDER BY item->>'key',item->>'account',(item->'dimensions')::text),'[]'::jsonb) INTO allocation
  FROM jsonb_array_elements(evidence->'allocation') item;
  RETURN jsonb_build_object('matrix',matrix,'allocation',allocation);
END $$;
"""

_CHECK_ADDITIONAL_EXPENSE = """
CREATE OR REPLACE FUNCTION procurement.check_additional_expense(expense integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE h procurement.additional_expense_document%ROWTYPE;
        r procurement.additional_expense_revision%ROWTYPE;
        c accounting.source_control%ROWTYPE;
        n integer; latest integer;
BEGIN
  SELECT * INTO h FROM procurement.additional_expense_document WHERE id = expense;
  IF NOT FOUND THEN RAISE EXCEPTION 'Additional expense header is missing'; END IF;
  SELECT count(*), max(version) INTO n, latest FROM procurement.additional_expense_revision WHERE expense_id = expense;
  IF n = 0 OR latest <> n OR EXISTS (SELECT 1 FROM procurement.additional_expense_revision
      WHERE expense_id = expense AND version < 1) THEN
    RAISE EXCEPTION 'Additional expense revision chain is incomplete';
  END IF;
  SELECT * INTO r FROM procurement.additional_expense_revision WHERE expense_id = expense AND version = latest;
  SELECT * INTO c FROM accounting.source_control WHERE organization_id = h.organization_id
    AND source = 'procurement:additional-expense:' || expense;
  IF NOT FOUND OR c.version IS DISTINCT FROM latest OR c.month IS DISTINCT FROM left(r.document->>'operation_date', 7)
     OR (c.entry_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM accounting.late_cost_receipt l
       WHERE l.entry_id=c.entry_id AND l.organization_id=h.organization_id AND l.expense_id=expense
         AND l.source_version=latest)
       AND NOT EXISTS (SELECT 1 FROM accounting.late_pool_package p
         JOIN accounting.entry e ON e.id=p.late_entry_id
         WHERE p.late_entry_id=c.entry_id AND p.organization_id=h.organization_id
           AND e.source=c.source AND e.source_version=latest
           AND p.preview->>'expense_id'=expense::text
           AND p.command->'allocation'->>'expected_version'=latest::text)) THEN
    RAISE EXCEPTION 'Additional expense completeness registration is missing or inconsistent';
  END IF;
END $$;
"""

_LEGACY_CHECK_ADDITIONAL_EXPENSE = """
CREATE OR REPLACE FUNCTION procurement.check_additional_expense(expense integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE h procurement.additional_expense_document%ROWTYPE;
        r procurement.additional_expense_revision%ROWTYPE;
        c accounting.source_control%ROWTYPE;
        n integer; latest integer;
BEGIN
  SELECT * INTO h FROM procurement.additional_expense_document WHERE id = expense;
  IF NOT FOUND THEN RAISE EXCEPTION 'Additional expense header is missing'; END IF;
  SELECT count(*), max(version) INTO n, latest FROM procurement.additional_expense_revision WHERE expense_id = expense;
  IF n = 0 OR latest <> n OR EXISTS (SELECT 1 FROM procurement.additional_expense_revision
      WHERE expense_id = expense AND version < 1) THEN
    RAISE EXCEPTION 'Additional expense revision chain is incomplete';
  END IF;
  SELECT * INTO r FROM procurement.additional_expense_revision WHERE expense_id = expense AND version = latest;
  SELECT * INTO c FROM accounting.source_control WHERE organization_id = h.organization_id
    AND source = 'procurement:additional-expense:' || expense;
  IF NOT FOUND OR c.version IS DISTINCT FROM latest OR c.month IS DISTINCT FROM left(r.document->>'operation_date', 7)
     OR (c.entry_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM accounting.late_cost_receipt l
       WHERE l.entry_id=c.entry_id AND l.organization_id=h.organization_id AND l.expense_id=expense
         AND l.source_version=latest)) THEN
    RAISE EXCEPTION 'Additional expense completeness registration is missing or inconsistent';
  END IF;
END $$;
"""


def _verify_function(*, actual_output_evidence: bool) -> str:
    """Derive the exact prior function and fail if its reviewed anchor drifted."""
    source = Path(__file__).with_name("0153_late_pool_atomic_package.py").read_text(encoding="utf-8")
    match = re.search(r"CREATE FUNCTION accounting\.verify_late_pool_package\(target integer\) "
                      r"RETURNS void.*?END \$\$;", source, re.DOTALL)
    if match is None:
        raise RuntimeError("0154 frozen V3 package verification function is unavailable")
    sql = match.group(0)
    if actual_output_evidence:
        if sql.count(_OLD_EVIDENCE_CHECK) != 1:
            raise RuntimeError("0154 V3 output evidence anchor changed")
        sql = sql.replace(_OLD_EVIDENCE_CHECK, _NEW_EVIDENCE_CHECK)
        sql = sql.replace(_OLD_CREATE, _NEW_CREATE, 1)
    return sql


def upgrade():
    op.execute(_EVIDENCE_PROJECTION)
    op.execute(_CHECK_ADDITIONAL_EXPENSE)
    op.execute(_verify_function(actual_output_evidence=True))


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.late_pool_package) THEN
        RAISE EXCEPTION 'Cannot downgrade V3 pool history with source control';
      END IF;
      IF EXISTS (
        SELECT 1
        FROM accounting.late_pool_package p
        JOIN accounting.late_pool_output_cost_link link ON link.package_id=p.id
        WHERE link.evidence IS DISTINCT FROM (
          SELECT item->'prospective_evidence'
          FROM jsonb_array_elements(p.preview->'outputs') item
          WHERE (item->>'output_entry_id')::integer=link.output_entry_id
        )
      ) THEN
        RAISE EXCEPTION 'Cannot downgrade V3 pool history with posted output evidence';
      END IF;
    END $$;
    """)
    op.execute(_verify_function(actual_output_evidence=False))
    op.execute(_LEGACY_CHECK_ADDITIONAL_EXPENSE)
    op.execute("DROP FUNCTION accounting.pool_output_evidence_projection(jsonb)")
