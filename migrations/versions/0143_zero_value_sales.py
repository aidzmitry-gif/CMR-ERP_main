"""Bind zero-value sale quantity to its real revenue/VAT entry."""
import runpy
from pathlib import Path

from alembic import op

revision = "0143"
down_revision = "0142"
branch_labels = None
depends_on = None


def previous(number, name):
    module = runpy.run_path(str(Path(__file__).with_name(name)))
    return module["DDL"]


def function(ddl, name):
    start = ddl.index(f"CREATE OR REPLACE FUNCTION accounting.{name}(")
    end = ddl.index("END $$;", start) + len("END $$;")
    return ddl[start:end]


def replace_once(value, old, new):
    if value.count(old) != 1:
        raise RuntimeError(f"0143 expected one immutable anchor: {old[:80]}")
    return value.replace(old, new)


def definitions():
    old = previous(140, "0140_zero_value_disposals.py")
    dates = previous(142, "0142_zero_value_command_dates.py")
    register = function(old, "register_inventory_zero_value_disposal")
    register = replace_once(register, "  SELECT pg_get_serial_sequence", """  IF NEW.operation='inventory_sale' THEN
    IF NEW.entry_id IS NULL THEN RAISE EXCEPTION 'Zero sale requires its entry'; END IF;
    IF NOT EXISTS (SELECT 1 FROM accounting.entry WHERE id=NEW.entry_id
        AND organization_id=NEW.organization_id AND operation='inventory_sale') THEN
      RAISE EXCEPTION 'Zero sale entry belongs to another organization or operation';
    END IF;
    NEW.registration_token := NEW.entry_id; RETURN NEW;
  END IF;
  SELECT pg_get_serial_sequence""")
    guard = function(old, "guard_inventory_zero_value_disposal")
    guard = replace_once(guard,
        "NEW.operation IS DISTINCT FROM 'inventory_issue' OR NEW.entry_id IS NOT NULL",
        "(NEW.operation NOT IN ('inventory_issue','inventory_sale')) OR "
        "(NEW.operation='inventory_issue' AND NEW.entry_id IS NOT NULL) OR "
        "(NEW.operation='inventory_sale' AND (NEW.entry_id IS NULL OR NEW.registration_token<>NEW.entry_id))")
    guard = replace_once(guard, "c->>'operation' IS DISTINCT FROM 'inventory_issue'",
                         "c->>'operation' IS DISTINCT FROM NEW.operation")
    guard = replace_once(guard, "e.operation='inventory_issue') THEN",
                         "e.operation=NEW.operation AND e.id IS DISTINCT FROM NEW.entry_id) THEN")
    version = function(dates, "validate_zero_value_disposal_command")
    version = replace_once(version, "BEGIN\n", """BEGIN
  IF c->'command_version'='3'::jsonb THEN
    IF c->>'command_version' IS DISTINCT FROM '3' THEN
      RAISE EXCEPTION 'Zero sale command version must be integer 3';
    END IF;
    IF c->>'operation' IS DISTINCT FROM 'inventory_sale'
       OR jsonb_typeof(c->'sale_document') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'Version three requires a complete sale document';
    END IF;
    c := jsonb_set(c,'{command_version}','2'::jsonb);
  ELSIF c->>'operation'='inventory_sale' THEN
    RAISE EXCEPTION 'Linked zero sale requires version three';
  END IF;
""")
    return register + "\n" + guard + "\n" + version


