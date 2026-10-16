"""Append-only, source-backed payroll arithmetic reviews; no ledger posting."""
from alembic import op

revision = "0164"
down_revision = "0163"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.payroll_workpaper_review (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  employment_binding_id INTEGER NOT NULL REFERENCES accounting.payroll_employment_binding(id),
  month VARCHAR(7) NOT NULL,
  work_from DATE NOT NULL,
  work_to DATE NOT NULL,
  revision INTEGER NOT NULL,
  supersedes_id INTEGER REFERENCES accounting.payroll_workpaper_review(id),
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  basis_digest VARCHAR(64) NOT NULL,
  snapshot_digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  reviewer_evidence VARCHAR(2000) NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_payroll_workpaper_review_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_payroll_workpaper_review_revision UNIQUE (
    organization_id, employment_binding_id, month, work_from, work_to, revision
  ),
  CONSTRAINT payroll_workpaper_review_positive_revision CHECK (revision > 0),
  CONSTRAINT payroll_workpaper_review_month CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  CONSTRAINT payroll_workpaper_review_dates CHECK (
    work_from <= work_to
    AND to_char(work_from, 'YYYY-MM') = month
    AND to_char(work_to, 'YYYY-MM') = month
  )
);
CREATE INDEX ix_payroll_workpaper_review_scope
  ON accounting.payroll_workpaper_review (
    organization_id, employment_binding_id, month, work_from, work_to, revision DESC
  );

CREATE OR REPLACE FUNCTION accounting.guard_payroll_workpaper_review_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior_id INTEGER;
DECLARE prior_revision INTEGER;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Payroll review organization is unavailable';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM accounting.payroll_employment_binding
    WHERE id = NEW.employment_binding_id AND organization_id = NEW.organization_id
  ) THEN
    RAISE EXCEPTION 'Payroll review employment belongs to another organization';
  END IF;
  IF EXISTS (
    SELECT 1 FROM accounting.period
    WHERE organization_id = NEW.organization_id AND month >= NEW.month AND closed IS TRUE
  ) THEN
    RAISE EXCEPTION 'Payroll review cannot revise a closed period';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.basis_digest !~ '^[a-f0-9]{64}$'
     OR NEW.snapshot_digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) <> 'object'
     OR NEW.snapshot->>'status' IS DISTINCT FROM 'arithmetic_workpaper_only'
     OR NEW.snapshot->>'posting_available' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'statutory_payroll_certified' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'contract_and_timesheet_hashes_verified' IS DISTINCT FROM 'true'
     OR NEW.snapshot->>'rule_source_file_bytes_verified' IS DISTINCT FROM 'true'
     OR length(btrim(NEW.reviewer_evidence)) < 10
     OR length(btrim(NEW.actor)) = 0 THEN
    RAISE EXCEPTION 'Payroll arithmetic review evidence is invalid';
  END IF;
  IF EXISTS (
    SELECT 1 FROM accounting.payroll_workpaper_review
    WHERE organization_id = NEW.organization_id
      AND employment_binding_id = NEW.employment_binding_id
      AND month = NEW.month
      AND work_from <= NEW.work_to AND work_to >= NEW.work_from
      AND (work_from <> NEW.work_from OR work_to <> NEW.work_to)
  ) THEN
    RAISE EXCEPTION 'Payroll arithmetic review overlaps another work segment';
  END IF;
  SELECT id, revision INTO prior_id, prior_revision
  FROM accounting.payroll_workpaper_review
  WHERE organization_id = NEW.organization_id
    AND employment_binding_id = NEW.employment_binding_id
    AND month = NEW.month AND work_from = NEW.work_from AND work_to = NEW.work_to
  ORDER BY revision DESC LIMIT 1;
  IF prior_id IS NULL THEN
    IF NEW.revision <> 1 OR NEW.supersedes_id IS NOT NULL THEN
      RAISE EXCEPTION 'First payroll arithmetic review must start at revision one';
    END IF;
  ELSIF NEW.revision <> prior_revision + 1
        OR NEW.supersedes_id IS DISTINCT FROM prior_id THEN
    RAISE EXCEPTION 'Payroll arithmetic review must supersede its latest revision';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_payroll_workpaper_review_insert
  BEFORE INSERT ON accounting.payroll_workpaper_review
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_workpaper_review_insert();

CREATE OR REPLACE FUNCTION accounting.reject_payroll_workpaper_review_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Payroll arithmetic review history is immutable';
END $$;
CREATE TRIGGER immutable_payroll_workpaper_review
  BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_workpaper_review
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_workpaper_review_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_workpaper_review) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll arithmetic reviews';
      END IF;
    END $$;
    DROP TABLE accounting.payroll_workpaper_review;
    DROP FUNCTION accounting.guard_payroll_workpaper_review_insert();
    DROP FUNCTION accounting.reject_payroll_workpaper_review_mutation();
    """)
