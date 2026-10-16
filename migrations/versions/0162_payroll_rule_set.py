"""Append-only organization payroll arithmetic ruleset."""
from alembic import op

revision = "0162"
down_revision = "0161"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.payroll_rule_set (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  policy_id INTEGER NOT NULL REFERENCES accounting.policy(id),
  effective_from DATE NOT NULL,
  revision INTEGER NOT NULL,
  gross_method VARCHAR(40) NOT NULL,
  rounding VARCHAR(20) NOT NULL,
  rate_rules JSONB NOT NULL,
  source_reference VARCHAR(200) NOT NULL,
  source_digest VARCHAR(64) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_payroll_rule_set_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_payroll_rule_set_revision UNIQUE (organization_id, effective_from, revision),
  CONSTRAINT payroll_rule_set_positive_revision CHECK (revision > 0),
  CONSTRAINT payroll_rule_set_gross_method CHECK (gross_method = 'monthly_salary_by_hours'),
  CONSTRAINT payroll_rule_set_rounding CHECK (rounding = 'half_up_cent'),
  CONSTRAINT payroll_rule_set_period CHECK (effective_from = date_trunc('month', effective_from)::date),
  CONSTRAINT payroll_rule_set_evidence CHECK (
    length(btrim(source_reference)) > 0 AND length(btrim(evidence)) >= 10
    AND length(btrim(actor)) > 0
  )
);
CREATE INDEX ix_payroll_rule_set_effective
  ON accounting.payroll_rule_set (organization_id, effective_from DESC, revision DESC);

CREATE OR REPLACE FUNCTION accounting.guard_payroll_rule_set_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_revision INTEGER;
DECLARE current_policy_id INTEGER;
DECLARE current_policy_verified BOOLEAN;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Payroll rule set organization is unavailable';
  END IF;
  SELECT id, normative_verified INTO current_policy_id, current_policy_verified
  FROM accounting.policy
  WHERE organization_id = NEW.organization_id AND effective_from <= NEW.effective_from
  ORDER BY effective_from DESC LIMIT 1;
  IF current_policy_id IS DISTINCT FROM NEW.policy_id
     OR current_policy_verified IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'Payroll rule set needs the current verified accounting policy';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.source_digest !~ '^[a-f0-9]{64}$'
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) <> 'object'
     OR jsonb_typeof(NEW.rate_rules) <> 'array'
     OR jsonb_array_length(NEW.rate_rules) NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'Payroll rule set identity or evidence is invalid';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.rate_rules) AS rule(value)
    WHERE jsonb_typeof(rule.value) <> 'object'
      OR coalesce(length(btrim(rule.value->>'code')), 0) = 0
      OR coalesce((rule.value->>'role') NOT IN ('employee_deduction', 'employer_contribution'), TRUE)
      OR coalesce((rule.value->>'base_mode') NOT IN ('gross', 'gross_less_adjustment'), TRUE)
      OR coalesce(length(btrim(rule.value->>'classification_evidence')), 0) < 10
  ) OR (
    SELECT count(DISTINCT rule.value->>'code')
    FROM jsonb_array_elements(NEW.rate_rules) AS rule(value)
  ) <> jsonb_array_length(NEW.rate_rules) THEN
    RAISE EXCEPTION 'Payroll rule set rate classification is incomplete';
  END IF;
  SELECT COALESCE(max(revision), 0) + 1 INTO expected_revision
  FROM accounting.payroll_rule_set
  WHERE organization_id = NEW.organization_id AND effective_from = NEW.effective_from;
  IF NEW.revision <> expected_revision THEN
    RAISE EXCEPTION 'Payroll rule set revision must append to its dated history';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_payroll_rule_set_insert
  BEFORE INSERT ON accounting.payroll_rule_set
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_payroll_rule_set_insert();

CREATE OR REPLACE FUNCTION accounting.reject_payroll_rule_set_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Payroll rule set history is immutable';
END $$;
CREATE TRIGGER immutable_payroll_rule_set
  BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.payroll_rule_set
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_payroll_rule_set_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.payroll_rule_set) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable payroll rule set history';
      END IF;
    END $$;
    DROP TABLE accounting.payroll_rule_set;
    DROP FUNCTION accounting.guard_payroll_rule_set_insert();
    DROP FUNCTION accounting.reject_payroll_rule_set_mutation();
    """)
