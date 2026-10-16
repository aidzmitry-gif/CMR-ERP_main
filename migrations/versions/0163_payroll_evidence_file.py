"""Organization-bound immutable metadata for private payroll source files."""
from alembic import op

revision = "0163"
down_revision = "0162"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.payroll_evidence_file (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  employment_binding_id INTEGER REFERENCES accounting.payroll_employment_binding(id),
  kind VARCHAR(24) NOT NULL,
  month VARCHAR(7),
  reference VARCHAR(160) NOT NULL,
  filename VARCHAR(160) NOT NULL,
  content_type VARCHAR(120) NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 VARCHAR(64) NOT NULL,
  storage_filename VARCHAR(80) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_payroll_evidence_request UNIQUE (organization_id, request_key),
  CONSTRAINT payroll_evidence_kind CHECK (
    kind IN ('employment_contract', 'timesheet', 'payroll_policy', 'base_adjustment')
  ),
  CONSTRAINT payroll_evidence_size CHECK (size_bytes > 0 AND size_bytes <= 10485760),
  CONSTRAINT payroll_evidence_subject CHECK (
    (kind = 'payroll_policy' AND employment_binding_id IS NULL AND month IS NULL)
    OR (kind = 'employment_contract' AND employment_binding_id IS NOT NULL AND month IS NULL)
    OR (kind IN ('timesheet', 'base_adjustment')
        AND employment_binding_id IS NOT NULL AND month IS NOT NULL)
  ),
  CONSTRAINT payroll_evidence_month CHECK (
    month IS NULL OR (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$')
  )
);
CREATE INDEX ix_payroll_evidence_subject
  ON accounting.payroll_evidence_file (organization_id, employment_binding_id, kind, month, id);

CREATE OR REPLACE FUNCTION accounting.guard_payroll_evidence_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Payroll evidence organization is unavailable';
  END IF;
  IF NEW.employment_binding_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM accounting.payroll_employment_binding
    WHERE id = NEW.employment_binding_id AND organization_id = NEW.organization_id
  ) THEN
    RAISE EXCEPTION 'Payroll evidence employment belongs to another organization';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.sha256 !~ '^[a-f0-9]{64}$'
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR NEW.storage_filename !~ '^[a-f0-9]{32}\.(pdf|doc|docx|xlsx|jpg|png)$'
     OR jsonb_typeof(NEW.snapshot) <> 'object'
     OR length(btrim(NEW.reference)) = 0
     OR length(btrim(NEW.filename)) = 0
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) = 0 THEN
    RAISE EXCEPTION 'Payroll evidence file metadata is invalid';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_payroll_evidence_insert
  BEFORE INSERT ON accounting.payroll_evidence_file
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_evidence_insert();

CREATE OR REPLACE FUNCTION accounting.reject_payroll_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Payroll evidence file history is immutable';
END $$;
CREATE TRIGGER immutable_payroll_evidence
  BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_evidence_file
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_evidence_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_evidence_file) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll evidence file history';
      END IF;
    END $$;
    DROP TABLE accounting.payroll_evidence_file;
    DROP FUNCTION accounting.guard_payroll_evidence_insert();
    DROP FUNCTION accounting.reject_payroll_evidence_mutation();
    """)
