"""Freeze bank source completeness guards after the joint CRM/Accounting head."""
from alembic import op
from sqlalchemy import text

revision = "0134"
down_revision = "0133"
branch_labels = None
depends_on = None

DDL = "-- Additive bank completeness protection; register after the joint migration head.\nCREATE OR REPLACE FUNCTION accounting.guard_bank_period_close() RETURNS trigger\nLANGUAGE plpgsql AS $$\nBEGIN\n  IF NEW.closed THEN\n    PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;\n    IF EXISTS (\n      SELECT 1 FROM accounting.source_binding b\n      JOIN finance.bank_transaction s ON s.id=b.source_id\n      LEFT JOIN accounting.bank_import_receipt r\n        ON r.organization_id=b.organization_id AND r.source_transaction_id=s.id\n      WHERE b.organization_id=NEW.organization_id AND b.source_type='finance_bank_transaction'\n        AND b.ownership='own' AND r.entry_id IS NULL\n        AND (s.occurred_on IS NULL OR to_char(s.occurred_on,'YYYY-MM')<=NEW.month)\n    ) THEN\n      RAISE EXCEPTION 'Unposted imported bank transactions prevent closing';\n    END IF;\n  END IF;\n  RETURN NEW;\nEND $$;\nCREATE TRIGGER bank_period_close_check BEFORE INSERT OR UPDATE ON accounting.period\nFOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_period_close();\n\nCREATE OR REPLACE FUNCTION accounting.guard_bank_source_binding() RETURNS trigger\nLANGUAGE plpgsql AS $$\nDECLARE source_row finance.bank_transaction;\nBEGIN\n  IF NEW.source_type<>'finance_bank_transaction' THEN RETURN NEW; END IF;\n  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;\n  SELECT * INTO source_row FROM finance.bank_transaction WHERE id=NEW.source_id FOR UPDATE;\n  IF NOT FOUND OR NEW.ownership<>'own' THEN\n    RAISE EXCEPTION 'Bank source binding requires an existing own-company source';\n  END IF;\n  IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id AND closed\n      AND (source_row.occurred_on IS NULL OR month>=to_char(source_row.occurred_on,'YYYY-MM'))) THEN\n    RAISE EXCEPTION 'Bank source affects a closed period';\n  END IF;\n  RETURN NEW;\nEND $$;\nCREATE TRIGGER bank_source_binding_check BEFORE INSERT ON accounting.source_binding\nFOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_source_binding();\n\nCREATE OR REPLACE FUNCTION accounting.guard_bound_bank_source_mutation() RETURNS trigger\nLANGUAGE plpgsql AS $$\nBEGIN\n  IF TG_OP='UPDATE' THEN\n    IF ROW(NEW.id,NEW.ext_id,NEW.occurred_on,NEW.amount,NEW.currency,NEW.payer_unp,NEW.payer_name,NEW.purpose,NEW.account_code)\n       IS NOT DISTINCT FROM ROW(OLD.id,OLD.ext_id,OLD.occurred_on,OLD.amount,OLD.currency,OLD.payer_unp,OLD.payer_name,OLD.purpose,OLD.account_code)\n    THEN RETURN NEW; END IF;\n  END IF;\n  IF EXISTS (SELECT 1 FROM accounting.source_binding WHERE source_type='finance_bank_transaction' AND source_id=OLD.id) THEN\n    RAISE EXCEPTION 'Bound bank source financial fields are immutable';\n  END IF;\n  IF TG_OP='DELETE' THEN RETURN OLD; END IF;\n  RETURN NEW;\nEND $$;\nCREATE TRIGGER bound_bank_source_mutation BEFORE UPDATE OR DELETE ON finance.bank_transaction\nFOR EACH ROW EXECUTE FUNCTION accounting.guard_bound_bank_source_mutation();\n\nCREATE OR REPLACE FUNCTION accounting.guard_bound_bank_source_truncate() RETURNS trigger\nLANGUAGE plpgsql AS $$\nBEGIN\n  IF EXISTS (SELECT 1 FROM accounting.source_binding WHERE source_type='finance_bank_transaction') THEN\n    RAISE EXCEPTION 'Bound bank sources cannot be truncated';\n  END IF;\n  RETURN NULL;\nEND $$;\nCREATE TRIGGER bound_bank_source_truncate BEFORE TRUNCATE ON finance.bank_transaction\nFOR EACH STATEMENT EXECUTE FUNCTION accounting.guard_bound_bank_source_truncate();\n"

PREFLIGHT = "-- Read-only diagnostics before bank_period_guards installation.\n-- An empty result means these structural checks found no conflicting rows;\n-- it does not certify the books or infer ownership of unbound bank rows.\nSELECT 'invalid_bank_binding' AS issue, b.organization_id, NULL::text AS month,\n       b.id AS binding_id, b.source_id AS source_transaction_id\nFROM accounting.source_binding b\nLEFT JOIN finance.bank_transaction s ON s.id=b.source_id\nWHERE b.source_type='finance_bank_transaction'\n  AND (s.id IS NULL OR b.ownership<>'own')\nUNION ALL\nSELECT 'closed_period_unposted_bank' AS issue, b.organization_id, p.month,\n       b.id AS binding_id, b.source_id AS source_transaction_id\nFROM accounting.source_binding b\nJOIN finance.bank_transaction s ON s.id=b.source_id\nJOIN accounting.period p ON p.organization_id=b.organization_id AND p.closed\nLEFT JOIN accounting.bank_import_receipt r\n  ON r.organization_id=b.organization_id AND r.source_transaction_id=s.id\nWHERE b.source_type='finance_bank_transaction' AND b.ownership='own'\n  AND r.entry_id IS NULL\n  AND (s.occurred_on IS NULL OR to_char(s.occurred_on,'YYYY-MM')<=p.month)\nORDER BY organization_id, month, binding_id;\n"

def upgrade():
    connection = op.get_bind()
    # Keep diagnostics and installation atomic with respect to source changes.
    connection.execute(text(
        "LOCK TABLE accounting.period, accounting.source_binding, "
        "accounting.bank_import_receipt, finance.bank_transaction "
        "IN ACCESS EXCLUSIVE MODE"
    ))
    if connection.execute(text(PREFLIGHT)).first() is not None:
        raise RuntimeError(
            "Bank period guard preflight failed; review existing source bindings "
            "and closed periods before retrying migration 0134"
        )
    op.execute(DDL)


def downgrade():
    raise RuntimeError("Bank completeness guards require a reviewed forward fix")
