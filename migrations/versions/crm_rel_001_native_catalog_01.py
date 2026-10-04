"""Scoped incoming catalog identities and immutable observed source revisions."""
from alembic import op

revision = "crm_rel_001_native_catalog_01"
down_revision = "crm_rel_001_output_source_01"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE catalog_source_identity (
 id SERIAL PRIMARY KEY, namespace VARCHAR(64) NOT NULL, entity VARCHAR(128) NOT NULL,
 source_guid VARCHAR(36) NOT NULL, kind VARCHAR(16) NOT NULL,
 sku_id INTEGER REFERENCES sku(id) ON DELETE RESTRICT,
 group_id INTEGER REFERENCES ref_nomenclature_category(id) ON DELETE RESTRICT,
 counterparty_id INTEGER REFERENCES counterparty(id) ON DELETE RESTRICT,
 source_sha VARCHAR(64) NOT NULL, revision_no INTEGER NOT NULL,
 target_sha VARCHAR(64), holds JSON NOT NULL,
 CONSTRAINT uq_catalog_source_identity UNIQUE(namespace,entity,source_guid),
 CONSTRAINT ck_catalog_source_kind CHECK(kind IN ('sku','group','counterparty')),
 CONSTRAINT ck_catalog_source_target CHECK (
  (sku_id IS NULL AND group_id IS NULL AND counterparty_id IS NULL) OR
  (kind='sku' AND sku_id IS NOT NULL AND group_id IS NULL AND counterparty_id IS NULL) OR
  (kind='group' AND group_id IS NOT NULL AND sku_id IS NULL AND counterparty_id IS NULL) OR
  (kind='counterparty' AND counterparty_id IS NOT NULL AND sku_id IS NULL AND group_id IS NULL))
);
CREATE TABLE catalog_source_revision (
 id SERIAL PRIMARY KEY, identity_id INTEGER NOT NULL REFERENCES catalog_source_identity(id) ON DELETE RESTRICT,
 revision_no INTEGER NOT NULL, source_sha VARCHAR(64) NOT NULL, data_version VARCHAR(255) NOT NULL,
 previous_sha VARCHAR(64), source_text TEXT NOT NULL, target_sha VARCHAR(64), holds JSON NOT NULL,
 actor VARCHAR(128) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT uq_catalog_source_revision UNIQUE(identity_id,revision_no),
 CONSTRAINT ck_catalog_source_revision_positive CHECK(revision_no>0)
);
CREATE INDEX ix_catalog_source_revision_identity_id ON catalog_source_revision(identity_id);
CREATE FUNCTION guard_catalog_source_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound catalog_source_identity;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Catalog source revision is append-only'; END IF;
 SELECT * INTO bound FROM catalog_source_identity WHERE id=NEW.identity_id;
 IF encode(sha256(convert_to(NEW.source_text,'UTF8')),'hex') IS DISTINCT FROM NEW.source_sha
    OR (NEW.source_text::jsonb->>'DataVersion') IS DISTINCT FROM NEW.data_version
    OR (NEW.source_text::jsonb->>'Ref_Key')::uuid::text IS DISTINCT FROM bound.source_guid THEN
  RAISE EXCEPTION 'Catalog source revision payload differs from its seal';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_catalog_source_revision BEFORE INSERT OR UPDATE OR DELETE
 ON catalog_source_revision FOR EACH ROW EXECUTE FUNCTION guard_catalog_source_revision();
CREATE TRIGGER no_truncate_catalog_source_revision BEFORE TRUNCATE ON catalog_source_revision
 FOR EACH STATEMENT EXECUTE FUNCTION guard_catalog_source_revision();
CREATE FUNCTION guard_catalog_source_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.namespace IS DISTINCT FROM OLD.namespace OR NEW.entity IS DISTINCT FROM OLD.entity
    OR NEW.source_guid IS DISTINCT FROM OLD.source_guid OR NEW.kind IS DISTINCT FROM OLD.kind THEN
  RAISE EXCEPTION 'Catalog source identity is immutable';
 END IF;
 IF (OLD.sku_id IS NOT NULL AND NEW.sku_id IS DISTINCT FROM OLD.sku_id)
  OR (OLD.group_id IS NOT NULL AND NEW.group_id IS DISTINCT FROM OLD.group_id)
  OR (OLD.counterparty_id IS NOT NULL AND NEW.counterparty_id IS DISTINCT FROM OLD.counterparty_id) THEN
  RAISE EXCEPTION 'Catalog source native binding is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_catalog_source_identity BEFORE UPDATE ON catalog_source_identity
 FOR EACH ROW EXECUTE FUNCTION guard_catalog_source_identity();
"""


def upgrade():
    op.execute(DDL)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM catalog_source_identity) THEN
        RAISE EXCEPTION 'Cannot downgrade catalog import with preserved source history';
      END IF;
    END $$;
    DROP TABLE catalog_source_revision;
    DROP TABLE catalog_source_identity;
    DROP FUNCTION guard_catalog_source_revision();
    DROP FUNCTION guard_catalog_source_identity();""")
