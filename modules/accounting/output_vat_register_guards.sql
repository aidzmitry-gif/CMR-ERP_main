-- Proposal-only PostgreSQL guards for the accrued-output-VAT register.

CREATE OR REPLACE FUNCTION accounting.reject_output_vat_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Output VAT register history is immutable';
END;
$$;

CREATE TRIGGER output_vat_register_immutable
BEFORE UPDATE OR DELETE ON accounting.output_vat_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_output_vat_register_mutation();

CREATE TRIGGER output_vat_register_no_truncate
BEFORE TRUNCATE ON accounting.output_vat_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_output_vat_register_mutation();

CREATE OR REPLACE FUNCTION accounting.check_output_vat_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id = NEW.entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id = NEW.line_id;
  IF e.organization_id <> NEW.organization_id OR l.entry_id <> e.id
     OR NEW.source <> e.source OR NEW.source_version <> e.source_version
     OR NEW.entry_digest <> e.digest OR NEW.posting_date <> e.posting_date
     OR l.account_code !~ '^90[.]2([.]|$)' OR l.side <> 'debit' OR l.amount <> NEW.amount
     OR l.currency <> NEW.currency THEN
    RAISE EXCEPTION 'Output VAT register source does not match its posted 90.2 line';
  END IF;
  IF NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' THEN
    RAISE EXCEPTION 'Invalid output VAT tax period';
  END IF;
  IF NEW.eschf_status = 'provided' AND nullif(btrim(NEW.eschf_identifier), '') IS NULL THEN
    RAISE EXCEPTION 'Provided ЭСЧФ requires an identifier';
  END IF;
  IF NEW.eschf_status <> 'provided' AND NEW.eschf_identifier IS NOT NULL THEN
    RAISE EXCEPTION 'ЭСЧФ identifier requires provided status';
  END IF;
  IF NEW.tax_treatment = 'zero_export' AND nullif(btrim(NEW.export_evidence), '') IS NULL THEN
    RAISE EXCEPTION 'Zero-export treatment requires export evidence';
  END IF;
  IF NEW.tax_treatment <> 'zero_export' AND NEW.export_evidence IS NOT NULL THEN
    RAISE EXCEPTION 'Export evidence is allowed only for zero-export treatment';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER output_vat_register_source_consistency
AFTER INSERT ON accounting.output_vat_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_output_vat_register_source();
