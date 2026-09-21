"""Add immutable per-organization chart catalogue adoption provenance."""
from alembic import op


revision = "0158"
down_revision = "0157"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.catalog_adoption (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  effective_from DATE NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  catalog_version VARCHAR(200) NOT NULL,
  catalog_source VARCHAR(2000) NOT NULL,
  catalog_review_state JSONB NOT NULL,
  current_normative_verified BOOLEAN NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_catalog_adoption_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_catalog_adoption_effective UNIQUE (organization_id, effective_from),
  CONSTRAINT uq_catalog_adoption_organization_id UNIQUE (organization_id, id),
  CONSTRAINT catalog_adoption_text_required CHECK (
    length(btrim(evidence)) >= 10 AND length(btrim(catalog_version)) > 0
    AND length(btrim(catalog_source)) > 0 AND length(btrim(actor)) > 0
  )
);
CREATE INDEX ix_catalog_adoption_effective
  ON accounting.catalog_adoption (organization_id, effective_from DESC, id DESC);

ALTER TABLE accounting.account ADD COLUMN catalog_adoption_id INTEGER;
ALTER TABLE accounting.account ADD CONSTRAINT fk_account_catalog_adoption_organization
  FOREIGN KEY (organization_id, catalog_adoption_id)
  REFERENCES accounting.catalog_adoption(organization_id, id);
CREATE INDEX ix_account_catalog_adoption_id ON accounting.account (catalog_adoption_id);

CREATE OR REPLACE FUNCTION accounting.guard_catalog_adoption_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Catalog adoption organization is unavailable'; END IF;
  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.request_digest !~ '^[a-f0-9]{64}$' OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) <> 'object' OR jsonb_typeof(NEW.catalog_review_state) <> 'object' THEN
    RAISE EXCEPTION 'Catalog adoption identity or snapshot is invalid';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_catalog_adoption_insert BEFORE INSERT ON accounting.catalog_adoption
FOR EACH ROW EXECUTE FUNCTION accounting.guard_catalog_adoption_insert();

CREATE OR REPLACE FUNCTION accounting.guard_account_catalog_adoption() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.catalog_adoption_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM accounting.catalog_adoption ca
    WHERE ca.id = NEW.catalog_adoption_id AND ca.organization_id = NEW.organization_id
      AND ca.effective_from <= NEW.valid_from
  ) THEN RAISE EXCEPTION 'Account catalogue adoption is outside organization or effective date'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_account_catalog_adoption BEFORE INSERT ON accounting.account
FOR EACH ROW EXECUTE FUNCTION accounting.guard_account_catalog_adoption();

CREATE OR REPLACE FUNCTION accounting.reject_catalog_adoption_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Catalog adoption history is immutable';
END $$;
CREATE TRIGGER immutable_catalog_adoption BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.catalog_adoption
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_catalog_adoption_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.catalog_adoption) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable catalogue-adoption history';
      END IF;
    END $$;
    DROP TRIGGER guard_account_catalog_adoption ON accounting.account;
    DROP FUNCTION accounting.guard_account_catalog_adoption();
    DROP INDEX accounting.ix_account_catalog_adoption_id;
    ALTER TABLE accounting.account DROP CONSTRAINT fk_account_catalog_adoption_organization;
    ALTER TABLE accounting.account DROP COLUMN catalog_adoption_id;
    DROP TABLE accounting.catalog_adoption;
    DROP FUNCTION accounting.guard_catalog_adoption_insert();
    DROP FUNCTION accounting.reject_catalog_adoption_mutation();
    """)
