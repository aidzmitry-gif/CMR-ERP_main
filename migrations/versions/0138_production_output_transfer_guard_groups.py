"""Allow strict grouped WIP credits for finished-goods output transfers.

Revision ID: 0138
Revises: 0137
"""
from alembic import op

revision = "0138"
down_revision = "0137"
branch_labels = None
depends_on = None


UPGRADE_GUARD = r"""
CREATE OR REPLACE FUNCTION accounting.guard_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  e accounting.entry%ROWTYPE;
  debit_count integer;
  credit_count integer;
  declared_debit_count integer;
  declared_credit_count integer;
  declared_line_count integer;
  expected_group_count integer;
  expected_group_sum numeric;
  expected_groups jsonb;
  actual_credits jsonb;
  declared_credits jsonb;
  actual_debit accounting.line%ROWTYPE;
  declared_debit jsonb;
  actual_debit_tuple jsonb;
  declared_debit_tuple jsonb;
  basis jsonb;
  posting jsonb;
BEGIN
  basis := NEW.basis::jsonb;
  posting := NEW.posting::jsonb;
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id <> NEW.organization_id
     OR e.source IS DISTINCT FROM 'production:output-transfer:'||NEW.organization_id||':'||NEW.order_id
     OR e.operation IS DISTINCT FROM 'production_output_transfer'
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'order_id' IS DISTINCT FROM NEW.order_id::text
     OR NEW.command->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
     OR NEW.command->>'digest' IS DISTINCT FROM NEW.digest
     OR NEW.posting IS NULL OR NEW.basis IS NULL THEN
    RAISE EXCEPTION 'Production output transfer receipt does not match its ledger entry';
  END IF;

  IF (basis->>'organization_id') IS DISTINCT FROM NEW.organization_id::text
     OR (basis->>'policy_id') IS DISTINCT FROM e.policy_id::text
     OR (posting->>'policy_id') IS DISTINCT FROM e.policy_id::text
     OR basis->'target'->>'finished_goods_account' IS NULL
     OR basis->'wip'->>'account' IS NULL
     OR basis->>'candidate_transfer_byn' IS NULL
     OR basis->'output'->>'accepted_quantity' IS NULL THEN
    RAISE EXCEPTION 'Production output transfer receipt has incomplete policy or cost basis';
  END IF;

  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  SELECT count(*) FILTER (WHERE line->>'side'='debit'), count(*) FILTER (WHERE line->>'side'='credit')
    INTO declared_debit_count, declared_credit_count FROM jsonb_array_elements(posting->'lines') line;
  declared_line_count := jsonb_array_length(posting->'lines');

  SELECT * INTO actual_debit FROM accounting.line
    WHERE entry_id=NEW.entry_id AND side='debit';
  SELECT line INTO declared_debit FROM jsonb_array_elements(posting->'lines') line
    WHERE line->>'side'='debit';
  actual_debit_tuple := jsonb_build_object('account',actual_debit.account_code,'side',actual_debit.side,
    'amount',actual_debit.amount,'dimensions',actual_debit.dimensions::jsonb,
    'quantity',actual_debit.quantity,'currency',actual_debit.currency);
  declared_debit_tuple := jsonb_build_object('account',declared_debit->>'account','side',declared_debit->>'side',
    'amount',(declared_debit->>'amount')::numeric,'dimensions',declared_debit->'dimensions',
    'quantity',(declared_debit->>'quantity')::numeric,'currency',declared_debit->>'currency');
  IF debit_count <> 1 OR declared_debit_count <> 1 OR declared_debit IS NULL
     OR actual_debit.account_code IS DISTINCT FROM basis->'target'->>'finished_goods_account'
     OR actual_debit.currency IS DISTINCT FROM 'BYN'
     OR actual_debit.amount IS DISTINCT FROM (basis->>'candidate_transfer_byn')::numeric
     OR actual_debit.quantity IS DISTINCT FROM (basis->'output'->>'accepted_quantity')::numeric
     OR actual_debit_tuple IS DISTINCT FROM declared_debit_tuple THEN
    RAISE EXCEPTION 'Production output transfer finished-goods debit differs from its receipt';
  END IF;

  IF NOT (basis->'wip' ? 'groups') THEN
    IF credit_count <> 1 OR declared_credit_count <> 1 OR declared_line_count <> 2 THEN
      RAISE EXCEPTION 'Legacy production output transfer must contain one credit';
    END IF;
    RETURN NEW;
  END IF;

  SELECT count(*), coalesce(sum((item->>'balance_byn')::numeric),0),
         count(DISTINCT item->'dimensions'),
         coalesce(jsonb_agg(jsonb_build_object('account',basis->'wip'->>'account','side','credit',
           'dimensions',item->'dimensions','amount',(item->>'balance_byn')::numeric,
           'currency','BYN','quantity',null)
           ORDER BY item->'dimensions', (item->>'balance_byn')::numeric),'[]'::jsonb)
    INTO expected_group_count, expected_group_sum, debit_count, expected_groups
    FROM jsonb_array_elements(basis->'wip'->'groups') item
    WHERE jsonb_typeof(item->'dimensions')='object' AND (item->>'balance_byn')::numeric > 0;
  IF expected_group_count < 1 OR expected_group_count <> debit_count
     OR expected_group_sum IS DISTINCT FROM actual_debit.amount
     OR jsonb_array_length(basis->'wip'->'groups') <> expected_group_count THEN
    RAISE EXCEPTION 'Production output transfer WIP groups must be unique and positive';
  END IF;

  SELECT coalesce(jsonb_agg(jsonb_build_object('account',account_code,'side',side,'dimensions',dimensions::jsonb,
           'amount',amount,'currency',currency,'quantity',quantity)
           ORDER BY dimensions::jsonb, amount),'[]'::jsonb)
    INTO actual_credits FROM accounting.line WHERE entry_id=NEW.entry_id AND side='credit';
  SELECT coalesce(jsonb_agg(jsonb_build_object('account',line->>'account','side',line->>'side',
           'dimensions',line->'dimensions','amount',(line->>'amount')::numeric,
           'currency',line->>'currency','quantity',(line->>'quantity')::numeric)
           ORDER BY line->'dimensions', (line->>'amount')::numeric),'[]'::jsonb)
    INTO declared_credits FROM jsonb_array_elements(posting->'lines') line
    WHERE line->>'side'='credit';
  IF credit_count <> expected_group_count OR declared_credit_count <> expected_group_count
     OR declared_line_count <> expected_group_count + 1 OR actual_credits IS DISTINCT FROM expected_groups
     OR declared_credits IS DISTINCT FROM expected_groups THEN
    RAISE EXCEPTION 'Production output transfer WIP credits differ from their saved analytic groups';
  END IF;
  RETURN NEW;
END $$;
"""


