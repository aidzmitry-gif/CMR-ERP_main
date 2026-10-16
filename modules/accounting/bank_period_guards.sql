-- Additive bank completeness protection; register after the joint migration head.
CREATE OR REPLACE FUNCTION accounting.guard_bank_period_close() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.closed THEN
    PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
    IF EXISTS (
      SELECT 1 FROM accounting.source_binding b
      JOIN finance.bank_transaction s ON s.id=b.source_id
      LEFT JOIN accounting.bank_import_receipt r
        ON r.organization_id=b.organization_id AND r.source_transaction_id=s.id
      WHERE b.organization_id=NEW.organization_id AND b.source_type='finance_bank_transaction'
        AND b.ownership='own' AND r.entry_id IS NULL
        AND (s.occurred_on IS NULL OR to_char(s.occurred_on,'YYYY-MM')<=NEW.month)
    ) THEN
      RAISE EXCEPTION 'Unposted imported bank transactions prevent closing';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_period_close_check BEFORE INSERT OR UPDATE ON accounting.period
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_period_close();

CREATE OR REPLACE FUNCTION accounting.guard_bank_source_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_row finance.bank_transaction;
BEGIN
  IF NEW.source_type<>'finance_bank_transaction' THEN RETURN NEW; END IF;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT * INTO source_row FROM finance.bank_transaction WHERE id=NEW.source_id FOR UPDATE;
  IF NOT FOUND OR NEW.ownership<>'own' THEN
    RAISE EXCEPTION 'Bank source binding requires an existing own-company source';
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.period WHERE organization_id=NEW.organization_id AND closed
      AND (source_row.occurred_on IS NULL OR month>=to_char(source_row.occurred_on,'YYYY-MM'))) THEN
    RAISE EXCEPTION 'Bank source affects a closed period';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bank_source_binding_check BEFORE INSERT ON accounting.source_binding
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bank_source_binding();

CREATE OR REPLACE FUNCTION accounting.guard_bound_bank_source_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF ROW(NEW.id,NEW.ext_id,NEW.occurred_on,NEW.amount,NEW.currency,NEW.payer_unp,NEW.payer_name,NEW.purpose,NEW.account_code)
       IS NOT DISTINCT FROM ROW(OLD.id,OLD.ext_id,OLD.occurred_on,OLD.amount,OLD.currency,OLD.payer_unp,OLD.payer_name,OLD.purpose,OLD.account_code)
    THEN RETURN NEW; END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM accounting.source_binding WHERE source_type='finance_bank_transaction' AND source_id=OLD.id) THEN
    RAISE EXCEPTION 'Bound bank source financial fields are immutable';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER bound_bank_source_mutation BEFORE UPDATE OR DELETE ON finance.bank_transaction
FOR EACH ROW EXECUTE FUNCTION accounting.guard_bound_bank_source_mutation();

CREATE OR REPLACE FUNCTION accounting.guard_bound_bank_source_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM accounting.source_binding WHERE source_type='finance_bank_transaction') THEN
    RAISE EXCEPTION 'Bound bank sources cannot be truncated';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER bound_bank_source_truncate BEFORE TRUNCATE ON finance.bank_transaction
FOR EACH STATEMENT EXECUTE FUNCTION accounting.guard_bound_bank_source_truncate();
