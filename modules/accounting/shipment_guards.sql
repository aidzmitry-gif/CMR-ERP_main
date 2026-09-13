-- Independent physical, commercial and specific-lot cost checks for whole shipments.
CREATE TRIGGER no_truncate_shipment_receipt BEFORE TRUNCATE ON accounting.shipment_accounting_receipt
FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_history_mutation();

CREATE OR REPLACE FUNCTION accounting.shipment_account_contract(org integer, code_value text, day_value date,
    dims jsonb, category_value text, tracks_quantity boolean) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE acc accounting.account;
BEGIN
  SELECT * INTO acc FROM accounting.account WHERE organization_id=org AND code=code_value
    AND valid_from<=day_value ORDER BY valid_from DESC LIMIT 1;
  IF acc.id IS NULL OR acc.category IS DISTINCT FROM category_value OR acc.cash
     OR acc.quantity_tracking IS DISTINCT FROM tracks_quantity
     OR jsonb_typeof(dims) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Shipment account role or dimensions are invalid';
  END IF;
  IF EXISTS(SELECT 1 FROM jsonb_each(dims) d WHERE jsonb_typeof(d.value) IS DISTINCT FROM 'string'
      OR nullif(btrim(d.key),'') IS NULL OR length(d.key)>100
      OR nullif(btrim(d.value#>>'{}'),'') IS NULL OR length(d.value#>>'{}')>200)
     OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(acc.required_dimensions::jsonb) required
       WHERE NOT(dims ? required)) THEN
    RAISE EXCEPTION 'Shipment account requires valid complete analytics';
  END IF;
  RETURN acc.id;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_shipment_costs(receipt_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.shipment_accounting_receipt; bucket record; movement record; cost jsonb;
        qty numeric; amount numeric; issue_cost numeric; acquisition_amount numeric; acquisition_qty numeric;
        dims jsonb; expected jsonb:='[]'; policy accounting.policy; posting_day date;
        allocation jsonb; cumulative numeric; assigned numeric; target numeric; history jsonb;
        adjusted boolean; value_only boolean;
BEGIN
  SELECT * INTO STRICT r FROM accounting.shipment_accounting_receipt WHERE id=receipt_id;
  posting_day:=(r.command->>'posting_date')::date;
  IF r.command->>'recognition' IS DISTINCT FROM 'sale_on_shipment'
     OR r.command->>'cost_allocation' IS DISTINCT FROM 'cumulative_floor_last'
     OR r.command->>'vat_rounding' IS DISTINCT FROM 'commercial_line_half_up' THEN
    RAISE EXCEPTION 'Shipment calculation rule is unsupported';
  END IF;
  SELECT * INTO policy FROM accounting.policy WHERE organization_id=r.organization_id
    AND effective_from<=posting_day ORDER BY effective_from DESC LIMIT 1;
  IF policy.id IS NULL OR policy.id<>(r.command->>'policy_id')::integer OR policy.inventory_method<>'specific' THEN
    RAISE EXCEPTION 'Shipment requires its applicable specific-lot policy';
  END IF;
  IF jsonb_typeof(r.snapshot::jsonb->'costs') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment lot cost evidence required';
  END IF;
  FOR allocation IN SELECT value FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') LOOP
    IF (allocation->>'expense_account' ~ '^90[.]4([.]|$)') IS NOT TRUE THEN
      RAISE EXCEPTION 'Shipment allocation requires an expense account under 90.4';
    END IF;
    PERFORM accounting.shipment_account_contract(r.organization_id,allocation->>'expense_account',posting_day,
      allocation->'expense_dimensions','expense',false);
  END LOOP;
  IF EXISTS (
    (SELECT value-'cost_byn' FROM jsonb_array_elements(r.snapshot::jsonb->'mapping')
      EXCEPT ALL SELECT value FROM jsonb_array_elements(r.command::jsonb->'allocations'))
    UNION ALL
    (SELECT value FROM jsonb_array_elements(r.command::jsonb->'allocations')
      EXCEPT ALL SELECT value-'cost_byn' FROM jsonb_array_elements(r.snapshot::jsonb->'mapping'))
  ) THEN RAISE EXCEPTION 'Shipment mapping differs from approved allocation inputs'; END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(r.snapshot::jsonb->'costs')) <>
     (SELECT count(*) FROM (SELECT DISTINCT m->>'account',m->>'lot',p.warehouse,p.sku_code
       FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
       JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
       JOIN wms.physical_shipment_act a ON a.id=p.act_id
       WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source) b) THEN
    RAISE EXCEPTION 'Shipment lot cost evidence must cover every bucket once';
  END IF;
  FOR bucket IN
    SELECT m->>'account' AS account,m->>'lot' AS lot,p.warehouse,p.sku_code,
      sum((m->>'quantity')::numeric) AS quantity,sum((m->>'cost_byn')::numeric) AS mapped_cost
    FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
    JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
    JOIN wms.physical_shipment_act a ON a.id=p.act_id
    WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source
    GROUP BY m->>'account',m->>'lot',p.warehouse,p.sku_code
  LOOP
    IF bucket.account !~ '^41([.]|$)' OR nullif(bucket.lot,'') IS NULL THEN
      RAISE EXCEPTION 'Shipment inventory bucket is invalid';
    END IF;
    SELECT value INTO STRICT cost FROM jsonb_array_elements(r.snapshot::jsonb->'costs')
      WHERE value->>'account'=bucket.account AND value->'dimensions'->>'lot'=bucket.lot
        AND value->'dimensions'->>'warehouse'=bucket.warehouse AND value->'dimensions'->>'sku'=bucket.sku_code;
    qty:=0; amount:=0; dims:=NULL; acquisition_amount:=NULL; acquisition_qty:=NULL; history:='[]'; adjusted:=false;
    FOR movement IN SELECT l.*,e.posting_date,e.source,e.source_version,e.operation FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND l.account_code=bucket.account
        AND NOT(e.source=r.source OR starts_with(e.source,r.source||':part:'))
      ORDER BY e.posting_date,e.id,l.id
    LOOP
      IF nullif(movement.dimensions->>'warehouse','') IS NULL OR nullif(movement.dimensions->>'sku','') IS NULL
         OR nullif(movement.dimensions->>'lot','') IS NULL THEN
        RAISE EXCEPTION 'Shipment inventory history lacks required dimensions';
      END IF;
      IF movement.dimensions->>'warehouse'<>bucket.warehouse OR movement.dimensions->>'sku'<>bucket.sku_code
         OR movement.dimensions->>'lot'<>bucket.lot THEN CONTINUE; END IF;
      value_only:=movement.quantity IS NULL;
      IF value_only THEN
        IF movement.operation<>'inventory_late_cost' OR movement.side<>'debit' OR movement.amount<=0 OR qty<=0
           OR NOT EXISTS(SELECT 1 FROM accounting.late_cost_receipt c WHERE c.entry_id=movement.entry_id
              AND c.organization_id=r.organization_id) THEN
          RAISE EXCEPTION 'Shipment value adjustment has no valid late-cost receipt';
        END IF;
        PERFORM accounting.verify_late_cost_lines(movement.entry_id);
      END IF;
      IF movement.posting_date>posting_day OR movement.category<>'asset' OR movement.cash
         OR movement.currency<>'BYN' THEN
        RAISE EXCEPTION 'Shipment inventory history requires chronological owned BYN quantities';
      END IF;
      IF dims IS NULL THEN dims:=movement.dimensions::jsonb;
      ELSIF dims<>movement.dimensions::jsonb THEN RAISE EXCEPTION 'Shipment inventory lot has mixed analytics'; END IF;
      IF value_only THEN adjusted:=true;
      ELSIF movement.side='debit' THEN
        IF adjusted THEN RAISE EXCEPTION 'Shipment acquisition after cost adjustment requires separate layers'; END IF;
        IF acquisition_qty IS NULL THEN acquisition_amount:=movement.amount; acquisition_qty:=movement.quantity;
        ELSIF acquisition_amount*movement.quantity<>movement.amount*acquisition_qty THEN
          RAISE EXCEPTION 'Shipment inventory lot has mixed acquisition prices';
        END IF;
      END IF;
      IF NOT value_only THEN qty:=qty+movement.quantity*CASE WHEN movement.side='debit' THEN 1 ELSE -1 END; END IF;
      amount:=amount+movement.amount*CASE WHEN movement.side='debit' THEN 1 ELSE -1 END;
      IF qty<0 OR amount<0 OR (qty=0 AND amount<>0) THEN
        RAISE EXCEPTION 'Shipment inventory history has an invalid balance';
      END IF;
      history:=history||jsonb_build_array(jsonb_build_object('entry_id',movement.entry_id,'line_id',movement.id,
        'source',movement.source,'source_version',movement.source_version,'side',movement.side,
        'quantity',movement.quantity::text,'amount_byn',movement.amount::text));
    END LOOP;
    IF qty<=0 OR bucket.quantity<=0 OR bucket.quantity>qty THEN RAISE EXCEPTION 'Shipment exceeds book quantity'; END IF;
    issue_cost:=CASE WHEN bucket.quantity=qty THEN amount ELSE round(amount*bucket.quantity/qty,2) END;
    IF issue_cost<=0 OR bucket.mapped_cost IS DISTINCT FROM issue_cost
       OR (cost->>'issue_cost_byn')::numeric IS DISTINCT FROM issue_cost
       OR (cost->>'issue_quantity')::numeric IS DISTINCT FROM bucket.quantity
       OR (cost->>'book_quantity')::numeric IS DISTINCT FROM qty
       OR (cost->>'book_value_byn')::numeric IS DISTINCT FROM amount
       OR (cost->>'remaining_quantity')::numeric IS DISTINCT FROM qty-bucket.quantity
       OR (cost->>'remaining_value_byn')::numeric IS DISTINCT FROM amount-issue_cost
       OR cost->'evidence' IS DISTINCT FROM history
       OR cost->'inventory_dimensions' IS DISTINCT FROM dims THEN
      RAISE EXCEPTION 'Shipment inventory cost differs from ledger history';
    END IF;
    cumulative:=0; assigned:=0;
    FOR allocation IN SELECT m FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
      JOIN wms.physical_shipment_line p ON p.source=m->>'line_source'
      JOIN wms.physical_shipment_act a ON a.id=p.act_id
      WHERE a.organization_id=r.organization_id AND 'wms:physical-shipment:'||a.organization_id||':'||a.source_key=r.source
        AND m->>'account'=bucket.account AND m->>'lot'=bucket.lot
        AND p.warehouse=bucket.warehouse AND p.sku_code=bucket.sku_code
      ORDER BY accounting.financial_canonical(m-'cost_byn') COLLATE "C"
    LOOP
      cumulative:=cumulative+(allocation->>'quantity')::numeric;
      target:=floor(issue_cost*100*cumulative/bucket.quantity);
      IF (allocation->>'cost_byn')::numeric IS DISTINCT FROM (target-assigned)/100 THEN
        RAISE EXCEPTION 'Shipment cent allocation differs from deterministic lot distribution';
      END IF;
      assigned:=target;
    END LOOP;
    expected:=expected||jsonb_build_array(jsonb_build_object('account',bucket.account,'side','credit',
      'amount',issue_cost,'quantity',bucket.quantity,'dimensions',dims));
  END LOOP;
  SELECT expected||coalesce(jsonb_agg(jsonb_build_object('account',totals.account,'side','debit','amount',totals.amount,
      'quantity',NULL,'dimensions',totals.dimensions)),'[]'::jsonb) INTO expected
    FROM (SELECT m->>'expense_account' AS account,m->'expense_dimensions' AS dimensions,sum((m->>'cost_byn')::numeric) AS amount
      FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m GROUP BY m->>'expense_account',m->'expense_dimensions'
      HAVING sum((m->>'cost_byn')::numeric)<>0) totals;
  IF EXISTS (
    WITH wanted AS (SELECT v->>'account' AS account,v->>'side' AS side,(v->>'amount')::numeric AS amount,
      (v->>'quantity')::numeric AS quantity,v->'dimensions' AS dimensions FROM jsonb_array_elements(expected) v),
    actual AS (SELECT l.account_code AS account,l.side,sum(l.amount) AS amount,sum(l.quantity) AS quantity,l.dimensions::jsonb AS dimensions
      FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
        AND l.account_code ~ '^(41|90[.]4)([.]|$)'
      GROUP BY l.account_code,l.side,l.dimensions::jsonb)
    (SELECT * FROM wanted EXCEPT ALL SELECT * FROM actual) UNION ALL
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM wanted)
  ) THEN RAISE EXCEPTION 'Shipment inventory and expense ledger coverage differs'; END IF;
END $$;

CREATE OR REPLACE FUNCTION accounting.validate_shipment_receipt(receipt_id integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE r accounting.shipment_accounting_receipt; a wms.physical_shipment_act;
        page jsonb; n integer:=0; entry_row accounting.entry; expected_source text; basis jsonb;
        line_row accounting.line; category_value text; inventory_line boolean; effective_account integer;
BEGIN
  SELECT * INTO r FROM accounting.shipment_accounting_receipt WHERE id=receipt_id;
  IF r.id IS NULL THEN RAISE EXCEPTION 'Shipment receipt is required'; END IF;
  SELECT * INTO a FROM wms.physical_shipment_act WHERE organization_id=r.organization_id
    AND 'wms:physical-shipment:'||organization_id||':'||source_key=r.source;
  IF a.id IS NULL OR a.digest IS DISTINCT FROM r.act_digest
     OR r.snapshot::jsonb->'act' IS DISTINCT FROM jsonb_build_object(
       'act_id',a.id,'source_key',a.source_key,'request_hash',a.request_hash,'digest',a.digest,'snapshot',a.snapshot)
     OR r.command::jsonb->>'expected_act_digest' IS DISTINCT FROM a.digest THEN
    RAISE EXCEPTION 'Shipment receipt requires its exact physical act';
  END IF;
  basis:=jsonb_build_object('act_digest',r.act_digest,'inputs',r.command,
      'mapping',r.snapshot::jsonb->'mapping','costs',r.snapshot::jsonb->'costs',
      'commercial',r.snapshot::jsonb->'commercial');
  IF accounting.financial_sha(basis) IS DISTINCT FROM r.basis_digest
     OR jsonb_typeof(r.snapshot::jsonb->'pages') IS DISTINCT FROM 'array'
     OR jsonb_array_length(r.snapshot::jsonb->'pages')<1 THEN
    RAISE EXCEPTION 'Shipment receipt calculation envelope is invalid';
  END IF;
  FOR page IN SELECT value FROM jsonb_array_elements(r.snapshot::jsonb->'pages') LOOP
    n:=n+1;
    expected_source:=r.source||CASE WHEN n=1 THEN '' ELSE ':part:'||n END;
    SELECT * INTO entry_row FROM accounting.entry WHERE id=(page->>'entry_id')::integer;
    IF entry_row.id IS NULL OR entry_row.organization_id<>r.organization_id
       OR entry_row.source<>expected_source OR entry_row.source_version<>1
       OR entry_row.operation<>'inventory_sale' OR entry_row.actor<>r.actor
       OR entry_row.operation_date<>a.operation_date
       OR entry_row.document_date IS DISTINCT FROM (r.command->>'document_date')::date
       OR entry_row.posting_date IS DISTINCT FROM (r.command->>'posting_date')::date
       OR entry_row.policy_id IS DISTINCT FROM (r.command->>'policy_id')::integer
       OR entry_row.explanation IS DISTINCT FROM r.command->>'explanation'
       OR entry_row.opening IS DISTINCT FROM false OR entry_row.correction_of IS NOT NULL
       OR entry_row.rule_version<>'shipment-sale-v1:'||r.basis_digest
       OR entry_row.digest IS DISTINCT FROM page->>'digest'
       OR accounting.financial_sha(page->'posting') IS DISTINCT FROM entry_row.digest
       OR accounting.posting_body_projection(accounting.financial_posting_body(entry_row.id),false)
          IS DISTINCT FROM accounting.posting_body_projection(page->'posting',false)
       OR (n=1 AND entry_row.id<>r.anchor_entry_id) THEN
      RAISE EXCEPTION 'Shipment receipt does not match its complete ledger pages';
    END IF;
    FOR line_row IN SELECT * FROM accounting.line WHERE entry_id=entry_row.id LOOP
      inventory_line:=line_row.account_code ~ '^41([.]|$)';
      category_value:=CASE
        WHEN inventory_line OR line_row.account_code ~ '^62([.]|$)' THEN 'asset'
        WHEN line_row.account_code ~ '^90[.]4([.]|$)' THEN 'expense'
        WHEN line_row.account_code ~ '^90[.](1|2)([.]|$)' THEN 'income'
        WHEN line_row.account_code ~ '^68([.]|$)' THEN 'liability'
        ELSE NULL END;
      IF category_value IS NULL OR line_row.currency IS DISTINCT FROM 'BYN'
         OR line_row.original_amount IS NOT NULL OR line_row.rate IS NOT NULL
         OR line_row.rate_scale IS NOT NULL OR line_row.rate_date IS NOT NULL OR line_row.rate_source IS NOT NULL
         OR line_row.cash_activity IS NOT NULL
         OR (line_row.amount>0 AND line_row.amount<1000000000000000000) IS NOT TRUE
         OR (inventory_line AND (line_row.quantity>0 AND line_row.quantity<1000000000000000000) IS NOT TRUE)
         OR (NOT inventory_line AND line_row.quantity IS NOT NULL) THEN
        RAISE EXCEPTION 'Shipment ledger line has incompatible quantity, currency or cash metadata';
      END IF;
      effective_account:=accounting.shipment_account_contract(r.organization_id,line_row.account_code,
        entry_row.posting_date,line_row.dimensions::jsonb,category_value,inventory_line);
      IF effective_account IS DISTINCT FROM line_row.account_id THEN
        RAISE EXCEPTION 'Shipment ledger line requires the effective account version';
      END IF;
    END LOOP;
  END LOOP;
  IF (SELECT count(*) FROM accounting.entry WHERE organization_id=r.organization_id
      AND (source=r.source OR starts_with(source,r.source||':part:')))<>n THEN
    RAISE EXCEPTION 'Shipment receipt has extra ledger pages';
  END IF;
  IF jsonb_typeof(r.snapshot::jsonb->'mapping') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment receipt requires physical quantity coverage';
  END IF;
  IF EXISTS (
    WITH mapped AS (
      SELECT value->>'line_source' AS source,sum((value->>'quantity')::numeric) AS qty
      FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') GROUP BY value->>'line_source'
    ), physical AS (SELECT source,qty FROM wms.physical_shipment_line WHERE act_id=a.id)
    SELECT 1 FROM mapped FULL JOIN physical USING(source)
    WHERE mapped.qty IS DISTINCT FROM physical.qty
  ) OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(r.snapshot::jsonb->'mapping') m
    WHERE (m->>'quantity')::numeric<=0 OR m->>'quantity' IS NULL
  ) THEN RAISE EXCEPTION 'Shipment receipt physical quantity coverage differs'; END IF;
  IF jsonb_typeof(r.command::jsonb->'commercial_lines') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'Shipment commercial treatment is required';
  END IF;
  IF EXISTS (
    WITH commercial AS (SELECT (value->>'line_no')::integer AS line_no,count(*) AS n
      FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') GROUP BY (value->>'line_no')::integer),
    physical AS (SELECT DISTINCT line_no FROM wms.physical_shipment_line WHERE act_id=a.id)
    SELECT 1 FROM commercial FULL JOIN physical USING(line_no)
      WHERE commercial.n IS DISTINCT FROM 1::bigint OR physical.line_no IS NULL
  ) THEN RAISE EXCEPTION 'Shipment commercial lines must cover the physical act exactly once'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') c WHERE
      jsonb_typeof(c->'net_amount') IS DISTINCT FROM 'string'
      OR jsonb_typeof(c->'vat_rate') IS DISTINCT FROM 'string'
      OR ((c->>'net_amount')::numeric>0 AND (c->>'net_amount')::numeric<1000000000000000000) IS NOT TRUE
      OR ((c->>'vat_rate')::numeric BETWEEN 0 AND 100) IS NOT TRUE
      OR (c->>'buyer_account' ~ '^62([.]|$)') IS NOT TRUE OR (c->>'revenue_account' ~ '^90[.]1([.]|$)') IS NOT TRUE
      OR (c->>'vat_revenue_account' ~ '^90[.]2([.]|$)') IS NOT TRUE OR (c->>'vat_payable_account' ~ '^68([.]|$)') IS NOT TRUE
      OR c->'buyer_dimensions'->>'settlement_document' IS DISTINCT FROM 'sales:document:'||a.document_id
      OR nullif(btrim(c->>'vat_basis'),'') IS NULL) THEN
    RAISE EXCEPTION 'Shipment commercial treatment is invalid';
  END IF;
  IF EXISTS (
    WITH commercial AS (
      SELECT c, round((c->>'net_amount')::numeric*(c->>'vat_rate')::numeric/100,2) AS vat,
        jsonb_build_object('vat_rate',c->>'vat_rate','vat_basis',c->>'vat_basis') AS metadata
      FROM jsonb_array_elements(r.command::jsonb->'commercial_lines') c
    ), expected_lines AS (
      SELECT v.* FROM commercial CROSS JOIN LATERAL (VALUES
        (c->>'buyer_account','debit',(c->>'net_amount')::numeric+vat,c->'buyer_dimensions'),
        (c->>'revenue_account','credit',(c->>'net_amount')::numeric+vat,(c->'revenue_dimensions')||metadata),
        (c->>'vat_revenue_account','debit',vat,(c->'vat_dimensions')||metadata),
        (c->>'vat_payable_account','credit',vat,(c->'vat_dimensions')||metadata)
      ) v(account,side,amount,dimensions) WHERE amount<>0
    ), expected AS (
      SELECT account,side,sum(amount) AS amount,dimensions FROM expected_lines GROUP BY account,side,dimensions
    ), actual AS (
      SELECT l.account_code AS account,l.side,sum(l.amount) AS amount,l.dimensions::jsonb AS dimensions
      FROM accounting.line l JOIN accounting.entry e ON e.id=l.entry_id
      WHERE e.organization_id=r.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
        AND l.account_code !~ '^(41|90[.]4)([.]|$)'
      GROUP BY l.account_code,l.side,l.dimensions::jsonb
    )
    (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
    UNION ALL
    (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
  ) THEN RAISE EXCEPTION 'Shipment revenue and VAT ledger coverage differs'; END IF;
  PERFORM accounting.validate_shipment_costs(r.id);
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_shipment_receipt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE page jsonb;
BEGIN
  FOR page IN SELECT value FROM jsonb_array_elements(NEW.snapshot::jsonb->'pages') LOOP
    PERFORM accounting.require_financial_entry_root((page->>'entry_id')::integer,NEW.organization_id,NEW.actor,'inventory_sale');
  END LOOP;
  PERFORM accounting.validate_shipment_receipt(NEW.id);
  RETURN NULL;
END $$;
CREATE TRIGGER validate_shipment_receipt_insert AFTER INSERT ON accounting.shipment_accounting_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_receipt_insert();
CREATE CONSTRAINT TRIGGER recheck_shipment_receipt_at_commit AFTER INSERT ON accounting.shipment_accounting_receipt
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_receipt_insert();

-- Each later ledger insertion schedules a fresh check. An earlier SET CONSTRAINTS
-- cannot drain protection for changes that have not happened yet.
CREATE OR REPLACE FUNCTION accounting.recheck_shipment_after_ledger_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt_id integer;
BEGIN
  FOR receipt_id IN
    SELECT r.id FROM accounting.shipment_accounting_receipt r
    JOIN accounting.entry_transaction t ON t.entry_id=r.anchor_entry_id
    JOIN accounting.entry e ON e.organization_id=r.organization_id
    WHERE e.id=NEW.entry_id AND t.root_transaction=txid_current()
      -- Own pages are verified by receipt insertion/commit; finalized guards
      -- forbid adding their lines after receipt creation. Recheck only external
      -- movements that can change the already calculated inventory basis.
      AND e.source<>r.source AND NOT starts_with(e.source,r.source||':part:')
  LOOP
    PERFORM accounting.validate_shipment_receipt(receipt_id);
  END LOOP;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER recheck_shipment_on_ledger_insert AFTER INSERT ON accounting.line
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.recheck_shipment_after_ledger_insert();

CREATE OR REPLACE FUNCTION accounting.guard_shipment_source_resolution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE receipt_id integer;
BEGIN
  IF starts_with(NEW.source,'wms:physical-shipment:') AND NEW.entry_id IS NOT NULL THEN
    SELECT id INTO receipt_id FROM accounting.shipment_accounting_receipt
      WHERE organization_id=NEW.organization_id AND source=NEW.source AND anchor_entry_id=NEW.entry_id;
    PERFORM accounting.validate_shipment_receipt(receipt_id);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER require_shipment_receipt BEFORE INSERT OR UPDATE ON accounting.source_control
FOR EACH ROW EXECUTE FUNCTION accounting.guard_shipment_source_resolution();

CREATE OR REPLACE FUNCTION accounting.guard_final_shipment_line() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM accounting.entry e JOIN accounting.shipment_accounting_receipt r
      ON r.organization_id=e.organization_id AND (e.source=r.source OR starts_with(e.source,r.source||':part:'))
      WHERE e.id=NEW.entry_id) THEN
    RAISE EXCEPTION 'Shipment receipt ledger lines are finalized';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finalized_shipment_line BEFORE INSERT ON accounting.line
FOR EACH ROW EXECUTE FUNCTION accounting.guard_final_shipment_line();

CREATE OR REPLACE FUNCTION accounting.guard_final_shipment_page() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS(SELECT 1 FROM accounting.shipment_accounting_receipt r WHERE r.organization_id=NEW.organization_id
      AND (NEW.source=r.source OR starts_with(NEW.source,r.source||':part:'))) THEN
    RAISE EXCEPTION 'Shipment receipt ledger pages are finalized';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER finalized_shipment_page BEFORE INSERT ON accounting.entry
FOR EACH ROW EXECUTE FUNCTION accounting.guard_final_shipment_page();
