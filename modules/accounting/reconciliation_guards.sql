-- An OSV reconciliation receipt is accountant evidence only.  It never
-- creates ledger movements and it is admitted only for two closed, complete,
-- numerically equal normalized reports.
CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_receipt_insert()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.request_key !~ '^[0-9a-fA-F-]{36}$'
     OR NEW.period_from > NEW.period_to
     OR NEW.left_digest !~ '^[0-9a-f]{64}$'
     OR NEW.right_digest !~ '^[0-9a-f]{64}$'
     OR NEW.command_digest !~ '^[0-9a-f]{64}$'
     OR NEW.digest !~ '^[0-9a-f]{64}$'
     OR NEW.left_status <> 'closed_periods'
     OR NEW.right_status <> 'closed_periods'
     OR NEW.left_pending_documents <> 0
     OR NEW.right_pending_documents <> 0
     OR NEW.left_rows < 0
     OR NEW.right_rows < 0
     OR NEW.difference_count <> 0
     OR jsonb_typeof(NEW.snapshot::jsonb) <> 'object'
     OR length(btrim(NEW.evidence)) < 10
     OR length(btrim(NEW.actor)) < 1 THEN
    RAISE EXCEPTION 'Reconciliation receipt is not an eligible closed OSV acceptance';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS reconciliation_receipt_insert_guard ON accounting.reconciliation_receipt;
CREATE CONSTRAINT TRIGGER reconciliation_receipt_insert_guard
AFTER INSERT ON accounting.reconciliation_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION accounting.guard_reconciliation_receipt_insert();

CREATE OR REPLACE FUNCTION accounting.guard_reconciliation_receipt_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'Reconciliation receipts are immutable';
END;
$$;

DROP TRIGGER IF EXISTS reconciliation_receipt_update_guard ON accounting.reconciliation_receipt;
CREATE TRIGGER reconciliation_receipt_update_guard
BEFORE UPDATE OR DELETE ON accounting.reconciliation_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_reconciliation_receipt_immutable();

DROP TRIGGER IF EXISTS reconciliation_receipt_truncate_guard ON accounting.reconciliation_receipt;
CREATE TRIGGER reconciliation_receipt_truncate_guard
BEFORE TRUNCATE ON accounting.reconciliation_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.guard_reconciliation_receipt_immutable();