LINK_DDL = r"""
CREATE OR REPLACE FUNCTION accounting.validate_zero_sale_link(target integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; r accounting.inventory_sale_receipt%ROWTYPE;
 z accounting.inventory_zero_value_disposal_receipt%ROWTYPE; c jsonb; d jsonb; layer jsonb; field text;
 net numeric; vat numeric; gross numeric; metadata jsonb;
BEGIN
 SELECT * INTO e FROM accounting.entry WHERE id=target;
 IF NOT FOUND OR e.operation IS DISTINCT FROM 'inventory_sale' THEN
   IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE entry_id=target) THEN
     RAISE EXCEPTION 'Zero sale references a non-sale entry';
   END IF;
   RETURN;
 END IF;
 SELECT * INTO r FROM accounting.inventory_sale_receipt WHERE entry_id=target;
 SELECT * INTO z FROM accounting.inventory_zero_value_disposal_receipt WHERE entry_id=target;
 IF z.id IS NULL THEN
   IF r.entry_id IS NOT NULL AND ((r.cost->>'issue_cost_byn')::numeric=0
       OR NOT EXISTS (SELECT 1 FROM accounting.line WHERE entry_id=target AND quantity IS NOT NULL)) THEN
     RAISE EXCEPTION 'Zero-cost sale requires its quantity receipt';
   END IF;
   RETURN;
 END IF;
 c:=z.command::jsonb; d:=c->'sale_document'; layer:=c->'inventory_layers'->0;
 IF r.entry_id IS NULL OR z.operation IS DISTINCT FROM 'inventory_sale'
   OR z.organization_id<>e.organization_id OR r.organization_id<>e.organization_id
   OR z.registration_token<>e.id OR z.source<>e.source OR z.source_version<>e.source_version
   OR z.actor<>e.actor OR r.actor<>e.actor OR z.policy_id<>e.policy_id
   OR z.posting_date<>e.posting_date OR c->'command_version' IS DISTINCT FROM '3'::jsonb
   OR r.command::jsonb IS DISTINCT FROM d OR r.digest IS DISTINCT FROM e.digest
   OR (r.cost->>'issue_cost_byn')::numeric IS DISTINCT FROM 0
   OR c->>'document_date' IS DISTINCT FROM e.document_date::text
   OR c->>'operation_date' IS DISTINCT FROM e.operation_date::text
   OR c->>'destination_account' IS DISTINCT FROM d->>'expense_account'
   OR c->'destination_dimensions' IS DISTINCT FROM d->'expense_dimensions'
   OR d->>'expense_account' !~ '^90[.]4([.]|$)'
   OR layer->>'inventory_account' IS DISTINCT FROM d->>'account'
   OR (layer->>'quantity')::numeric IS DISTINCT FROM (d->>'quantity')::numeric
   OR layer->'inventory_dimensions' IS DISTINCT FROM jsonb_build_object(
        'warehouse',d->>'warehouse','sku',d->>'sku','lot',d->>'lot')
   OR EXISTS (SELECT 1 FROM accounting.line WHERE entry_id=target AND quantity IS NOT NULL) THEN
   RAISE EXCEPTION 'Zero sale quantity and monetary receipt differ';
 END IF;
 FOREACH field IN ARRAY ARRAY['source','source_version','document_date','operation_date','posting_date','policy_id','explanation'] LOOP
   IF c->field IS DISTINCT FROM d->field THEN RAISE EXCEPTION 'Zero sale command metadata differ'; END IF;
 END LOOP;
 IF jsonb_typeof(d->'net_amount') IS DISTINCT FROM 'string'
    OR jsonb_typeof(d->'vat_rate') IS DISTINCT FROM 'string'
    OR d->>'net_amount' !~ '^[0-9]+([.][0-9]{1,2})?$'
    OR d->>'vat_rate' !~ '^[0-9]+([.][0-9]{1,4})?$'
    OR coalesce(btrim(d->>'vat_basis'),'')='' THEN
   RAISE EXCEPTION 'Zero sale requires exact monetary and VAT terms';
 END IF;
 net:=(d->>'net_amount')::numeric;
 IF net<=0 OR (d->>'vat_rate')::numeric NOT BETWEEN 0 AND 100 THEN
   RAISE EXCEPTION 'Zero sale monetary or VAT amount is invalid';
 END IF;
 vat:=round(net*(d->>'vat_rate')::numeric/100,2); gross:=net+vat;
 IF coalesce(d->>'buyer_account','') !~ '^62([.]|$)'
    OR coalesce(d->>'revenue_account','') !~ '^90[.]1([.]|$)'
    OR coalesce(d->>'vat_revenue_account','') !~ '^90[.]2([.]|$)'
    OR coalesce(d->>'vat_payable_account','') !~ '^68([.]|$)' THEN
   RAISE EXCEPTION 'Zero sale accounts do not have the required roles';
 END IF;
 FOREACH field IN ARRAY ARRAY['counterparty','contract','settlement_document'] LOOP
   IF coalesce(btrim(d->'buyer_dimensions'->>field),'')='' THEN
     RAISE EXCEPTION 'Zero sale buyer analytics are incomplete';
   END IF;
 END LOOP;
 metadata:=jsonb_build_object('vat_rate',d->>'vat_rate','vat_basis',d->>'vat_basis');
 IF (SELECT count(*) FROM accounting.line WHERE entry_id=target) <> (CASE WHEN vat=0 THEN 2 ELSE 4 END)
    OR (SELECT count(*) FROM accounting.line WHERE entry_id=target AND account_code=d->>'buyer_account'
         AND side='debit' AND amount=gross AND dimensions::jsonb=d->'buyer_dimensions')<>1
    OR (SELECT count(*) FROM accounting.line WHERE entry_id=target AND account_code=d->>'revenue_account'
         AND side='credit' AND amount=gross AND dimensions::jsonb=coalesce(d->'revenue_dimensions','{}'::jsonb)||metadata)<>1
    OR (vat<>0 AND ((SELECT count(*) FROM accounting.line WHERE entry_id=target AND account_code=d->>'vat_revenue_account'
         AND side='debit' AND amount=vat AND dimensions::jsonb=coalesce(d->'vat_dimensions','{}'::jsonb)||metadata)<>1
       OR (SELECT count(*) FROM accounting.line WHERE entry_id=target AND account_code=d->>'vat_payable_account'
         AND side='credit' AND amount=vat AND dimensions::jsonb=coalesce(d->'vat_dimensions','{}'::jsonb)||metadata)<>1)) THEN
   RAISE EXCEPTION 'Zero sale ledger differs from its monetary terms';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION accounting.check_zero_sale_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target integer;
BEGIN
 IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
 IF target IS NOT NULL THEN PERFORM accounting.validate_zero_sale_link(target); END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER complete_zero_sale_entry AFTER INSERT ON accounting.entry
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_zero_sale_link();
CREATE CONSTRAINT TRIGGER complete_zero_sale_receipt AFTER INSERT ON accounting.inventory_sale_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_zero_sale_link();
CREATE CONSTRAINT TRIGGER complete_zero_sale_quantity AFTER INSERT ON accounting.inventory_zero_value_disposal_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_zero_sale_link();
"""


