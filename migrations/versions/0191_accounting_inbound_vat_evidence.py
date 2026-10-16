"""Attach private immutable files to exact VAT-only receipt correction revisions."""
from alembic import op

revision = "0191"
down_revision = "0190"
branch_labels = None
depends_on = None


SQL = r"""
CREATE TABLE accounting.inbound_vat_evidence_file (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  receipt_id INTEGER NOT NULL,
  receipt_version INTEGER NOT NULL,
  kind VARCHAR(32) NOT NULL,
  tax_period VARCHAR(7) NOT NULL,
  reference VARCHAR(160) NOT NULL,
  filename VARCHAR(160) NOT NULL,
  content_type VARCHAR(120) NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 VARCHAR(64) NOT NULL,
  storage_filename VARCHAR(80) NOT NULL,
  evidence VARCHAR(2000) NOT NULL,
  request_key VARCHAR(36) NOT NULL,
  supersedes_id INTEGER,
  request_digest VARCHAR(64) NOT NULL,
  digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_inbound_vat_evidence_request UNIQUE (organization_id, request_key),
  CONSTRAINT uq_inbound_vat_evidence_org_id UNIQUE (organization_id, id),
  CONSTRAINT uq_inbound_vat_evidence_successor UNIQUE (supersedes_id),
  CONSTRAINT fk_inbound_vat_evidence_receipt
    FOREIGN KEY (receipt_id) REFERENCES procurement.receipt_document(id),
  CONSTRAINT fk_inbound_vat_evidence_receipt_revision
    FOREIGN KEY (receipt_id, receipt_version)
    REFERENCES procurement.receipt_revision(receipt_id, version),
  CONSTRAINT fk_inbound_vat_evidence_supersedes_org
    FOREIGN KEY (organization_id, supersedes_id)
    REFERENCES accounting.inbound_vat_evidence_file(organization_id, id),
  CONSTRAINT inbound_vat_evidence_kind
    CHECK (kind IN ('supplier_eschf_xml', 'supporting_document_pdf')),
  CONSTRAINT inbound_vat_evidence_positive_version CHECK (receipt_version > 0),
  CONSTRAINT inbound_vat_evidence_tax_period
    CHECK (tax_period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  CONSTRAINT inbound_vat_evidence_size CHECK (size_bytes > 0 AND size_bytes <= 10485760),
  CONSTRAINT inbound_vat_evidence_sha256 CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  CONSTRAINT inbound_vat_evidence_request_key
    CHECK (request_key = (request_key::uuid)::text),
  CONSTRAINT inbound_vat_evidence_request_digest CHECK (request_digest ~ '^[a-f0-9]{64}$'),
  CONSTRAINT inbound_vat_evidence_digest CHECK (digest ~ '^[a-f0-9]{64}$'),
  CONSTRAINT inbound_vat_evidence_actor CHECK (length(btrim(actor)) > 0),
  CONSTRAINT inbound_vat_evidence_reference CHECK (length(btrim(reference)) > 0),
  CONSTRAINT inbound_vat_evidence_filename CHECK (
    length(btrim(filename)) > 0 AND filename !~ '[/\\\r\n]'
  ),
  CONSTRAINT inbound_vat_evidence_content_type CHECK (
    (kind = 'supplier_eschf_xml' AND content_type IN ('application/xml', 'text/xml')
       AND filename ~* '\.xml$'
       AND storage_filename = replace(request_key, '-', '') || '.xml')
    OR (kind = 'supporting_document_pdf' AND content_type = 'application/pdf'
       AND filename ~* '\.pdf$'
       AND storage_filename = replace(request_key, '-', '') || '.pdf')
  ),
  CONSTRAINT inbound_vat_evidence_storage_filename
    CHECK (storage_filename ~ '^[a-f0-9]{32}\.(xml|pdf)$'),
  CONSTRAINT inbound_vat_evidence_evidence CHECK (length(btrim(evidence)) >= 10)
);
CREATE INDEX ix_inbound_vat_evidence_scope
  ON accounting.inbound_vat_evidence_file
  (organization_id, receipt_id, receipt_version, kind, id);

CREATE FUNCTION accounting.guard_inbound_vat_evidence_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE correction procurement.receipt_document%ROWTYPE;
DECLARE original procurement.receipt_document%ROWTYPE;
DECLARE original_posting procurement.receipt_posting%ROWTYPE;
DECLARE previous accounting.inbound_vat_evidence_file%ROWTYPE;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Inbound VAT evidence organization is unavailable';
  END IF;

  SELECT * INTO correction FROM procurement.receipt_document
    WHERE id = NEW.receipt_id FOR UPDATE;
  IF correction.id IS NULL OR correction.organization_id IS DISTINCT FROM NEW.organization_id
     OR correction.status <> 'draft' OR correction.current_version <> NEW.receipt_version
     OR correction.correction_of_receipt_id IS NULL
     OR correction.correction_of_version IS NULL OR correction.correction_of_entry_id IS NULL
     OR correction.correction_of_receipt_id = correction.id
     OR EXISTS (SELECT 1 FROM procurement.receipt_posting p WHERE p.receipt_id=correction.id) THEN
    RAISE EXCEPTION 'Inbound VAT evidence must bind the exact current correction draft revision';
  END IF;

  SELECT * INTO original FROM procurement.receipt_document
    WHERE id=correction.correction_of_receipt_id FOR UPDATE;
  SELECT * INTO original_posting FROM procurement.receipt_posting
    WHERE receipt_id=correction.correction_of_receipt_id;
  IF original.id IS NULL OR original.organization_id IS DISTINCT FROM NEW.organization_id
     OR original.correction_of_receipt_id IS NOT NULL
     OR original.current_version IS DISTINCT FROM correction.correction_of_version
     OR original_posting.receipt_id IS NULL
     OR original_posting.version IS DISTINCT FROM correction.correction_of_version
     OR original_posting.entry_id IS DISTINCT FROM correction.correction_of_entry_id
     OR NOT EXISTS (SELECT 1 FROM procurement.receipt_revision r
       WHERE r.receipt_id=original.id AND r.version=correction.correction_of_version)
     OR NOT EXISTS (SELECT 1 FROM accounting.entry e
       WHERE e.id=correction.correction_of_entry_id AND e.organization_id=NEW.organization_id
         AND e.source='procurement:receipt:'||original.id::text
         AND e.source_version=correction.correction_of_version
         AND e.operation='inventory_purchase' AND e.correction_of IS NULL) THEN
    RAISE EXCEPTION 'Inbound VAT evidence correction source identity is stale or inconsistent';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period p
      WHERE p.organization_id=NEW.organization_id AND p.month=NEW.tax_period AND p.closed) THEN
    RAISE EXCEPTION 'Inbound VAT evidence cannot be added to a closed tax period';
  END IF;

  IF NEW.supersedes_id IS NULL THEN
    IF EXISTS (SELECT 1 FROM accounting.inbound_vat_evidence_file f
        WHERE f.organization_id=NEW.organization_id
          AND f.receipt_id=NEW.receipt_id
          AND f.receipt_version=NEW.receipt_version
          AND f.kind=NEW.kind) THEN
      RAISE EXCEPTION 'Inbound VAT evidence cannot start a parallel chain';
    END IF;
  ELSE
    SELECT * INTO previous FROM accounting.inbound_vat_evidence_file
      WHERE id=NEW.supersedes_id FOR UPDATE;
    IF previous.id IS NULL OR previous.organization_id IS DISTINCT FROM NEW.organization_id
       OR previous.receipt_id IS DISTINCT FROM NEW.receipt_id
       OR previous.receipt_version IS DISTINCT FROM NEW.receipt_version
       OR previous.kind IS DISTINCT FROM NEW.kind
       OR EXISTS (SELECT 1 FROM accounting.inbound_vat_evidence_file f
         WHERE f.supersedes_id=previous.id) THEN
      RAISE EXCEPTION 'Inbound VAT evidence must supersede the latest file in the same chain';
    END IF;
  END IF;

  IF NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.sha256 !~ '^[a-f0-9]{64}$'
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) IS DISTINCT FROM 'object'
     OR length(btrim(NEW.reference)) = 0
     OR length(btrim(NEW.filename)) = 0
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) = 0 THEN
    RAISE EXCEPTION 'Inbound VAT evidence metadata is invalid';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inbound_vat_evidence_insert
  BEFORE INSERT ON accounting.inbound_vat_evidence_file
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_inbound_vat_evidence_insert();

CREATE FUNCTION accounting.reject_inbound_vat_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Inbound VAT evidence file history is immutable';
END $$;
CREATE TRIGGER immutable_inbound_vat_evidence
  BEFORE UPDATE OR DELETE ON accounting.inbound_vat_evidence_file
  FOR EACH ROW EXECUTE FUNCTION accounting.reject_inbound_vat_evidence_mutation();
CREATE TRIGGER no_truncate_inbound_vat_evidence
  BEFORE TRUNCATE ON accounting.inbound_vat_evidence_file
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inbound_vat_evidence_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inbound_vat_evidence_file) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable inbound VAT evidence file history';
      END IF;
    END $$;
    DROP TABLE accounting.inbound_vat_evidence_file;
    DROP FUNCTION accounting.guard_inbound_vat_evidence_insert();
    DROP FUNCTION accounting.reject_inbound_vat_evidence_mutation();
    """)
