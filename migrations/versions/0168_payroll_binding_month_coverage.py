"""Require a source for every known payroll binding before month close."""
from alembic import op

revision = "0168"
down_revision = "0167"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population',
                     'payroll_zero_individual'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment', 'payroll_zero_individual')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
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

    CREATE OR REPLACE FUNCTION accounting.guard_payroll_binding_coverage_close()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE has_known boolean;
    DECLARE has_accrual boolean;
    DECLARE has_unmapped boolean;
    DECLARE has_uncovered boolean;
    BEGIN
      IF NOT NEW.closed OR (TG_OP = 'UPDATE' AND OLD.closed) THEN
        RETURN NEW;
      END IF;
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      WITH dated AS (
        SELECT DISTINCT ON (employee_id, contract_ref, effective_from)
          id, employee_id, contract_ref, effective_from, state
        FROM accounting.payroll_employment_binding
        WHERE organization_id = NEW.organization_id
          AND effective_from < (NEW.month || '-01')::date + INTERVAL '1 month'
        ORDER BY employee_id, contract_ref, effective_from, revision DESC, id DESC
      ), intervals AS (
        SELECT id, effective_from, state,
          lead(effective_from) OVER (
            PARTITION BY employee_id, contract_ref ORDER BY effective_from
          ) AS next_from
        FROM dated
      ), active AS (
        SELECT id FROM intervals WHERE state = 'active'
          AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date)
      )
      SELECT EXISTS (SELECT 1 FROM active) INTO has_known;
      IF NOT has_known THEN
        RETURN NEW;
      END IF;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_accrual_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_accrual_import'
          AND e.source LIKE 'payroll:accrual:%'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ) INTO has_accrual;
      IF NOT has_accrual THEN
        RETURN NEW; -- Existing monthly-source guard handles the whole-month zero case.
      END IF;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_accrual_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_accrual_import'
          AND e.source LIKE 'payroll:accrual:%'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
          AND (jsonb_typeof(r.source::jsonb -> 'lines') IS DISTINCT FROM 'array'
            OR jsonb_array_length(CASE
              WHEN jsonb_typeof(r.source::jsonb -> 'lines') = 'array'
              THEN r.source::jsonb -> 'lines' ELSE '[]'::jsonb END) = 0
            OR r.source::jsonb -> 'lines' IS DISTINCT FROM r.command::jsonb -> 'lines'
            OR EXISTS (
              SELECT 1 FROM jsonb_array_elements(CASE
                WHEN jsonb_typeof(r.source::jsonb -> 'lines') = 'array'
                THEN r.source::jsonb -> 'lines' ELSE '[]'::jsonb END) item
              WHERE jsonb_typeof(item -> 'employment_binding_id') IS DISTINCT FROM 'number'
            ))
      ) INTO has_unmapped;
      IF has_unmapped THEN
        RAISE EXCEPTION 'Payroll accrual lines need stable employer bindings before closing';
      END IF;
      WITH dated AS (
        SELECT DISTINCT ON (employee_id, contract_ref, effective_from)
          id, employee_id, contract_ref, effective_from, state
        FROM accounting.payroll_employment_binding
        WHERE organization_id = NEW.organization_id
          AND effective_from < (NEW.month || '-01')::date + INTERVAL '1 month'
        ORDER BY employee_id, contract_ref, effective_from, revision DESC, id DESC
      ), intervals AS (
        SELECT id, effective_from, state,
          lead(effective_from) OVER (
            PARTITION BY employee_id, contract_ref ORDER BY effective_from
          ) AS next_from
        FROM dated
      ), active AS (
        SELECT id FROM intervals WHERE state = 'active'
          AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date)
      )
      SELECT EXISTS (
        SELECT 1 FROM active b
        WHERE NOT EXISTS (
          SELECT 1 FROM accounting.payroll_accrual_receipt r
          JOIN accounting.entry e ON e.id = r.entry_id
          CROSS JOIN LATERAL jsonb_array_elements(r.source::jsonb -> 'lines') item
          WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
            AND e.organization_id = NEW.organization_id
            AND e.operation = 'payroll_accrual_import'
            AND e.source LIKE 'payroll:accrual:%'
            AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
            AND item -> 'employment_binding_id' = to_jsonb(b.id)
        ) AND NOT EXISTS (
          SELECT 1 FROM accounting.payroll_evidence_file f
          WHERE f.organization_id = NEW.organization_id AND f.month = NEW.month
            AND f.kind = 'payroll_zero_individual' AND f.employment_binding_id = b.id
        )
      ) INTO has_uncovered;
      IF has_uncovered THEN
        RAISE EXCEPTION 'Known payroll binding coverage is incomplete';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zz_guard_payroll_binding_coverage_close
      BEFORE INSERT OR UPDATE ON accounting.period FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_binding_coverage_close();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                 WHERE kind = 'payroll_zero_individual') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable individual zero-payroll evidence';
      END IF;
    END $$;
    DROP TRIGGER zz_guard_payroll_binding_coverage_close ON accounting.period;
    DROP FUNCTION accounting.guard_payroll_binding_coverage_close();
    CREATE OR REPLACE FUNCTION accounting.guard_payroll_zero_activity_closed_month()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind IN ('payroll_zero_activity', 'payroll_population')
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
      OR (kind IN ('timesheet', 'base_adjustment')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population'));
    """)
