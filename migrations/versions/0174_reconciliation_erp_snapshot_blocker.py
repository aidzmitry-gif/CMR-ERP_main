"""Keep immutable OSV mismatch queues valid under the live-ledger source guard."""

from alembic import op

revision = "0174"
down_revision = "0173"
branch_labels = None
depends_on = None

_BASE = "'numeric_differences', 'reports_not_closed', 'pending_documents'"
_FUNCTION = r"""
CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_issue_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Reconciliation issue organization is unavailable';
  END IF;
  IF NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.period_from > NEW.period_to
     OR NEW.left_digest !~ '^[a-f0-9]{64}$'
     OR NEW.right_digest !~ '^[a-f0-9]{64}$'
     OR NEW.command_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR NEW.left_status NOT IN ('preliminary', 'closed_periods')
     OR NEW.right_status NOT IN ('preliminary', 'closed_periods')
     OR NEW.left_pending_documents < 0
     OR NEW.right_pending_documents < 0
     OR NEW.left_rows < 0
     OR NEW.right_rows < 0
     OR NEW.difference_count < 0
     OR jsonb_typeof(NEW.eligibility_blockers) <> 'array'
     OR jsonb_array_length(NEW.eligibility_blockers) = 0
     OR jsonb_typeof(NEW.snapshot) <> 'object'
     OR length(btrim(NEW.responsible)) = 0
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) = 0 THEN
    RAISE EXCEPTION 'Reconciliation issue has incomplete immutable evidence';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(NEW.eligibility_blockers) AS blocker(value)
    WHERE blocker.value NOT IN (__ALLOWED__)
  ) THEN
    RAISE EXCEPTION 'Reconciliation issue has an unknown eligibility blocker';
  END IF;
  IF (NEW.difference_count > 0) <> (NEW.eligibility_blockers ? 'numeric_differences') THEN
    RAISE EXCEPTION 'Reconciliation issue difference count and blockers disagree';
  END IF;
  RETURN NEW;
END;
$$;
"""


def upgrade():
    op.execute(_FUNCTION.replace("__ALLOWED__", _BASE + ", 'erp_snapshot_mismatch'"))


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.reconciliation_issue
                 WHERE eligibility_blockers ? 'erp_snapshot_mismatch') THEN
        RAISE EXCEPTION 'Cannot downgrade 0174 with immutable ERP snapshot mismatch issues';
      END IF;
    END $$;
    """)
    op.execute(_FUNCTION.replace("__ALLOWED__", _BASE))
