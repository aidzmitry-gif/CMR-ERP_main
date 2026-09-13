-- Opening-import evidence is immutable and must point to the exact opening entries.
CREATE OR REPLACE FUNCTION accounting.guard_opening_import_receipt_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE invalid_entries integer;
BEGIN
  IF NEW.cutover_date <> date_trunc('month', NEW.cutover_date)::date
     OR NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.source_digest !~ '^[0-9a-f]{64}$'
     OR NEW.command_digest !~ '^[0-9a-f]{64}$'
     OR NEW.digest !~ '^[0-9a-f]{64}$'
     OR NEW.entry_count <= 0
     OR NEW.line_count < NEW.entry_count
     OR NEW.debit_total < 0
     OR NEW.credit_total < 0
     OR NEW.debit_total <> NEW.credit_total
     OR jsonb_typeof(NEW.entry_ids::jsonb) <> 'array'
     OR jsonb_array_length(NEW.entry_ids::jsonb) <> NEW.entry_count
     OR jsonb_typeof(NEW.snapshot::jsonb) <> 'object'
     OR length(btrim(NEW.evidence)) < 10 THEN
    RAISE EXCEPTION 'Opening import receipt has invalid control metadata';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.entry_ids::jsonb) item
    WHERE jsonb_typeof(item) <> 'number'
  ) THEN
    RAISE EXCEPTION 'Opening import receipt entry ids must be numeric';
  END IF;
  SELECT count(*) INTO invalid_entries
  FROM jsonb_array_elements_text(NEW.entry_ids::jsonb) ids(value)
  LEFT JOIN accounting.entry e ON e.id = ids.value::bigint
  WHERE e.id IS NULL
     OR e.organization_id <> NEW.organization_id
     OR NOT e.opening
     OR e.posting_date <> NEW.cutover_date;
  IF invalid_entries <> 0 THEN
    RAISE EXCEPTION 'Opening import receipt must reference same-organization opening entries';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION accounting.guard_opening_import_receipt_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Opening import receipts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS opening_import_receipt_insert_guard ON accounting.opening_import_receipt;
CREATE CONSTRAINT TRIGGER opening_import_receipt_insert_guard
AFTER INSERT ON accounting.opening_import_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_opening_import_receipt_insert();

DROP TRIGGER IF EXISTS opening_import_receipt_update_guard ON accounting.opening_import_receipt;
CREATE TRIGGER opening_import_receipt_update_guard
BEFORE UPDATE OR DELETE ON accounting.opening_import_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_opening_import_receipt_immutable();
