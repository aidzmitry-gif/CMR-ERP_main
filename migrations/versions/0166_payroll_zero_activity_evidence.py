"""Allow a chief-reviewed monthly zero-payroll source file."""
from alembic import op

revision = "0166"
down_revision = "0165"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind = 'payroll_zero_activity' AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    CREATE OR REPLACE FUNCTION accounting.guard_payroll_zero_activity_closed_month()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind = 'payroll_zero_activity' AND EXISTS (
        SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
          AND month = NEW.month AND closed IS TRUE
      ) THEN
        RAISE EXCEPTION 'Closed month rejects new zero-activity payroll evidence';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zz_guard_payroll_zero_activity_closed_month
      BEFORE INSERT ON accounting.payroll_evidence_file FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_zero_activity_closed_month();
    CREATE OR REPLACE FUNCTION accounting.guard_known_payroll_period_close()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE has_active_binding boolean;
    BEGIN
      IF NOT NEW.closed OR (TG_OP = 'UPDATE' AND OLD.closed) THEN
        RETURN NEW;
      END IF;
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      WITH latest_on_date AS (
        SELECT DISTINCT ON (employee_id, contract_ref, effective_from)
          employee_id, contract_ref, effective_from, state
        FROM accounting.payroll_employment_binding
        WHERE organization_id = NEW.organization_id
          AND effective_from < (NEW.month || '-01')::date + INTERVAL '1 month'
        ORDER BY employee_id, contract_ref, effective_from, revision DESC, id DESC
      ), intervals AS (
        SELECT effective_from, state,
          lead(effective_from) OVER (
            PARTITION BY employee_id, contract_ref ORDER BY effective_from
          ) AS next_from
        FROM latest_on_date
      )
      SELECT EXISTS (
        SELECT 1 FROM intervals WHERE state = 'active'
          AND effective_from < (NEW.month || '-01')::date + INTERVAL '1 month'
          AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date)
      ) INTO has_active_binding;
      IF (has_active_binding OR EXISTS (
            SELECT 1 FROM accounting.entry e
            WHERE e.organization_id = NEW.organization_id
              AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
              AND e.operation = 'payroll_statutory_import'
          ))
         AND NOT EXISTS (
           SELECT 1 FROM accounting.payroll_accrual_receipt r
           JOIN accounting.entry e ON e.id = r.entry_id
           WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
             AND e.organization_id = NEW.organization_id
             AND e.operation = 'payroll_accrual_import'
             AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
         )
         AND NOT EXISTS (
           SELECT 1 FROM accounting.payroll_evidence_file f
           WHERE f.organization_id = NEW.organization_id
             AND f.month = NEW.month AND f.kind = 'payroll_zero_activity'
             AND NOT EXISTS (
               SELECT 1 FROM accounting.entry e
               WHERE e.organization_id = NEW.organization_id
                 AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
                 AND e.operation IN ('payroll_accrual_import', 'payroll_statutory_import')
             )
         ) THEN
        RAISE EXCEPTION 'Known employment requires a monthly payroll source before closing';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zz_guard_known_payroll_period_close
      BEFORE INSERT OR UPDATE ON accounting.period FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_known_payroll_period_close();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                 WHERE kind = 'payroll_zero_activity') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable zero-activity payroll evidence';
      END IF;
    END $$;
    DROP TRIGGER zz_guard_payroll_zero_activity_closed_month
      ON accounting.payroll_evidence_file;
    DROP FUNCTION accounting.guard_payroll_zero_activity_closed_month();
    DROP TRIGGER zz_guard_known_payroll_period_close ON accounting.period;
    DROP FUNCTION accounting.guard_known_payroll_period_close();
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy', 'base_adjustment'));
    """)
