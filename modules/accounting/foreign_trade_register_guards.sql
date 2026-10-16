-- Proposal-only PostgreSQL guards for the explicit import/export register.
CREATE OR REPLACE FUNCTION accounting.reject_foreign_trade_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Foreign-trade register history is immutable';
END $$;

CREATE TRIGGER immutable_foreign_trade_register
BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.foreign_trade_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_foreign_trade_register_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_foreign_trade_register_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  SELECT * INTO l FROM accounting.line WHERE id=NEW.line_id;
  IF NOT FOUND OR e.id IS DISTINCT FROM NEW.entry_id OR l.entry_id IS DISTINCT FROM NEW.entry_id
     OR e.organization_id IS DISTINCT FROM NEW.organization_id
     OR e.digest IS DISTINCT FROM NEW.entry_digest
     OR e.source IS DISTINCT FROM NEW.source OR e.source_version IS DISTINCT FROM NEW.source_version
     OR l.currency IS DISTINCT FROM NEW.currency OR l.amount IS DISTINCT FROM NEW.amount
     OR NEW.command->>'request_key' IS DISTINCT FROM NEW.request_key
     OR NEW.command->>'entry_id' IS DISTINCT FROM NEW.entry_id::text
     OR NEW.command->>'line_id' IS DISTINCT FROM NEW.line_id::text
     OR NEW.command->>'expected_entry_digest' IS DISTINCT FROM NEW.entry_digest
     OR NEW.command->>'trade_mode' IS DISTINCT FROM NEW.trade_mode
     OR NEW.command->>'tax_period' IS DISTINCT FROM NEW.tax_period THEN
    RAISE EXCEPTION 'Foreign-trade register source does not match its posted line';
  END IF;
  IF NEW.trade_mode NOT IN ('eaeu_import','third_country_import','export')
     OR NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
     OR NEW.amount <= 0 OR NEW.customs_duty < 0 OR NEW.import_vat < 0 THEN
    RAISE EXCEPTION 'Invalid foreign-trade register metadata';
  END IF;
  IF NEW.trade_mode IN ('eaeu_import','third_country_import') AND NEW.incoterms IS NULL THEN
    RAISE EXCEPTION 'Import trade evidence requires Incoterms';
  END IF;
  IF NEW.trade_mode = 'eaeu_import' AND NEW.eaeu_reference IS NULL THEN
    RAISE EXCEPTION 'EAEU trade evidence requires its document reference';
  END IF;
  IF NEW.trade_mode IN ('third_country_import','export') AND NEW.customs_reference IS NULL THEN
    RAISE EXCEPTION 'This trade lane requires a customs reference';
  END IF;
  IF NEW.trade_mode = 'export' AND (NEW.export_evidence IS NULL OR NEW.import_vat <> 0 OR NEW.customs_duty <> 0) THEN
    RAISE EXCEPTION 'Export trade evidence has invalid customs or transport data';
  END IF;
  IF NEW.trade_mode = 'export' THEN
    IF l.side <> 'credit' OR (l.account_code <> '90.1' AND l.account_code NOT LIKE '90.1.%') THEN
      RAISE EXCEPTION 'Export evidence must bind to a credit 90.1 source line';
    END IF;
  ELSIF l.side <> 'debit' OR NOT (l.account_code IN ('10','18','20','41')
         OR l.account_code LIKE '10.%' OR l.account_code LIKE '18.%'
         OR l.account_code LIKE '20.%' OR l.account_code LIKE '41.%') THEN
    RAISE EXCEPTION 'Import evidence must bind to a debit inventory or input-VAT source line';
  END IF;
  IF NEW.currency = 'BYN' THEN
    IF NEW.original_amount IS NOT NULL OR NEW.rate IS NOT NULL OR NEW.rate_scale IS NOT NULL
       OR NEW.rate_date IS NOT NULL OR NEW.rate_source IS NOT NULL
       OR l.original_amount IS NOT NULL OR l.rate IS NOT NULL OR l.rate_scale IS NOT NULL
       OR l.rate_date IS NOT NULL OR l.rate_source IS NOT NULL THEN
      RAISE EXCEPTION 'BYN trade evidence cannot carry FX metadata';
    END IF;
  ELSE
    IF NEW.original_amount IS NULL OR NEW.rate IS NULL OR NEW.rate_scale IS NULL
       OR NEW.rate_date IS NULL OR NEW.rate_source IS NULL
       OR l.original_amount IS DISTINCT FROM NEW.original_amount
       OR l.rate IS DISTINCT FROM NEW.rate OR l.rate_scale IS DISTINCT FROM NEW.rate_scale
       OR l.rate_date IS DISTINCT FROM NEW.rate_date OR l.rate_source IS DISTINCT FROM NEW.rate_source THEN
      RAISE EXCEPTION 'Foreign-currency trade evidence does not match the posted rate source';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE CONSTRAINT TRIGGER foreign_trade_register_insert_guard
AFTER INSERT ON accounting.foreign_trade_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_foreign_trade_register_insert();
