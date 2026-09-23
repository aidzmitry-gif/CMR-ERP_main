"""Immutable source-roster review and PostgreSQL close boundary."""
from alembic import op

revision = "0167"
down_revision = "0166"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity', 'payroll_population'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
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

    CREATE TABLE accounting.payroll_population_review (
      id SERIAL PRIMARY KEY,
      organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
      month VARCHAR(7) NOT NULL,
      revision INTEGER NOT NULL,
      supersedes_id INTEGER REFERENCES accounting.payroll_population_review(id),
      source_file_id INTEGER NOT NULL REFERENCES accounting.payroll_evidence_file(id),
      source_file_sha256 VARCHAR(64) NOT NULL,
      source_system VARCHAR(80) NOT NULL,
      source_document VARCHAR(160) NOT NULL,
      source_employee_count INTEGER NOT NULL,
      binding_ids JSONB NOT NULL,
      employee_ids JSONB NOT NULL,
      evidence VARCHAR(2000) NOT NULL,
      request_key VARCHAR(36) NOT NULL,
      request_digest VARCHAR(64) NOT NULL,
      digest VARCHAR(64) NOT NULL,
      snapshot JSONB NOT NULL,
      actor VARCHAR(200) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT uq_payroll_population_request UNIQUE (organization_id, request_key),
      CONSTRAINT uq_payroll_population_revision UNIQUE (organization_id, month, revision),
      CONSTRAINT payroll_population_positive_revision CHECK (revision > 0),
      CONSTRAINT payroll_population_nonnegative_count CHECK (source_employee_count >= 0),
      CONSTRAINT payroll_population_month CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
    );
    CREATE INDEX ix_payroll_population_review_organization_id
      ON accounting.payroll_population_review (organization_id);
    CREATE INDEX ix_payroll_population_review_month
      ON accounting.payroll_population_review (month);

    CREATE OR REPLACE FUNCTION accounting.guard_payroll_population_review()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_row accounting.payroll_evidence_file%ROWTYPE;
    DECLARE prior accounting.payroll_population_review%ROWTYPE;
    DECLARE expected_bindings jsonb;
    DECLARE expected_employees jsonb;
    BEGIN
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      IF EXISTS (SELECT 1 FROM accounting.period
                 WHERE organization_id = NEW.organization_id
                   AND month >= NEW.month AND closed IS TRUE) THEN
        RAISE EXCEPTION 'Closed period blocks payroll population review';
      END IF;
      SELECT * INTO source_row FROM accounting.payroll_evidence_file
        WHERE id = NEW.source_file_id AND organization_id = NEW.organization_id
          AND month = NEW.month AND kind = 'payroll_population';
      IF NOT FOUND OR source_row.sha256 IS DISTINCT FROM NEW.source_file_sha256
         OR source_row.reference IS DISTINCT FROM NEW.source_document THEN
        RAISE EXCEPTION 'Payroll population review source file mismatch';
      END IF;
      SELECT * INTO prior FROM accounting.payroll_population_review
        WHERE organization_id = NEW.organization_id AND month = NEW.month
        ORDER BY revision DESC LIMIT 1;
      IF NEW.revision <> coalesce(prior.revision, 0) + 1
         OR NEW.supersedes_id IS DISTINCT FROM prior.id THEN
        RAISE EXCEPTION 'Payroll population review must extend the current revision';
      END IF;
      WITH dated AS (
        SELECT DISTINCT ON (employee_id, contract_ref, effective_from)
          id, employee_id, contract_ref, effective_from, state
        FROM accounting.payroll_employment_binding
        WHERE organization_id = NEW.organization_id
          AND effective_from < (NEW.month || '-01')::date + INTERVAL '1 month'
        ORDER BY employee_id, contract_ref, effective_from, revision DESC, id DESC
      ), intervals AS (
        SELECT id, employee_id, effective_from, state,
          lead(effective_from) OVER (
            PARTITION BY employee_id, contract_ref ORDER BY effective_from
          ) AS next_from
        FROM dated
      ), active AS (
        SELECT id, employee_id FROM intervals WHERE state = 'active'
          AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date)
      )
      SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb),
             coalesce((SELECT jsonb_agg(employee_id ORDER BY employee_id)
                       FROM (SELECT DISTINCT employee_id FROM active) people), '[]'::jsonb)
        INTO expected_bindings, expected_employees FROM active;
      IF NEW.binding_ids IS DISTINCT FROM expected_bindings
         OR NEW.employee_ids IS DISTINCT FROM expected_employees
         OR NEW.source_employee_count <> jsonb_array_length(expected_employees)
         OR NEW.snapshot->'binding_ids' IS DISTINCT FROM NEW.binding_ids
         OR NEW.snapshot->'employee_ids' IS DISTINCT FROM NEW.employee_ids
         OR NEW.snapshot->>'source_file_sha256' IS DISTINCT FROM NEW.source_file_sha256
         OR NEW.snapshot->>'request_key' IS DISTINCT FROM NEW.request_key
         OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
         OR NEW.request_digest !~ '^[a-f0-9]{64}$'
         OR NEW.digest !~ '^[a-f0-9]{64}$'
         OR length(btrim(NEW.source_system)) = 0
         OR length(btrim(NEW.evidence)) < 10
         OR length(btrim(NEW.actor)) = 0 THEN
        RAISE EXCEPTION 'Payroll population review differs from known roster or source';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER guard_payroll_population_review
      BEFORE INSERT ON accounting.payroll_population_review FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_population_review();
    CREATE TRIGGER immutable_payroll_population_review
      BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_population_review
      FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_evidence_mutation();

    CREATE OR REPLACE FUNCTION accounting.guard_payroll_population_period_close()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE expected_bindings jsonb;
    DECLARE reviewed_bindings jsonb;
    DECLARE expected_employees jsonb;
    DECLARE reviewed_employees jsonb;
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
        SELECT id, employee_id, effective_from, state,
          lead(effective_from) OVER (
            PARTITION BY employee_id, contract_ref ORDER BY effective_from
          ) AS next_from
        FROM dated
      )
      SELECT coalesce(jsonb_agg(id ORDER BY id), '[]'::jsonb),
             coalesce((SELECT jsonb_agg(employee_id ORDER BY employee_id)
                       FROM (SELECT DISTINCT employee_id FROM intervals
                             WHERE state = 'active'
                               AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date)
                       ) people), '[]'::jsonb)
        INTO expected_bindings, expected_employees FROM intervals WHERE state = 'active'
          AND (next_from IS NULL OR next_from > (NEW.month || '-01')::date);
      IF expected_bindings <> '[]'::jsonb THEN
        SELECT binding_ids, employee_ids INTO reviewed_bindings, reviewed_employees
          FROM accounting.payroll_population_review
          WHERE organization_id = NEW.organization_id AND month = NEW.month
          ORDER BY revision DESC LIMIT 1;
        IF reviewed_bindings IS DISTINCT FROM expected_bindings
           OR reviewed_employees IS DISTINCT FROM expected_employees THEN
          RAISE EXCEPTION 'Current payroll population review required before closing';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zz_guard_payroll_population_period_close
      BEFORE INSERT OR UPDATE ON accounting.period FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_population_period_close();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_population_review)
         OR EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                    WHERE kind = 'payroll_population') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll population history';
      END IF;
    END $$;
    DROP TRIGGER zz_guard_payroll_population_period_close ON accounting.period;
    DROP FUNCTION accounting.guard_payroll_population_period_close();
    DROP TRIGGER immutable_payroll_population_review ON accounting.payroll_population_review;
    DROP TRIGGER guard_payroll_population_review ON accounting.payroll_population_review;
    DROP FUNCTION accounting.guard_payroll_population_review();
    DROP TABLE accounting.payroll_population_review;
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
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'base_adjustment')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind = 'payroll_zero_activity' AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'payroll_policy',
                     'base_adjustment', 'payroll_zero_activity'));
    """)
