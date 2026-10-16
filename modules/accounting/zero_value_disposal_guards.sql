-- FOUNDATION ONLY: this draft is deliberately not referenced by a migration.
-- It documents the DB boundary required before zero-value receipt confirmation
-- can be connected to inventory valuation or sales.

CREATE OR REPLACE FUNCTION accounting.register_inventory_zero_value_disposal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE entry_sequence text;
BEGIN
  IF NEW.registration_token IS NOT NULL THEN
    RAISE EXCEPTION 'Zero-value disposal registration token is database assigned';
  END IF;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  SELECT pg_get_serial_sequence('accounting.entry', 'id') INTO entry_sequence;
  IF entry_sequence IS NULL THEN RAISE EXCEPTION 'Accounting entry identity sequence is unavailable'; END IF;
  EXECUTE format('SELECT nextval(%L)', entry_sequence) INTO NEW.registration_token;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION accounting.guard_inventory_zero_value_disposal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE posted accounting.entry%ROWTYPE; period_row accounting.period%ROWTYPE; layer jsonb; command_snapshot jsonb;
BEGIN
  -- Fail closed until a migration installs the canonical SQL digest verifier.
  RAISE EXCEPTION 'Zero-value disposal foundation is not enabled without its migration and canonical DB authentication';
  command_snapshot := NEW.command::jsonb;
  PERFORM 1 FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
  IF NOT EXISTS (SELECT 1 FROM accounting.policy WHERE id=NEW.policy_id
                 AND organization_id=NEW.organization_id AND effective_from<=NEW.posting_date) THEN
    RAISE EXCEPTION 'Zero-value disposal requires an applicable organization policy';
  END IF;
  SELECT * INTO period_row FROM accounting.period
    WHERE organization_id=NEW.organization_id AND month=to_char(NEW.posting_date,'YYYY-MM');
  IF NOT FOUND OR period_row.closed THEN RAISE EXCEPTION 'Zero-value disposal requires an open accounting period'; END IF;
  IF NEW.operation NOT IN ('inventory_issue','inventory_sale') OR NEW.source='' OR NEW.source_version<=0
    OR NEW.basis_digest !~ '^[0-9a-f]{64}$' OR NEW.digest !~ '^[0-9a-f]{64}$'
    OR command_snapshot->>'source' IS DISTINCT FROM NEW.source
    OR (command_snapshot->>'source_version')::integer IS DISTINCT FROM NEW.source_version
    OR command_snapshot->>'operation' IS DISTINCT FROM NEW.operation
    OR (command_snapshot->>'policy_id')::integer IS DISTINCT FROM NEW.policy_id
    OR command_snapshot->>'basis_digest' IS DISTINCT FROM NEW.basis_digest
    OR command_snapshot->>'posting_date' IS DISTINCT FROM NEW.posting_date::text
    OR command_snapshot->>'destination_account' IS NULL
    OR jsonb_typeof(coalesce(command_snapshot->'destination_dimensions','{}'::jsonb)) IS DISTINCT FROM 'object'
    OR length(btrim(coalesce(command_snapshot->>'explanation','')))=0
    OR length(btrim(coalesce(NEW.actor,'')))=0
    OR jsonb_typeof(command_snapshot->'inventory_layers') IS DISTINCT FROM 'array'
    OR jsonb_array_length(command_snapshot->'inventory_layers')=0 THEN
    RAISE EXCEPTION 'Zero-value disposal has an incomplete immutable snapshot';
  END IF;
  FOR layer IN SELECT value FROM jsonb_array_elements(command_snapshot->'inventory_layers') LOOP
    IF (layer->>'source_entry_id')::integer <= 0 OR (layer->>'source_line_id')::integer <= 0
      OR layer->>'inventory_account' IS NULL OR layer->'inventory_dimensions' IS NULL
      OR nullif(layer->'inventory_dimensions'->>'warehouse','') IS NULL
      OR nullif(layer->'inventory_dimensions'->>'sku','') IS NULL
      OR nullif(layer->'inventory_dimensions'->>'lot','') IS NULL
      OR (layer->>'quantity')::numeric <= 0 THEN
      RAISE EXCEPTION 'Zero-value disposal layer identity or quantity is invalid';
    END IF;
  END LOOP;
  SELECT * INTO posted FROM accounting.entry WHERE organization_id=NEW.organization_id
    AND source=NEW.source AND source_version=NEW.source_version AND operation=NEW.operation;
  IF NEW.operation='inventory_issue' THEN
    IF NEW.entry_id IS NOT NULL OR posted.id IS NOT NULL THEN
      RAISE EXCEPTION 'Zero-value inventory issue must not share an entry identity';
    END IF;
  ELSE
    IF NEW.entry_id IS NULL OR posted.id IS DISTINCT FROM NEW.entry_id OR posted.digest IS NULL
      OR posted.actor IS DISTINCT FROM NEW.actor OR posted.policy_id IS DISTINCT FROM NEW.policy_id
      OR posted.posting_date IS DISTINCT FROM NEW.posting_date THEN
      RAISE EXCEPTION 'Zero-value sale disposal must bind its real sale entry';
    END IF;
  END IF;
  RETURN NEW; -- unreachable until the migration supplies canonical authentication.
END $$;

-- A symmetric BEFORE INSERT guard on accounting.entry is required as well:
-- lock organization and reject an inventory_issue entry if this receipt already
-- owns the same (organization_id, source, source_version, operation).  Sales
-- are allowed only when they are the entry explicitly bound by this receipt.
