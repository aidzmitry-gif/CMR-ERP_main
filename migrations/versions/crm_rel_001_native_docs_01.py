"""Append-only held source documents, with immutable namespace input policy."""

from alembic import op

revision = "crm_rel_001_native_docs_01"
down_revision = "crm_rel_001_native_catalog_01"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE document_source_revision (
 id SERIAL PRIMARY KEY, namespace VARCHAR(64) NOT NULL, entity VARCHAR(128) NOT NULL,
 source_guid VARCHAR(36) NOT NULL, source_scope VARCHAR(48) NOT NULL,
 revision_no INTEGER NOT NULL, source_sha VARCHAR(64) NOT NULL,
 data_version VARCHAR(255) NOT NULL, previous_sha VARCHAR(64), source_text TEXT NOT NULL,
 holds JSON NOT NULL, actor VARCHAR(128) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 organization_sha256 VARCHAR(64) NOT NULL, period_start TIMESTAMP NOT NULL,
 period_end TIMESTAMP NOT NULL, entity_scopes_sha256 VARCHAR(64) NOT NULL,
 entity_scopes_text TEXT NOT NULL,
 CONSTRAINT uq_document_source_revision UNIQUE(namespace,entity,source_guid,revision_no),
 CONSTRAINT uq_document_source_version UNIQUE(namespace,entity,source_guid,data_version),
 CONSTRAINT ck_document_source_revision_positive CHECK(revision_no>0),
 CONSTRAINT ck_document_source_revision_period CHECK(period_start<period_end)
);
CREATE FUNCTION guard_document_source_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 policy document_source_revision;
 prior document_source_revision;
 raw JSON;
 scopes JSONB;
 held JSONB;
 observed TIMESTAMP;
 canonical_guid TEXT := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_APPEND_ONLY'; END IF;
 IF current_setting('transaction_isolation') <> 'read committed' THEN
  RAISE EXCEPTION 'DOCUMENT_ISOLATION_REQUIRED';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('document:'||NEW.namespace,0));
 IF length(NEW.namespace)=0 OR length(NEW.entity)=0 OR length(NEW.actor)=0
    OR length(NEW.data_version)=0 OR NEW.source_guid !~ canonical_guid
    OR NEW.source_guid='00000000-0000-0000-0000-000000000000'
    OR NEW.organization_sha256 !~ '^[0-9a-f]{64}$'
    OR NEW.period_start>=NEW.period_end OR NOT isfinite(NEW.period_start) OR NOT isfinite(NEW.period_end)
    OR octet_length(NEW.source_text) NOT BETWEEN 1 AND 16777216
    OR octet_length(NEW.entity_scopes_text) NOT BETWEEN 1 AND 32768
    OR encode(sha256(convert_to(NEW.source_text,'UTF8')),'hex') IS DISTINCT FROM NEW.source_sha
    OR encode(sha256(convert_to(NEW.entity_scopes_text,'UTF8')),'hex') IS DISTINCT FROM NEW.entity_scopes_sha256 THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_SEAL';
 END IF;
 BEGIN
  raw:=NEW.source_text::json;
  scopes:=NEW.entity_scopes_text::jsonb;
  held:=NEW.holds::jsonb;
 EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_SEAL'; END;
 IF json_typeof(raw) IS DISTINCT FROM 'object' OR jsonb_typeof(scopes) IS DISTINCT FROM 'object'
    OR jsonb_typeof(held) IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_SEAL';
 END IF;
 IF EXISTS (
   WITH RECURSIVE nodes(value) AS (
     SELECT raw
     UNION ALL
     SELECT child.value FROM nodes n CROSS JOIN LATERAL (
       SELECT value FROM json_each(CASE WHEN json_typeof(n.value)='object' THEN n.value ELSE '{}'::json END)
       UNION ALL
       SELECT value FROM json_array_elements(CASE WHEN json_typeof(n.value)='array' THEN n.value ELSE '[]'::json END)
     ) child
   )
   SELECT 1 FROM nodes n WHERE EXISTS (
     SELECT key FROM json_each(CASE WHEN json_typeof(n.value)='object' THEN n.value ELSE '{}'::json END)
     GROUP BY key HAVING count(*)>1
   )
 ) THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_SEAL'; END IF;
 IF EXISTS(SELECT key FROM json_each(NEW.entity_scopes_text::json) GROUP BY key HAVING count(*)>1)
    OR (SELECT count(*) FROM jsonb_each(scopes)) NOT BETWEEN 1 AND 128
    OR EXISTS(SELECT 1 FROM jsonb_each(scopes) WHERE length(key)>128 OR key !~ '^Document_[[:alnum:]_]+$'
         OR jsonb_typeof(value) IS DISTINCT FROM 'string'
         OR value#>>'{}' NOT IN ('BOUND_ORGANIZATION','SHARED_OR_ORG_UNEXPOSED_NOT_POSTABLE'))
    OR scopes->>NEW.entity IS DISTINCT FROM NEW.source_scope THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_SCOPE';
 END IF;
 IF NEW.entity_scopes_text IS DISTINCT FROM (
   SELECT '{'||string_agg(to_json(key)::text||':'||value::text,',' ORDER BY key COLLATE "C")||'}'
   FROM jsonb_each(scopes)
 ) THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_SCOPE'; END IF;
 IF json_typeof(raw->'Ref_Key') IS DISTINCT FROM 'string'
    OR raw->>'Ref_Key' IS DISTINCT FROM NEW.source_guid
    OR json_typeof(raw->'DataVersion') IS DISTINCT FROM 'string'
    OR raw->>'DataVersion' IS DISTINCT FROM NEW.data_version
    OR json_typeof(raw->'Date') IS DISTINCT FROM 'string'
    OR json_typeof(raw->'Posted') IS DISTINCT FROM 'boolean'
    OR json_typeof(raw->'DeletionMark') IS DISTINCT FROM 'boolean' THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_SEAL';
 END IF;
 IF raw->>'Date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}(:[0-9]{2}([.][0-9]{1,6})?)?)?$' THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_PERIOD';
 END IF;
 BEGIN observed:=(raw->>'Date')::timestamp;
 EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_PERIOD'; END;
 IF NOT (observed>=NEW.period_start AND observed<NEW.period_end) THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_PERIOD';
 END IF;
 IF NEW.source_scope='BOUND_ORGANIZATION' AND (
    json_typeof(raw->'Организация_Key') IS DISTINCT FROM 'string'
    OR raw->>'Организация_Key' !~ canonical_guid
    OR raw->>'Организация_Key'='00000000-0000-0000-0000-000000000000'
    OR encode(sha256(convert_to(raw->>'Организация_Key','UTF8')),'hex') IS DISTINCT FROM NEW.organization_sha256) THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_ORG';
 END IF;
 IF jsonb_array_length(held) NOT BETWEEN 1 AND 64
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(held) WHERE jsonb_typeof(value) IS DISTINCT FROM 'string'
         OR length(value#>>'{}') NOT BETWEEN 1 AND 128)
    OR (SELECT count(DISTINCT value) FROM jsonb_array_elements(held))<>jsonb_array_length(held)
    OR NOT held @> '["OPERATIONAL_DOCUMENT_MAPPING_NOT_ACCEPTED","FINANCIAL_POSTING_NOT_ACCEPTED"]'::jsonb
    OR (NEW.source_scope='SHARED_OR_ORG_UNEXPOSED_NOT_POSTABLE' AND NOT held @> '["ORG_UNEXPOSED_NOT_POSTABLE"]'::jsonb) THEN
  RAISE EXCEPTION 'DOCUMENT_SOURCE_HOLDS';
 END IF;
 SELECT * INTO policy FROM document_source_revision WHERE namespace=NEW.namespace ORDER BY id LIMIT 1;
 IF FOUND AND (NEW.organization_sha256 IS DISTINCT FROM policy.organization_sha256
    OR NEW.period_start IS DISTINCT FROM policy.period_start OR NEW.period_end IS DISTINCT FROM policy.period_end
    OR NEW.entity_scopes_sha256 IS DISTINCT FROM policy.entity_scopes_sha256
    OR NEW.entity_scopes_text IS DISTINCT FROM policy.entity_scopes_text) THEN
  RAISE EXCEPTION 'DOCUMENT_NAMESPACE_CONTEXT';
 END IF;
 SELECT * INTO prior FROM document_source_revision
  WHERE namespace=NEW.namespace AND entity=NEW.entity AND source_guid=NEW.source_guid
  ORDER BY revision_no DESC LIMIT 1;
 IF FOUND THEN
  IF NEW.revision_no IS DISTINCT FROM prior.revision_no+1 OR NEW.previous_sha IS DISTINCT FROM prior.source_sha
     OR NEW.source_scope IS DISTINCT FROM prior.source_scope OR NEW.source_sha=prior.source_sha THEN
   RAISE EXCEPTION 'DOCUMENT_REVISION_CHAIN';
  END IF;
  IF NOT held @> prior.holds::jsonb THEN RAISE EXCEPTION 'DOCUMENT_SOURCE_HOLDS'; END IF;
 ELSE
  IF NEW.revision_no IS DISTINCT FROM 1 OR NEW.previous_sha IS NOT NULL THEN
   RAISE EXCEPTION 'DOCUMENT_REVISION_CHAIN';
  END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM document_source_revision WHERE namespace=NEW.namespace
     AND entity=NEW.entity AND source_guid=NEW.source_guid AND data_version=NEW.data_version) THEN
  RAISE EXCEPTION 'DOCUMENT_VERSION_REUSED';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_document_source_revision BEFORE INSERT OR UPDATE OR DELETE
 ON document_source_revision FOR EACH ROW EXECUTE FUNCTION guard_document_source_revision();
CREATE TRIGGER no_truncate_document_source_revision BEFORE TRUNCATE ON document_source_revision
 FOR EACH STATEMENT EXECUTE FUNCTION guard_document_source_revision();
"""


def upgrade():
    op.execute(DDL)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM document_source_revision) THEN
        RAISE EXCEPTION 'DOCUMENT_PRESERVED_HISTORY_NO_DOWNGRADE';
      END IF;
    END $$;
    DROP TABLE document_source_revision;
    DROP FUNCTION guard_document_source_revision();""")
