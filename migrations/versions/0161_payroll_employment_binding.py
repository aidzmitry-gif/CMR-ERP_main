"""Append-only, organization-scoped HR employment evidence for payroll previews."""
from alembic import op

revision = "0161"
down_revision = "0160"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.payroll_employment_binding (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  employee_id INTEGER NOT NULL REFERENCES hr.employee(id),
  contract_ref VARCHAR(160) NOT NULL,
  effective_from DATE NOT NULL,
  revision INTEGER NOT NULL,
  state VARCHAR(8) NOT NULL,
  source_document VARCHAR(160) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_payroll_employment_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_payroll_employment_revision UNIQUE
    (organization_id, employee_id, contract_ref, effective_from, revision),
  CONSTRAINT payroll_employment_positive_revision CHECK (revision > 0),
  CONSTRAINT payroll_employment_state CHECK (state IN ('active', 'ended')),
  CONSTRAINT payroll_employment_evidence CHECK (
    length(btrim(contract_ref)) > 0 AND length(btrim(source_document)) > 0
    AND length(btrim(evidence)) >= 10 AND length(btrim(actor)) > 0
  )
);
CREATE INDEX ix_payroll_employment_current
  ON accounting.payroll_employment_binding
  (organization_id, employee_id, contract_ref, effective_from DESC, revision DESC);

CREATE OR REPLACE FUNCTION accounting.guard_payroll_employment_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_revision INTEGER;
DECLARE previous_state VARCHAR(8);
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Payroll employment organization is unavailable';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) <> 'object' THEN
    RAISE EXCEPTION 'Payroll employment identity or evidence is invalid';
  END IF;
  SELECT COALESCE(max(revision), 0) + 1 INTO expected_revision
  FROM accounting.payroll_employment_binding
  WHERE organization_id = NEW.organization_id
    AND employee_id = NEW.employee_id
    AND contract_ref = NEW.contract_ref
    AND effective_from = NEW.effective_from;
  IF NEW.revision <> expected_revision THEN
    RAISE EXCEPTION 'Payroll employment revision must append to its dated history';
  END IF;
  IF NEW.state = 'ended' THEN
    SELECT state INTO previous_state
    FROM accounting.payroll_employment_binding
    WHERE organization_id = NEW.organization_id
      AND employee_id = NEW.employee_id
      AND contract_ref = NEW.contract_ref
      AND effective_from <= NEW.effective_from
    ORDER BY effective_from DESC, revision DESC LIMIT 1;
    IF previous_state IS DISTINCT FROM 'active' THEN
      RAISE EXCEPTION 'Ending employment requires a prior active binding';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_payroll_employment_insert
  BEFORE INSERT ON accounting.payroll_employment_binding
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_employment_insert();

CREATE OR REPLACE FUNCTION accounting.reject_payroll_employment_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Payroll employment history is immutable';
END $$;
CREATE TRIGGER immutable_payroll_employment
  BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_employment_binding
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_employment_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_employment_binding) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll employment history';
      END IF;
    END $$;
    DROP TABLE accounting.payroll_employment_binding;
    DROP FUNCTION accounting.guard_payroll_employment_insert();
    DROP FUNCTION accounting.reject_payroll_employment_mutation();
    """)
