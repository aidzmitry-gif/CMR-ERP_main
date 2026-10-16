"""Bind explicit source allocations to their immutable ledger packages.

These checks authenticate structure and lineage, not historical valuation.
"""
from alembic import op

revision = "0144"
down_revision = "0143"
branch_labels = None
depends_on = None

DDL = r"""
CREATE OR REPLACE FUNCTION accounting.validate_inventory_allocation_link(target integer)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; r jsonb; c jsonb; p jsonb; d jsonb;
  item jsonb; expected jsonb; origin record; movement record; pos integer:=0;
  positive_pos integer:=0; qty numeric:=0; cost numeric:=0; seen text[]:=ARRAY[]::text[];
  identity text; effective_policy integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=target;
  IF NOT FOUND THEN RAISE EXCEPTION 'Allocation entry is missing'; END IF;
  IF e.operation='inventory_issue' THEN
    SELECT to_jsonb(x) INTO r FROM accounting.inventory_issue_receipt x WHERE entry_id=target;
  ELSIF e.operation='inventory_sale' THEN
    SELECT to_jsonb(x) INTO r FROM accounting.inventory_sale_receipt x WHERE entry_id=target;
  ELSE RETURN; END IF;
  c:=r->'cost'; p:=r->'posting'; d:=r->'command';
  IF NOT coalesce(c ? 'source_allocation_version',false) AND e.rule_version NOT LIKE ('%'||chr(58)||'a1') THEN RETURN; END IF;
  IF r IS NULL OR jsonb_typeof(c->'source_allocation_version') IS DISTINCT FROM 'number'
    OR c->>'source_allocation_version' IS DISTINCT FROM '1' THEN
    RAISE EXCEPTION 'Explicit allocation requires version 1 receipt';
  END IF;
  IF (r->>'organization_id')::integer IS DISTINCT FROM e.organization_id
    OR r->>'actor' IS DISTINCT FROM e.actor OR r->>'digest' IS DISTINCT FROM e.digest
    OR p->>'rule_version' IS DISTINCT FROM e.rule_version OR p->>'operation' IS DISTINCT FROM e.operation
    OR p->>'source' IS DISTINCT FROM e.source OR d->>'source' IS DISTINCT FROM e.source
    OR p->>'source_version' IS DISTINCT FROM e.source_version::text
    OR d->>'source_version' IS DISTINCT FROM e.source_version::text
    OR e.opening OR e.correction_of IS NOT NULL
    OR p->>'opening' IS DISTINCT FROM 'false' OR p->>'correction_of' IS NOT NULL
    OR p->>'explanation' IS DISTINCT FROM e.explanation OR d->>'explanation' IS DISTINCT FROM e.explanation THEN
    RAISE EXCEPTION 'Allocation receipt identity differs from entry';
  END IF;
  IF p->>'document_date' IS DISTINCT FROM e.document_date::text
    OR d->>'document_date' IS DISTINCT FROM e.document_date::text
    OR p->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR d->>'operation_date' IS DISTINCT FROM e.operation_date::text
    OR p->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR d->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR c->>'posting_date' IS DISTINCT FROM e.posting_date::text
    OR p->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR d->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR c->>'policy_id' IS DISTINCT FROM e.policy_id::text
    OR c->>'organization_id' IS DISTINCT FROM e.organization_id::text
    OR c->>'account' IS DISTINCT FROM d->>'account'
    OR coalesce(c->>'basis_digest','') !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'Allocation dates or cost identity differ';
  END IF;
  SELECT id INTO effective_policy FROM accounting.policy WHERE organization_id=e.organization_id
    AND effective_from<=e.posting_date ORDER BY effective_from DESC LIMIT 1;
  IF effective_policy IS DISTINCT FROM e.policy_id OR c->>'method' NOT IN ('fifo','weighted_average')
    OR c->>'method' IS DISTINCT FROM (SELECT inventory_method FROM accounting.policy WHERE id=e.policy_id) THEN
    RAISE EXCEPTION 'Allocation policy is not applicable';
  END IF;
  IF jsonb_typeof(p->'lines') IS DISTINCT FROM 'array'
    OR jsonb_typeof(c->'inventory_layers') IS DISTINCT FROM 'array'
    OR jsonb_array_length(c->'inventory_layers') NOT BETWEEN 1 AND 1000 THEN
    RAISE EXCEPTION 'Allocation arrays are missing';
  END IF;
  FOR movement IN SELECT * FROM accounting.line WHERE entry_id=target ORDER BY id LOOP
    expected:=p->'lines'->pos;
    IF expected IS NULL OR expected->>'account' IS DISTINCT FROM movement.account_code
      OR expected->>'side' IS DISTINCT FROM movement.side
      OR (expected->>'amount')::numeric IS DISTINCT FROM movement.amount
      OR (expected->>'quantity')::numeric IS DISTINCT FROM movement.quantity
      OR expected->'dimensions' IS DISTINCT FROM movement.dimensions::jsonb
      OR movement.amount<=0 OR movement.currency<>'BYN' OR expected->>'currency' IS DISTINCT FROM 'BYN'
      OR movement.original_amount IS NOT NULL OR expected->>'original_amount' IS NOT NULL
      OR movement.rate IS NOT NULL OR expected->>'rate' IS NOT NULL
      OR movement.rate_scale IS NOT NULL OR expected->>'rate_scale' IS NOT NULL
      OR movement.rate_date IS NOT NULL OR expected->>'rate_date' IS NOT NULL
      OR movement.rate_source IS NOT NULL OR expected->>'rate_source' IS NOT NULL
      OR movement.cash OR movement.cash_activity IS NOT NULL OR expected->>'cash_activity' IS NOT NULL THEN
      RAISE EXCEPTION 'Allocation posting differs from ledger';
    END IF;
    pos:=pos+1;
  END LOOP;
  IF pos=0 OR pos<>jsonb_array_length(p->'lines') THEN RAISE EXCEPTION 'Allocation posting is incomplete'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(c->'inventory_layers') LOOP
    IF jsonb_typeof(item->'source_entry_id') IS DISTINCT FROM 'number'
      OR jsonb_typeof(item->'source_line_id') IS DISTINCT FROM 'number'
      OR coalesce(item->>'source_entry_id','') !~ '^[1-9][0-9]*$'
      OR coalesce(item->>'source_line_id','') !~ '^[1-9][0-9]*$'
      OR coalesce(item->>'quantity','') !~ '^[0-9]+(\.[0-9]{1,6})?$'
      OR coalesce(item->>'amount_byn','') !~ '^[0-9]+(\.[0-9]{1,2})?$'
      OR (item->>'quantity')::numeric<=0 THEN RAISE EXCEPTION 'Invalid allocation source or numbers'; END IF;
    identity:=(item->>'source_entry_id')||':'||(item->>'source_line_id');
    IF identity=ANY(seen) THEN RAISE EXCEPTION 'Duplicate allocation origin'; END IF;
    seen:=array_append(seen,identity);
    SELECT l.*, x.organization_id AS owner, x.posting_date AS origin_date INTO origin
      FROM accounting.line l JOIN accounting.entry x ON x.id=l.entry_id
      WHERE l.id=(item->>'source_line_id')::integer AND x.id=(item->>'source_entry_id')::integer;
    IF NOT FOUND OR origin.owner<>e.organization_id OR origin.entry_id>=target OR origin.origin_date>e.posting_date
      OR origin.side<>'debit' OR origin.quantity IS NULL OR origin.quantity<=0
      OR origin.account_code IS DISTINCT FROM d->>'account' OR origin.category<>'asset' OR origin.cash
      OR origin.currency<>'BYN' OR origin.dimensions::jsonb IS DISTINCT FROM item->'dimensions'
      OR item->'dimensions'->>'warehouse' IS DISTINCT FROM d->>'warehouse'
      OR item->'dimensions'->>'sku' IS DISTINCT FROM d->>'sku'
      OR coalesce(item->'dimensions'->>'lot','')='' OR item->>'lot' IS DISTINCT FROM item->'dimensions'->>'lot'
      OR (coalesce(d->>'lot','')<>'' AND item->'dimensions'->>'lot' IS DISTINCT FROM d->>'lot') THEN
      RAISE EXCEPTION 'Allocation origin is not a prior owned inventory debit';
    END IF;
    qty:=qty+(item->>'quantity')::numeric; cost:=cost+(item->>'amount_byn')::numeric;
    IF (item->>'amount_byn')::numeric>0 THEN
      SELECT * INTO movement FROM accounting.line WHERE entry_id=target AND account_code=d->>'account'
        ORDER BY id OFFSET positive_pos LIMIT 1;
      IF NOT FOUND OR movement.side<>'credit' OR movement.category<>'asset'
        OR movement.quantity IS DISTINCT FROM (item->>'quantity')::numeric
        OR movement.amount IS DISTINCT FROM (item->>'amount_byn')::numeric
        OR movement.dimensions::jsonb IS DISTINCT FROM item->'dimensions' THEN
        RAISE EXCEPTION 'Allocation positive portion differs from inventory credit';
      END IF;
      positive_pos:=positive_pos+1;
    END IF;
  END LOOP;
  IF qty IS DISTINCT FROM (d->>'quantity')::numeric OR qty IS DISTINCT FROM (c->>'issue_quantity')::numeric
    OR cost IS DISTINCT FROM (c->>'issue_cost_byn')::numeric
    OR positive_pos<>(SELECT count(*) FROM accounting.line WHERE entry_id=target AND account_code=d->>'account') THEN
    RAISE EXCEPTION 'Allocation quantity, cost or credit count differs';
  END IF;
END $$;
CREATE OR REPLACE FUNCTION accounting.check_inventory_allocation_link() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='entry' THEN PERFORM accounting.validate_inventory_allocation_link(NEW.id);
  ELSE PERFORM accounting.validate_inventory_allocation_link(NEW.entry_id); END IF;
  RETURN NULL;
END $$;
"""


def upgrade():
    op.execute(DDL)
    for table in ("entry", "line", "inventory_issue_receipt", "inventory_sale_receipt"):
        op.execute(f"CREATE CONSTRAINT TRIGGER explicit_allocation_{table} AFTER INSERT ON accounting.{table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.check_inventory_allocation_link()")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.entry WHERE rule_version LIKE ('%'||chr(58)||'a1'))
        OR EXISTS (SELECT 1 FROM accounting.inventory_issue_receipt WHERE cost::jsonb ? 'source_allocation_version')
        OR EXISTS (SELECT 1 FROM accounting.inventory_sale_receipt WHERE cost::jsonb ? 'source_allocation_version') THEN
        RAISE EXCEPTION 'Cannot downgrade 0144 with explicit allocation history';
      END IF;
    END $$;""")
    for table in ("entry", "line", "inventory_issue_receipt", "inventory_sale_receipt"):
        op.execute(f"DROP TRIGGER explicit_allocation_{table} ON accounting.{table}")
    op.execute("DROP FUNCTION accounting.check_inventory_allocation_link(); "
               "DROP FUNCTION accounting.validate_inventory_allocation_link(integer)")
