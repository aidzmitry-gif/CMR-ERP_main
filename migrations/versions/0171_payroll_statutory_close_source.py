"""Require a reviewed deductions/contributions source for gross payroll close."""

from alembic import op

revision = "0171"
down_revision = "0170"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population',
                     'payroll_zero_individual', 'payroll_statutory_zero'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment', 'payroll_zero_individual')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_statutory_zero')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    CREATE OR REPLACE FUNCTION accounting.guard_payroll_zero_activity_closed_month()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind IN ('payroll_zero_activity', 'payroll_population',
                      'payroll_zero_individual', 'payroll_statutory_zero')
         AND EXISTS (
           SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
             AND month >= NEW.month AND closed IS TRUE
         ) THEN
        RAISE EXCEPTION 'Closed period rejects a new monthly payroll source';
      END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION accounting.guard_payroll_statutory_source_close()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE has_accrual boolean;
    DECLARE has_statutory boolean;
    DECLARE has_statutory_entry boolean;
    DECLARE has_zero boolean;
    BEGIN
      IF NOT NEW.closed OR (TG_OP = 'UPDATE' AND OLD.closed) THEN
        RETURN NEW;
      END IF;
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      SELECT EXISTS (
        SELECT 1 FROM accounting.entry e
        WHERE e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_statutory_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ) INTO has_statutory_entry;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_evidence_file f
        WHERE f.organization_id = NEW.organization_id AND f.month = NEW.month
          AND f.kind = 'payroll_statutory_zero'
      ) INTO has_zero;
      IF has_zero AND has_statutory_entry THEN
        RAISE EXCEPTION 'Payroll statutory zero statement conflicts with imported amounts';
      END IF;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_accrual_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_accrual_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ) INTO has_accrual;
      IF NOT has_accrual THEN
        RETURN NEW;
      END IF;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_statutory_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_statutory_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ) INTO has_statutory;
      IF NOT has_statutory AND NOT has_zero THEN
        RAISE EXCEPTION 'Payroll deductions and contributions source is missing';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zzz_guard_payroll_statutory_source_close
      BEFORE INSERT OR UPDATE ON accounting.period FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_statutory_source_close();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                 WHERE kind = 'payroll_statutory_zero') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable statutory-zero payroll evidence';
      END IF;
    END $$;
    DROP TRIGGER zzz_guard_payroll_statutory_source_close ON accounting.period;
    DROP FUNCTION accounting.guard_payroll_statutory_source_close();
    CREATE OR REPLACE FUNCTION accounting.guard_payroll_zero_activity_closed_month()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_zero_individual')
         AND EXISTS (
           SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
             AND month >= NEW.month AND closed IS TRUE
         ) THEN
        RAISE EXCEPTION 'Closed period rejects a new monthly payroll source';
      END IF;
      RETURN NEW;
    END $$;
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment', 'payroll_zero_individual')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population',
                     'payroll_zero_individual'));
    """)
