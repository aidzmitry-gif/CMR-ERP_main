"""Add private, append-only employee applicability reviews."""

from alembic import op

revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'work_schedule',
                     'payroll_policy', 'base_adjustment', 'payroll_zero_activity',
                     'payroll_population', 'payroll_zero_individual',
                     'payroll_statutory_zero', 'payroll_stat_zero_person',
                     'payroll_applicability'));
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'work_schedule', 'base_adjustment',
                  'payroll_zero_individual', 'payroll_stat_zero_person', 'payroll_applicability')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_statutory_zero')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );

    CREATE TABLE accounting.payroll_applicability_review (
      id SERIAL PRIMARY KEY,
      organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
      employment_binding_id INTEGER NOT NULL REFERENCES accounting.payroll_employment_binding(id),
      month VARCHAR(7) NOT NULL,
      revision INTEGER NOT NULL,
      supersedes_id INTEGER REFERENCES accounting.payroll_applicability_review(id),
      source_file_id INTEGER NOT NULL REFERENCES accounting.payroll_evidence_file(id),
      source_file_sha256 VARCHAR(64) NOT NULL,
      source_document VARCHAR(160) NOT NULL,
      facts JSONB NOT NULL,
      evidence VARCHAR(2000) NOT NULL,
      request_key VARCHAR(36) NOT NULL,
      request_digest VARCHAR(64) NOT NULL,
      digest VARCHAR(64) NOT NULL,
      snapshot JSONB NOT NULL,
      actor VARCHAR(200) NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT uq_payroll_applicability_request UNIQUE (organization_id, request_key),
      CONSTRAINT uq_payroll_applicability_revision UNIQUE
        (organization_id, employment_binding_id, month, revision),
      CONSTRAINT payroll_applicability_positive_revision CHECK (revision > 0),
      CONSTRAINT payroll_applicability_month CHECK
        (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
      CONSTRAINT payroll_applicability_facts CHECK
        (jsonb_typeof(facts) = 'array' AND jsonb_array_length(facts) BETWEEN 1 AND 6)
    );
    CREATE INDEX ix_payroll_applicability_review_organization_id
      ON accounting.payroll_applicability_review (organization_id);
    CREATE INDEX ix_payroll_applicability_review_employment_binding_id
      ON accounting.payroll_applicability_review (employment_binding_id);
    CREATE INDEX ix_payroll_applicability_review_month
      ON accounting.payroll_applicability_review (month);

    CREATE FUNCTION accounting.guard_payroll_applicability_file()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.kind = 'payroll_applicability' AND EXISTS (
        SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
          AND month >= NEW.month AND closed IS TRUE
      ) THEN
        RAISE EXCEPTION 'Closed period blocks payroll applicability source';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER guard_payroll_applicability_file
      BEFORE INSERT ON accounting.payroll_evidence_file FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_applicability_file();

    CREATE FUNCTION accounting.guard_payroll_applicability_review()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_row accounting.payroll_evidence_file%ROWTYPE;
    DECLARE prior accounting.payroll_applicability_review%ROWTYPE;
    DECLARE binding_row accounting.payroll_employment_binding%ROWTYPE;
    BEGIN
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      IF NOT FOUND OR EXISTS (
        SELECT 1 FROM accounting.period WHERE organization_id = NEW.organization_id
          AND month >= NEW.month AND closed IS TRUE
      ) THEN
        RAISE EXCEPTION 'Payroll applicability organization or period is unavailable';
      END IF;
      SELECT * INTO binding_row FROM accounting.payroll_employment_binding
        WHERE id = NEW.employment_binding_id AND organization_id = NEW.organization_id;
      IF NOT FOUND OR binding_row.effective_from >=
          ((NEW.month || '-01')::date + INTERVAL '1 month') THEN
        RAISE EXCEPTION 'Payroll applicability binding is unavailable';
      END IF;
      SELECT * INTO source_row FROM accounting.payroll_evidence_file
        WHERE id = NEW.source_file_id AND organization_id = NEW.organization_id
          AND employment_binding_id = NEW.employment_binding_id
          AND month = NEW.month AND kind = 'payroll_applicability';
      IF NOT FOUND OR source_row.sha256 IS DISTINCT FROM NEW.source_file_sha256
         OR source_row.reference IS DISTINCT FROM NEW.source_document THEN
        RAISE EXCEPTION 'Payroll applicability source file mismatch';
      END IF;
      SELECT * INTO prior FROM accounting.payroll_applicability_review
        WHERE organization_id = NEW.organization_id
          AND employment_binding_id = NEW.employment_binding_id AND month = NEW.month
        ORDER BY revision DESC LIMIT 1;
      IF NEW.revision <> coalesce(prior.revision, 0) + 1
         OR NEW.supersedes_id IS DISTINCT FROM prior.id
         OR NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
         OR NEW.snapshot->>'employment_binding_id' IS DISTINCT FROM NEW.employment_binding_id::text
         OR NEW.snapshot->>'month' IS DISTINCT FROM NEW.month
         OR NEW.snapshot->>'revision' IS DISTINCT FROM NEW.revision::text
         OR NEW.snapshot->>'source_file_id' IS DISTINCT FROM NEW.source_file_id::text
         OR NEW.snapshot->>'source_file_sha256' IS DISTINCT FROM NEW.source_file_sha256
         OR NEW.snapshot->>'source_document' IS DISTINCT FROM NEW.source_document
         OR NEW.snapshot->'facts' IS DISTINCT FROM NEW.facts
         OR NEW.snapshot->>'request_key' IS DISTINCT FROM NEW.request_key
         OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
         OR NEW.request_digest !~ '^[a-f0-9]{64}$'
         OR NEW.digest !~ '^[a-f0-9]{64}$'
         OR length(btrim(NEW.evidence)) < 10
         OR length(btrim(NEW.actor)) = 0 THEN
        RAISE EXCEPTION 'Payroll applicability review snapshot or revision mismatch';
      END IF;
      IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.facts) AS f
        WHERE f->>'code' NOT IN (
          'income_kind_and_tax_agent_treatment', 'year_to_date_taxable_income',
          'main_workplace_and_deduction_basis',
          'dependants_special_status_and_deduction_documents',
          'other_deduction_claims_and_documents', 'insurance_applicability_and_base'
        ) OR length(btrim(coalesce(f->>'finding', ''))) < 10
          OR length(btrim(coalesce(f->>'source_locator', ''))) < 3
      ) OR (SELECT count(DISTINCT f->>'code') FROM jsonb_array_elements(NEW.facts) AS f)
           <> jsonb_array_length(NEW.facts) THEN
        RAISE EXCEPTION 'Payroll applicability facts require distinct sourced findings';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER guard_payroll_applicability_review
      BEFORE INSERT ON accounting.payroll_applicability_review FOR EACH ROW
      EXECUTE FUNCTION accounting.guard_payroll_applicability_review();
    CREATE TRIGGER immutable_payroll_applicability_review
      BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_applicability_review
      FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_evidence_mutation();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_applicability_review)
         OR EXISTS (SELECT 1 FROM accounting.payroll_evidence_file
                    WHERE kind = 'payroll_applicability') THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll applicability history';
      END IF;
    END $$;
    DROP TRIGGER immutable_payroll_applicability_review ON accounting.payroll_applicability_review;
    DROP TRIGGER guard_payroll_applicability_review ON accounting.payroll_applicability_review;
    DROP FUNCTION accounting.guard_payroll_applicability_review();
    DROP TRIGGER guard_payroll_applicability_file ON accounting.payroll_evidence_file;
    DROP FUNCTION accounting.guard_payroll_applicability_file();
    DROP TABLE accounting.payroll_applicability_review;
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_subject;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_subject CHECK (
      (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
      OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
      OR (kind IN ('timesheet', 'work_schedule', 'base_adjustment',
                  'payroll_zero_individual', 'payroll_stat_zero_person')
          AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
      OR (kind IN ('payroll_zero_activity', 'payroll_population', 'payroll_statutory_zero')
          AND employment_binding_id IS NULL AND month IS NOT NULL)
    );
    ALTER TABLE accounting.payroll_evidence_file DROP CONSTRAINT payroll_evidence_kind;
    ALTER TABLE accounting.payroll_evidence_file ADD CONSTRAINT payroll_evidence_kind
      CHECK (kind IN ('employment_contract', 'timesheet', 'work_schedule',
                     'payroll_policy', 'base_adjustment', 'payroll_zero_activity',
                     'payroll_population', 'payroll_zero_individual',
                     'payroll_statutory_zero', 'payroll_stat_zero_person'));
    """)
