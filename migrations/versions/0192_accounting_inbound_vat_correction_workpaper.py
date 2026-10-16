"""Append review-only workpapers for VAT-only receipt corrections."""
from alembic import op

revision = "0192"
down_revision = "0191"
branch_labels = None
depends_on = None


SQL = r"""
-- This classifier compares document projections only. It performs no VAT
-- arithmetic and stores no delta or posting direction.
CREATE OR REPLACE FUNCTION accounting.receipt_correction_projection(document jsonb, include_vat boolean)
RETURNS jsonb LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT jsonb_build_object(
    'header', document - 'items' - 'explanation',
    'items', COALESCE((
      SELECT jsonb_agg(projected.item ORDER BY projected.item::text)
      FROM (
        SELECT CASE WHEN include_vat THEN value
          ELSE value - 'vat_rate' - 'vat_amount' - 'vat_basis' END AS item
        FROM jsonb_array_elements(document->'items') AS items(value)
      ) AS projected
    ), '[]'::jsonb)
  )
$$;

CREATE OR REPLACE FUNCTION accounting.receipt_correction_is_vat_only(original_document jsonb, corrected_document jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT accounting.receipt_correction_projection(original_document, false)
           = accounting.receipt_correction_projection(corrected_document, false)
     AND accounting.receipt_correction_projection(original_document, true)
           IS DISTINCT FROM accounting.receipt_correction_projection(corrected_document, true)
$$;

CREATE TABLE accounting.inbound_vat_correction_workpaper (
  id SERIAL PRIMARY KEY,
  organization_id INTEGER NOT NULL REFERENCES accounting.organization(id),
  receipt_id INTEGER NOT NULL REFERENCES procurement.receipt_document(id),
  receipt_version INTEGER NOT NULL,
  correction_revision_id INTEGER NOT NULL REFERENCES procurement.receipt_revision(id),
  original_receipt_id INTEGER NOT NULL REFERENCES procurement.receipt_document(id),
  original_version INTEGER NOT NULL,
  original_revision_id INTEGER NOT NULL REFERENCES procurement.receipt_revision(id),
  source_entry_id INTEGER NOT NULL REFERENCES accounting.entry(id),
  source_entry_digest VARCHAR(64) NOT NULL,
  tax_period VARCHAR(7) NOT NULL,
  revision INTEGER NOT NULL,
  supersedes_id INTEGER,
  request_key VARCHAR(36) NOT NULL,
  request_digest VARCHAR(64) NOT NULL,
  basis_digest VARCHAR(64) NOT NULL,
  snapshot_digest VARCHAR(64) NOT NULL,
  snapshot JSONB NOT NULL,
  reviewer_evidence VARCHAR(2000) NOT NULL,
  actor VARCHAR(200) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_inbound_vat_correction_workpaper_request
    UNIQUE (organization_id, request_key),
  CONSTRAINT uq_inbound_vat_correction_workpaper_org_id
    UNIQUE (organization_id, id),
  CONSTRAINT uq_inbound_vat_correction_workpaper_revision
    UNIQUE (organization_id, receipt_id, receipt_version, tax_period, revision),
  CONSTRAINT uq_inbound_vat_correction_workpaper_successor UNIQUE (supersedes_id),
  CONSTRAINT fk_inbound_vat_workpaper_supersedes_org
    FOREIGN KEY (organization_id, supersedes_id)
    REFERENCES accounting.inbound_vat_correction_workpaper(organization_id, id),
  CONSTRAINT fk_inbound_vat_workpaper_correction_revision
    FOREIGN KEY (receipt_id, receipt_version)
    REFERENCES procurement.receipt_revision(receipt_id, version),
  CONSTRAINT fk_inbound_vat_workpaper_original_revision
    FOREIGN KEY (original_receipt_id, original_version)
    REFERENCES procurement.receipt_revision(receipt_id, version),
  CONSTRAINT inbound_vat_correction_workpaper_positive_versions
    CHECK (receipt_version > 0 AND original_version > 0 AND revision > 0),
  CONSTRAINT inbound_vat_correction_workpaper_tax_period
    CHECK (tax_period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$' AND left(tax_period, 4) <> '0000'),
  CONSTRAINT inbound_vat_correction_workpaper_digests
    CHECK (source_entry_digest ~ '^[a-f0-9]{64}$'
      AND request_digest ~ '^[a-f0-9]{64}$'
      AND basis_digest ~ '^[a-f0-9]{64}$'
      AND snapshot_digest ~ '^[a-f0-9]{64}$'),
  CONSTRAINT inbound_vat_correction_workpaper_request_key
    CHECK (request_key = (request_key::uuid)::text),
  CONSTRAINT inbound_vat_correction_workpaper_snapshot
    CHECK (jsonb_typeof(snapshot) = 'object'
      AND jsonb_typeof(snapshot->'source_account_18_lines') = 'array'
      AND jsonb_typeof(snapshot->'evidence_files') = 'array'),
  CONSTRAINT inbound_vat_correction_workpaper_evidence
    CHECK (length(btrim(reviewer_evidence)) >= 10 AND length(btrim(actor)) > 0)
);
CREATE INDEX ix_inbound_vat_correction_workpaper_scope
  ON accounting.inbound_vat_correction_workpaper
    (organization_id, receipt_id, receipt_version, tax_period, revision DESC);

CREATE FUNCTION accounting.guard_inbound_vat_correction_workpaper_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE correction procurement.receipt_document%ROWTYPE;
DECLARE original procurement.receipt_document%ROWTYPE;
DECLARE posted procurement.receipt_posting%ROWTYPE;
DECLARE correction_revision procurement.receipt_revision%ROWTYPE;
DECLARE original_revision procurement.receipt_revision%ROWTYPE;
DECLARE source_entry accounting.entry%ROWTYPE;
DECLARE previous accounting.inbound_vat_correction_workpaper%ROWTYPE;
DECLARE source_line accounting.line%ROWTYPE;
DECLARE evidence_file accounting.inbound_vat_evidence_file%ROWTYPE;
DECLARE line_item jsonb;
DECLARE evidence_item jsonb;
DECLARE actual_count integer;
DECLARE distinct_count integer;
BEGIN
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Inbound VAT workpaper organization is unavailable';
  END IF;

  SELECT * INTO correction FROM procurement.receipt_document
    WHERE id=NEW.receipt_id FOR UPDATE;
  IF correction.id IS NULL OR correction.organization_id IS DISTINCT FROM NEW.organization_id
     OR correction.status <> 'draft' OR correction.current_version IS DISTINCT FROM NEW.receipt_version
     OR correction.correction_of_receipt_id IS DISTINCT FROM NEW.original_receipt_id
     OR correction.correction_of_version IS DISTINCT FROM NEW.original_version
     OR correction.correction_of_entry_id IS DISTINCT FROM NEW.source_entry_id
     OR correction.id=NEW.original_receipt_id
     OR EXISTS (SELECT 1 FROM procurement.receipt_posting p WHERE p.receipt_id=correction.id) THEN
    RAISE EXCEPTION 'Inbound VAT workpaper must bind the exact current correction draft revision';
  END IF;

  SELECT * INTO original FROM procurement.receipt_document
    WHERE id=NEW.original_receipt_id FOR UPDATE;
  SELECT * INTO posted FROM procurement.receipt_posting WHERE receipt_id=NEW.original_receipt_id;
  SELECT * INTO correction_revision FROM procurement.receipt_revision
    WHERE id=NEW.correction_revision_id AND receipt_id=NEW.receipt_id AND version=NEW.receipt_version;
  SELECT * INTO original_revision FROM procurement.receipt_revision
    WHERE id=NEW.original_revision_id AND receipt_id=NEW.original_receipt_id AND version=NEW.original_version;
  SELECT * INTO source_entry FROM accounting.entry
    WHERE id=NEW.source_entry_id AND organization_id=NEW.organization_id;
  IF original.id IS NULL OR original.organization_id IS DISTINCT FROM NEW.organization_id
     OR original.correction_of_receipt_id IS NOT NULL
     OR original.current_version IS DISTINCT FROM NEW.original_version
     OR posted.receipt_id IS NULL OR posted.version IS DISTINCT FROM NEW.original_version
     OR posted.entry_id IS DISTINCT FROM NEW.source_entry_id
     OR correction_revision.id IS NULL OR original_revision.id IS NULL
     OR source_entry.id IS NULL OR source_entry.operation <> 'inventory_purchase'
     OR source_entry.source <> 'procurement:receipt:'||NEW.original_receipt_id::text
     OR source_entry.source_version IS DISTINCT FROM NEW.original_version
     OR source_entry.correction_of IS NOT NULL
     OR source_entry.digest IS DISTINCT FROM NEW.source_entry_digest
     OR NOT accounting.receipt_correction_is_vat_only(
          original_revision.document::jsonb, correction_revision.document::jsonb) THEN
    RAISE EXCEPTION 'Inbound VAT workpaper source or VAT-only correction identity is stale or inconsistent';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period p
      WHERE p.organization_id=NEW.organization_id AND p.month=NEW.tax_period AND p.closed) THEN
    RAISE EXCEPTION 'Inbound VAT workpaper cannot be revised in a closed tax period';
  END IF;

  IF NEW.snapshot->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
     OR NEW.snapshot->'receipt'->>'correction_receipt_id' IS DISTINCT FROM NEW.receipt_id::text
     OR NEW.snapshot->'receipt'->>'correction_version' IS DISTINCT FROM NEW.receipt_version::text
     OR NEW.snapshot->'receipt'->>'correction_revision_id' IS DISTINCT FROM NEW.correction_revision_id::text
     OR NEW.snapshot->'receipt'->>'original_receipt_id' IS DISTINCT FROM NEW.original_receipt_id::text
     OR NEW.snapshot->'receipt'->>'original_version' IS DISTINCT FROM NEW.original_version::text
     OR NEW.snapshot->'receipt'->>'original_revision_id' IS DISTINCT FROM NEW.original_revision_id::text
     OR NEW.snapshot->'receipt'->>'source_entry_id' IS DISTINCT FROM NEW.source_entry_id::text
     OR NEW.snapshot->'receipt'->>'source_entry_digest' IS DISTINCT FROM NEW.source_entry_digest
     OR NEW.snapshot->'receipt'->>'source_entry' IS DISTINCT FROM source_entry.source
     OR NEW.snapshot->'receipt'->>'source_version' IS DISTINCT FROM source_entry.source_version::text
     OR COALESCE(NEW.snapshot->'receipt'->>'correction_document_digest', '') !~ '^[a-f0-9]{64}$'
     OR COALESCE(NEW.snapshot->'receipt'->>'original_document_digest', '') !~ '^[a-f0-9]{64}$'
     OR encode(sha256(convert_to(procurement.order_command_json(correction_revision.document::jsonb), 'UTF8')), 'hex')
          IS DISTINCT FROM NEW.snapshot->'receipt'->>'correction_document_digest'
     OR encode(sha256(convert_to(procurement.order_command_json(original_revision.document::jsonb), 'UTF8')), 'hex')
          IS DISTINCT FROM NEW.snapshot->'receipt'->>'original_document_digest'
     OR NEW.snapshot->>'tax_period' IS DISTINCT FROM NEW.tax_period
     OR NEW.snapshot->'classification' IS DISTINCT FROM '["vat_change"]'::jsonb
     OR NEW.snapshot->>'review_only' IS DISTINCT FROM 'true'
     OR NEW.snapshot->>'signature_verified' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'document_facts_verified' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'deduction_eligibility_assessed' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'accountant_accepted' IS DISTINCT FROM 'false'
     OR NEW.snapshot->>'posting_available' IS DISTINCT FROM 'false'
     OR NEW.snapshot ?| ARRAY['vat_delta','delta','debit','credit','side']
     OR NEW.request_key IS DISTINCT FROM (NEW.request_key::uuid)::text
     OR NEW.request_digest !~ '^[a-f0-9]{64}$'
     OR NEW.basis_digest !~ '^[a-f0-9]{64}$'
     OR NEW.snapshot_digest !~ '^[a-f0-9]{64}$'
     OR jsonb_typeof(NEW.snapshot) IS DISTINCT FROM 'object'
     OR length(btrim(NEW.reviewer_evidence)) < 10 OR length(btrim(NEW.actor))=0 THEN
    RAISE EXCEPTION 'Inbound VAT workpaper immutable review evidence is invalid';
  END IF;

  SELECT count(*) INTO actual_count FROM accounting.line l
    WHERE l.entry_id=NEW.source_entry_id
      AND (l.account_code='18' OR l.account_code LIKE '18.%');
  SELECT count(DISTINCT (value->>'line_id')::integer) INTO distinct_count
    FROM jsonb_array_elements(NEW.snapshot->'source_account_18_lines');
  IF actual_count <> jsonb_array_length(NEW.snapshot->'source_account_18_lines')
     OR actual_count <> distinct_count OR actual_count=0 THEN
    RAISE EXCEPTION 'Inbound VAT workpaper must snapshot at least one exact account-18 source line once';
  END IF;
  FOR line_item IN SELECT value FROM jsonb_array_elements(NEW.snapshot->'source_account_18_lines') LOOP
    IF line_item ?| ARRAY['side','debit','credit','vat_delta','delta']
       OR (line_item->>'line_id') !~ '^[0-9]+$' THEN
      RAISE EXCEPTION 'Inbound VAT workpaper account-18 line snapshot contains prohibited direction or delta data';
    END IF;
    SELECT * INTO source_line FROM accounting.line
      WHERE id=(line_item->>'line_id')::integer AND entry_id=NEW.source_entry_id;
    IF source_line.id IS NULL
       OR (source_line.account_code <> '18' AND source_line.account_code NOT LIKE '18.%')
       OR line_item->>'account_code' IS DISTINCT FROM source_line.account_code
       OR line_item->>'account_id' IS DISTINCT FROM source_line.account_id::text
       OR line_item->>'account_title' IS DISTINCT FROM source_line.account_title
       OR line_item->>'category' IS DISTINCT FROM source_line.category
       OR line_item->>'cash' IS DISTINCT FROM source_line.cash::text
       OR line_item->>'amount' IS DISTINCT FROM source_line.amount::text
       OR line_item->>'currency' IS DISTINCT FROM source_line.currency
       OR line_item->'dimensions' IS DISTINCT FROM source_line.dimensions::jsonb THEN
      RAISE EXCEPTION 'Inbound VAT workpaper account-18 line snapshot differs from the source entry';
    END IF;
  END LOOP;

  SELECT count(*) INTO actual_count FROM accounting.inbound_vat_evidence_file f
    WHERE f.organization_id=NEW.organization_id AND f.receipt_id=NEW.receipt_id
      AND f.receipt_version=NEW.receipt_version
      AND NOT EXISTS (SELECT 1 FROM accounting.inbound_vat_evidence_file successor
        WHERE successor.supersedes_id=f.id);
  SELECT count(DISTINCT (value->>'file_id')::integer) INTO distinct_count
    FROM jsonb_array_elements(NEW.snapshot->'evidence_files');
  IF actual_count <> jsonb_array_length(NEW.snapshot->'evidence_files')
     OR actual_count <> distinct_count OR actual_count=0 THEN
    RAISE EXCEPTION 'Inbound VAT workpaper must bind at least one current correction evidence file once';
  END IF;
  FOR evidence_item IN SELECT value FROM jsonb_array_elements(NEW.snapshot->'evidence_files') LOOP
    IF (evidence_item->>'file_id') !~ '^[0-9]+$' THEN
      RAISE EXCEPTION 'Inbound VAT workpaper evidence identity is invalid';
    END IF;
    SELECT * INTO evidence_file FROM accounting.inbound_vat_evidence_file
      WHERE id=(evidence_item->>'file_id')::integer;
    IF evidence_file.id IS NULL OR evidence_file.organization_id IS DISTINCT FROM NEW.organization_id
       OR evidence_file.receipt_id IS DISTINCT FROM NEW.receipt_id
       OR evidence_file.receipt_version IS DISTINCT FROM NEW.receipt_version
       OR evidence_file.tax_period IS DISTINCT FROM NEW.tax_period
       OR evidence_item->>'receipt_id' IS DISTINCT FROM evidence_file.receipt_id::text
       OR evidence_item->>'receipt_version' IS DISTINCT FROM evidence_file.receipt_version::text
       OR evidence_item->>'tax_period' IS DISTINCT FROM evidence_file.tax_period
       OR evidence_item->>'kind' IS DISTINCT FROM evidence_file.kind
       OR evidence_item->>'reference' IS DISTINCT FROM evidence_file.reference
       OR evidence_item->>'filename' IS DISTINCT FROM evidence_file.filename
       OR evidence_item->>'content_type' IS DISTINCT FROM evidence_file.content_type
       OR evidence_item->>'digest' IS DISTINCT FROM evidence_file.digest
       OR evidence_item->>'sha256' IS DISTINCT FROM evidence_file.sha256
       OR evidence_item->>'size_bytes' IS DISTINCT FROM evidence_file.size_bytes::text
       OR EXISTS (SELECT 1 FROM accounting.inbound_vat_evidence_file successor
          WHERE successor.supersedes_id=evidence_file.id) THEN
      RAISE EXCEPTION 'Inbound VAT workpaper evidence differs from current scoped file receipts';
    END IF;
  END LOOP;

  SELECT * INTO previous FROM accounting.inbound_vat_correction_workpaper
    WHERE organization_id=NEW.organization_id AND receipt_id=NEW.receipt_id
      AND receipt_version=NEW.receipt_version AND tax_period=NEW.tax_period
    ORDER BY revision DESC LIMIT 1 FOR UPDATE;
  IF previous.id IS NULL THEN
    IF NEW.revision <> 1 OR NEW.supersedes_id IS NOT NULL THEN
      RAISE EXCEPTION 'First inbound VAT workpaper must start at revision one';
    END IF;
  ELSIF NEW.revision <> previous.revision+1 OR NEW.supersedes_id IS DISTINCT FROM previous.id THEN
    RAISE EXCEPTION 'Inbound VAT workpaper must supersede its latest same-scope revision';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_inbound_vat_correction_workpaper_insert
  BEFORE INSERT ON accounting.inbound_vat_correction_workpaper
  FOR EACH ROW EXECUTE FUNCTION accounting.guard_inbound_vat_correction_workpaper_insert();

CREATE FUNCTION accounting.reject_inbound_vat_correction_workpaper_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  RAISE EXCEPTION 'Inbound VAT correction workpaper history is immutable';
END $$;
CREATE TRIGGER immutable_inbound_vat_correction_workpaper
  BEFORE UPDATE OR DELETE ON accounting.inbound_vat_correction_workpaper
  FOR EACH ROW EXECUTE FUNCTION accounting.reject_inbound_vat_correction_workpaper_mutation();
CREATE TRIGGER no_truncate_inbound_vat_correction_workpaper
  BEFORE TRUNCATE ON accounting.inbound_vat_correction_workpaper
  FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_inbound_vat_correction_workpaper_mutation();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inbound_vat_correction_workpaper) THEN
        RAISE EXCEPTION 'Cannot downgrade immutable inbound VAT workpaper history';
      END IF;
    END $$;
    DROP TABLE accounting.inbound_vat_correction_workpaper;
    DROP FUNCTION accounting.guard_inbound_vat_correction_workpaper_insert();
    DROP FUNCTION accounting.reject_inbound_vat_correction_workpaper_mutation();
    DROP FUNCTION accounting.receipt_correction_is_vat_only(jsonb, jsonb);
    DROP FUNCTION accounting.receipt_correction_projection(jsonb, boolean);
    """)
