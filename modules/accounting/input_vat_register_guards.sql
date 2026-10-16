-- Proposal-only PostgreSQL guards for the explicit input-VAT register.
-- The source document and ledger line are immutable snapshots; no deduction is
-- created by this table.  Do not register this file as a production migration
-- without an operator-assigned migration revision.

CREATE OR REPLACE FUNCTION accounting.reject_input_vat_register_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Input VAT register history is immutable';
END;
$$;

CREATE TRIGGER input_vat_register_immutable
BEFORE UPDATE OR DELETE ON accounting.input_vat_register_entry
FOR EACH ROW EXECUTE FUNCTION accounting.reject_input_vat_register_mutation();

CREATE TRIGGER input_vat_register_no_truncate
BEFORE TRUNCATE ON accounting.input_vat_register_entry
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_input_vat_register_mutation();

CREATE OR REPLACE FUNCTION accounting.check_input_vat_register_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; l accounting.line%ROWTYPE;
BEGIN
  SELECT * INTO STRICT e FROM accounting.entry WHERE id = NEW.entry_id;
  SELECT * INTO STRICT l FROM accounting.line WHERE id = NEW.line_id;
  IF e.organization_id <> NEW.organization_id OR l.entry_id <> e.id
     OR NEW.source <> e.source OR NEW.source_version <> e.source_version
     OR NEW.entry_digest <> e.digest OR NEW.posting_date <> e.posting_date
     OR l.account_code !~ '^18(\.|$)' OR l.amount <> NEW.amount
     OR l.currency <> NEW.currency OR l.side <> NEW.side THEN
    RAISE EXCEPTION 'Input VAT register source does not match its posted line';
  END IF;
  IF NEW.tax_period !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' THEN
    RAISE EXCEPTION 'Invalid input VAT tax period';
  END IF;
  IF NEW.eschf_status = 'provided' AND nullif(btrim(NEW.eschf_identifier), '') IS NULL THEN
    RAISE EXCEPTION 'Provided ЭСЧФ requires an identifier';
  END IF;
  IF NEW.eschf_status <> 'provided' AND NEW.eschf_identifier IS NOT NULL THEN
    RAISE EXCEPTION 'ЭСЧФ identifier requires provided status';
  END IF;
  IF NEW.deduction_status = 'eligible'
     AND NEW.eschf_status NOT IN ('provided', 'not_required') THEN
    RAISE EXCEPTION 'Eligible input VAT requires explicit ЭСЧФ status';
  END IF;
  IF NEW.side = 'credit' AND NEW.deduction_status = 'eligible' THEN
    RAISE EXCEPTION 'Credit input VAT line cannot be eligible';
  END IF;
  RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER input_vat_register_source_consistency
AFTER INSERT ON accounting.input_vat_register_entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.check_input_vat_register_source();