DOWNGRADE_GUARD = r"""
CREATE OR REPLACE FUNCTION accounting.guard_production_output_transfer_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e accounting.entry%ROWTYPE; debit_count integer; credit_count integer;
BEGIN
  SELECT * INTO e FROM accounting.entry WHERE id=NEW.entry_id;
  IF NOT FOUND OR e.organization_id <> NEW.organization_id
     OR e.source IS DISTINCT FROM 'production:output-transfer:'||NEW.organization_id||':'||NEW.order_id
     OR e.operation IS DISTINCT FROM 'production_output_transfer'
     OR e.source_version <> 1 OR e.digest IS DISTINCT FROM NEW.digest
     OR NEW.command->>'order_id' IS DISTINCT FROM NEW.order_id::text
     OR NEW.command->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
     OR NEW.command->>'digest' IS DISTINCT FROM NEW.digest
     OR NEW.posting IS NULL OR NEW.basis IS NULL THEN
    RAISE EXCEPTION 'Production output transfer receipt does not match its ledger entry';
  END IF;
  SELECT count(*) FILTER (WHERE side='debit'), count(*) FILTER (WHERE side='credit')
    INTO debit_count, credit_count FROM accounting.line WHERE entry_id=NEW.entry_id;
  IF debit_count <> 1 OR credit_count <> 1 THEN
    RAISE EXCEPTION 'Production output transfer must contain one debit and one credit';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(UPGRADE_GUARD)


def downgrade() -> None:
    op.execute(DOWNGRADE_GUARD)