def upgrade():
    op.execute(definitions())
    op.execute(LINK_DDL)
    evidence = runpy.run_path(str(Path(__file__).with_name("0141_zero_value_output_cost.py")))["_definitions"]()
    evidence = replace_once(evidence,
        "z.operation='inventory_issue' AND z.entry_id IS NULL",
        "((z.operation='inventory_issue' AND z.entry_id IS NULL) OR "
        "(z.operation='inventory_sale' AND z.entry_id=z.registration_token))")
    evidence = replace_once(evidence, "    IF zero_receipt.posting_date>cutoff THEN", """    IF zero_receipt.operation='inventory_sale' THEN
      PERFORM accounting.validate_zero_sale_link(zero_receipt.entry_id);
    END IF;
    IF zero_receipt.posting_date>cutoff THEN""")
    op.execute(evidence)


def downgrade():
    # Restoring the previous evidence definition must follow the populated-history check.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE operation='inventory_sale') THEN
        RAISE EXCEPTION 'Cannot downgrade 0143 with zero sale history';
      END IF;
    END $$;
    DROP TRIGGER complete_zero_sale_entry ON accounting.entry;
    DROP TRIGGER complete_zero_sale_receipt ON accounting.inventory_sale_receipt;
    DROP TRIGGER complete_zero_sale_quantity ON accounting.inventory_zero_value_disposal_receipt;
    DROP FUNCTION accounting.check_zero_sale_link();
    DROP FUNCTION accounting.validate_zero_sale_link(integer);""")
    old = previous(140, "0140_zero_value_disposals.py")
    op.execute(function(old, "register_inventory_zero_value_disposal"))
    op.execute(function(old, "guard_inventory_zero_value_disposal"))
    op.execute(function(previous(142, "0142_zero_value_command_dates.py"), "validate_zero_value_disposal_command"))
    op.execute(runpy.run_path(str(Path(__file__).with_name("0141_zero_value_output_cost.py")))["_definitions"]())
