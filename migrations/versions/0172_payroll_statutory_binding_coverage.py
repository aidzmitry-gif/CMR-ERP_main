"""Require statutory source coverage of each mapped gross payroll binding."""

from alembic import op

revision = "0172"
down_revision = "0171"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population',
                     'payroll_zero_individual', 'payroll_statutory_zero',
                     'payroll_stat_zero_person'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment', 'payroll_zero_individual',
                  'payroll_stat_zero_person')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_statutory_zero')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    CREATE OR REPLACE FUNCTION accounting.guard_payroll_zero_activity_closed_month()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind IN ('payroll_zero_activity', 'payroll_population',
                      'payroll_zero_individual', 'payroll_statutory_zero',
                      'payroll_stat_zero_person')
         AND EXISTS (
           SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
             AND month >= NEW.month AND closed IS TRUE
         ) THEN
        RAISE EXCEPTION 'Closed period rejects a new monthly payroll source';
      END IF;
      RETURN NEW;
    END $$;

    CREATE OR REPLACE FUNCTION accounting.guard_payroll_statutory_binding_close()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE has_statutory boolean;
    DECLARE has_gap boolean;
    BEGIN
      IF NOT NEW.closed OR (TG_OP = 'UPDATE' AND OLD.closed) THEN
        RETURN NEW;
      END IF;
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      SELECT EXISTS (
        SELECT 1 FROM accounting.payroll_statutory_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_statutory_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ) INTO has_statutory;
      IF NOT has_statutory THEN
        RETURN NEW; -- Revision 0171 requires a source or whole-month zero evidence.
      END IF;
      WITH gross_docs AS (
        SELECT r.source::jsonb AS source, r.command::jsonb AS command
        FROM accounting.payroll_accrual_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_accrual_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ), statutory_docs AS (
        SELECT r.source::jsonb AS source, r.command::jsonb AS command
        FROM accounting.payroll_statutory_receipt r
        JOIN accounting.entry e ON e.id = r.entry_id
        WHERE r.organization_id = NEW.organization_id AND r.month = NEW.month
          AND e.organization_id = NEW.organization_id
          AND e.operation = 'payroll_statutory_import'
          AND to_char(e.posting_date, 'YYYY-MM') = NEW.month
      ), gross_lines AS (
        SELECT CASE WHEN jsonb_typeof(item->'employment_binding_id') = 'number'
                    THEN (item->>'employment_binding_id')::bigint END AS binding_id
        FROM gross_docs d CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(d.source->'lines') = 'array'
               THEN d.source->'lines' ELSE '[]'::jsonb END) item
      ), statutory_lines AS (
        SELECT CASE WHEN jsonb_typeof(item->'employment_binding_id') = 'number'
                    THEN (item->>'employment_binding_id')::bigint END AS binding_id
        FROM statutory_docs d CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(d.source->'lines') = 'array'
               THEN d.source->'lines' ELSE '[]'::jsonb END) item
      )
      SELECT EXISTS (
        SELECT 1 FROM gross_docs d
        WHERE jsonb_typeof(d.source->'lines') IS DISTINCT FROM 'array'
           OR jsonb_array_length(CASE WHEN jsonb_typeof(d.source->'lines') = 'array'
                 THEN d.source->'lines' ELSE '[]'::jsonb END) = 0
           OR d.source->'lines' IS DISTINCT FROM d.command->'lines'
        UNION ALL
        SELECT 1 FROM statutory_docs d
        WHERE jsonb_typeof(d.source->'lines') IS DISTINCT FROM 'array'
           OR jsonb_array_length(CASE WHEN jsonb_typeof(d.source->'lines') = 'array'
                 THEN d.source->'lines' ELSE '[]'::jsonb END) = 0
           OR d.source->'lines' IS DISTINCT FROM d.command->'lines'
        UNION ALL
        SELECT 1 FROM statutory_lines s WHERE s.binding_id IS NULL
        UNION ALL
        SELECT 1 FROM gross_lines g WHERE g.binding_id IS NULL
           OR (NOT EXISTS (SELECT 1 FROM statutory_lines s WHERE s.binding_id = g.binding_id)
               AND NOT EXISTS (
                 SELECT 1 FROM accounting.payroll_evidence_file f
                 WHERE f.organization_id = NEW.organization_id AND f.month = NEW.month
                   AND f.kind = 'payroll_stat_zero_person'
                   AND f.employment_binding_id = g.binding_id
               ))
        UNION ALL
        SELECT 1 FROM statutory_lines s
        JOIN accounting.payroll_evidence_file f
          ON f.organization_id = NEW.organization_id AND f.month = NEW.month
         AND f.kind = 'payroll_stat_zero_person'
         AND f.employment_binding_id = s.binding_id
      ) INTO has_gap;
      IF has_gap THEN
        RAISE EXCEPTION 'Payroll statutory source does not cover all mapped gross accruals';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zzzz_guard_payroll_statutory_binding_close
      BEFORE INSERT OR UPDATE ON accounting.period FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_statutory_binding_close();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                 WHERE kind = 'payroll_stat_zero_person') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable individual statutory-zero evidence';
      END IF;
    END $$;
    DROP TRIGGER zzzz_guard_payroll_statutory_binding_close ON accounting.period;
    DROP FUNCTION accounting.guard_payroll_statutory_binding_close();
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
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment', 'payroll_zero_individual')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_statutory_zero')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population',
                     'payroll_zero_individual', 'payroll_statutory_zero'));
    """)
