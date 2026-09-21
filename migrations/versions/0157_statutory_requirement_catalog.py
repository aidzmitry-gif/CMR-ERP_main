"""Add append-only external statutory form/rate requirements."""
from alembic import op


revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.statutory_requirement (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  kind VARCHAR(8) NOT NULL,
  code VARCHAR(120) NOT NULL,
  title VARCHAR(500) NOT NULL,
  effective_from DATE NOT NULL,
  revision INTEGER NOT NULL,
  source_reference VARCHAR(1000) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  form_version VARCHAR(120),
  electronic_format_version VARCHAR(120),
  rate_value NUMERIC(24, 12),
  rate_unit VARCHAR(120),
  rate_basis VARCHAR(500),
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_statutory_requirement_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_statutory_requirement_revision
    UNIQUE (organization_id, kind, code, effective_from, revision),
  CONSTRAINT statutory_requirement_kind CHECK (kind IN ('form', 'rate')),
  CONSTRAINT statutory_requirement_positive_revision CHECK (revision > 0),
  CONSTRAINT statutory_requirement_effective_period
    CHECK (effective_from = date_trunc('month', effective_from)::date),
  CONSTRAINT statutory_requirement_text_required CHECK (
    length(btrim(code)) > 0 AND length(btrim(title)) > 0
    AND length(btrim(source_reference)) > 0 AND length(btrim(evidence)) >= 10
  ),
  CONSTRAINT statutory_requirement_kind_fields CHECK (
    (kind = 'form'
      AND length(btrim(form_version)) > 0
      AND length(btrim(electronic_format_version)) > 0
      AND rate_value IS NULL AND rate_unit IS NULL AND rate_basis IS NULL)
    OR
    (kind = 'rate'
      AND form_version IS NULL AND electronic_format_version IS NULL
      AND rate_value IS NOT NULL AND rate_value >= 0
      AND length(btrim(rate_unit)) > 0 AND length(btrim(rate_basis)) > 0)
  )
);
CREATE INDEX ix_statutory_requirement_effective
  ON accounting.statutory_requirement (organization_id, kind, code, effective_from DESC, revision DESC);

CREATE OR REPLACE FUNCTION accounting.guard_statutory_requirement_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_revision INTEGER;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Statutory requirement organization is unavailable';
  END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR length(btrim(NEW.actor)) = 0
     OR jsonb_typeof(NEW.snapshot) <> 'object' THEN
    RAISE EXCEPTION 'Statutory requirement identity or evidence is invalid';
  END IF;
  SELECT COALESCE(max(revision), 0) + 1 INTO expected_revision
    FROM accounting.statutory_requirement
    WHERE organization_id = NEW.organization_id AND kind = NEW.kind AND code = NEW.code
      AND effective_from = NEW.effective_from;
  IF NEW.revision <> expected_revision THEN
    RAISE EXCEPTION 'Statutory requirement revision must append to its effective-period history';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_statutory_requirement_insert
  BEFORE INSERT ON accounting.statutory_requirement
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_statutory_requirement_insert();

CREATE OR REPLACE FUNCTION accounting.reject_statutory_requirement_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Statutory requirement history is immutable';
END $$;
CREATE TRIGGER immutable_statutory_requirement
  BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.statutory_requirement
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_statutory_requirement_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.statutory_requirement) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable statutory requirement history';
      END IF;
    END $$;
    DROP TABLE accounting.statutory_requirement;
    DROP FUNCTION accounting.guard_statutory_requirement_insert();
    DROP FUNCTION accounting.reject_statutory_requirement_mutation();
    """)
