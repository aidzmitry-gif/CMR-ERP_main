"""Store an immutable V3 full-pool package without changing V1/V2 receipts."""

from alembic import op

revision = "0153"
down_revision = "0152"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE accounting.late_pool_package (
      id serial PRIMARY KEY,
      organization_id integer NOT NULL REFERENCES accounting.organization(id),
      request_key uuid NOT NULL,
      late_entry_id integer NOT NULL UNIQUE REFERENCES accounting.entry(id),
      command jsonb NOT NULL,
      calculation jsonb NOT NULL,
      preview jsonb NOT NULL,
      posting jsonb NOT NULL,
      basis_digest text NOT NULL CHECK (basis_digest ~ '^[0-9a-f]{64}$'),
      digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
      actor text NOT NULL CHECK (length(btrim(actor)) > 0),
      UNIQUE (organization_id, request_key),
      CHECK (jsonb_typeof(command) = 'object'
        AND jsonb_typeof(command->'command_version') = 'number'
        AND command->'command_version' = '3'::jsonb
        AND jsonb_typeof(command->'material_outputs') = 'array')
    );
    CREATE TABLE accounting.late_pool_output_cost_link (
      package_id integer NOT NULL REFERENCES accounting.late_pool_package(id),
      output_entry_id integer NOT NULL REFERENCES accounting.entry(id),
      output_revision_id integer NOT NULL UNIQUE REFERENCES accounting.production_output_cost_revision(id),
      amount numeric NOT NULL CHECK (amount <> 0 AND amount * 100 = trunc(amount * 100)),
      evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
      origins jsonb NOT NULL CHECK (jsonb_typeof(origins) = 'array'
        AND jsonb_array_length(origins) > 0),
      PRIMARY KEY (package_id, output_entry_id)
    );

    CREATE OR REPLACE FUNCTION accounting.check_late_cost_complete() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
      SELECT * INTO e FROM accounting.entry WHERE id=target;
      IF e.operation IS DISTINCT FROM 'inventory_late_cost' THEN RETURN NULL; END IF;
      IF e.rule_version='late-cost-pool-v3' THEN
        IF NOT EXISTS (SELECT 1 FROM accounting.source_control c
          WHERE c.organization_id=e.organization_id AND c.source=e.source
            AND c.version=e.source_version AND c.entry_id=e.id) THEN
          RAISE EXCEPTION 'Late cost entry requires its complete receipt and source control';
        END IF;
        PERFORM accounting.verify_late_pool_package(
          (SELECT id FROM accounting.late_pool_package WHERE late_entry_id=target));
        RETURN NULL;
      END IF;
      SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
      IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM accounting.source_control c
        WHERE c.organization_id=e.organization_id AND c.source=e.source
          AND c.version=e.source_version AND c.entry_id=e.id) THEN
        RAISE EXCEPTION 'Late cost entry requires its complete receipt and source control';
      END IF;
      PERFORM procurement.check_additional_expense(r.expense_id);
      PERFORM accounting.verify_late_cost_lines(target);
      RETURN NULL;
    END $$;

    CREATE FUNCTION accounting.verify_late_pool_package(target integer) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE p accounting.late_pool_package%ROWTYPE; e accounting.entry%ROWTYPE;
      expected integer; actual integer; link accounting.late_pool_output_cost_link%ROWTYPE;
      revision accounting.production_output_cost_revision%ROWTYPE; output_item jsonb;
    BEGIN
      SELECT * INTO p FROM accounting.late_pool_package WHERE id=target;
      IF p.id IS NULL THEN RAISE EXCEPTION 'V3 pool package is missing'; END IF;
      SELECT * INTO e FROM accounting.entry WHERE id=p.late_entry_id;
      IF e.id IS NULL OR e.organization_id IS DISTINCT FROM p.organization_id
        OR e.operation IS DISTINCT FROM 'inventory_late_cost'
        OR e.rule_version IS DISTINCT FROM 'late-cost-pool-v3'
        OR e.digest IS DISTINCT FROM p.digest OR e.actor IS DISTINCT FROM p.actor THEN
        RAISE EXCEPTION 'V3 pool package entry is invalid';
      END IF;
      IF p.preview->'command' IS DISTINCT FROM p.command
        OR p.preview->'calculation' IS DISTINCT FROM p.calculation
        OR p.preview->'posting' IS DISTINCT FROM p.posting
        OR p.preview->>'basis_digest' IS DISTINCT FROM p.basis_digest
        OR p.preview->>'posting_digest' IS DISTINCT FROM p.digest
        OR p.preview->>'organization_id' IS DISTINCT FROM p.organization_id::text
        OR jsonb_typeof(p.preview->'outputs') IS DISTINCT FROM 'array'
        OR accounting.posting_body_projection(p.posting) IS DISTINCT FROM
           accounting.posting_body_projection(accounting.financial_posting_body(e.id), false) THEN
        RAISE EXCEPTION 'V3 pool package evidence is incomplete';
      END IF;
      IF EXISTS (SELECT 1 FROM jsonb_array_elements(p.command->'material_outputs') item
          WHERE jsonb_typeof(item) <> 'object'
            OR jsonb_typeof(item->'output_entry_id') <> 'number'
            OR coalesce(item->>'output_entry_id', '') !~ '^[1-9][0-9]*$'
            OR jsonb_typeof(item->'amount_byn') <> 'string'
            OR coalesce(item->>'amount_byn', '') !~ '^-?[0-9]{1,16}[.][0-9]{2}$'
            OR (item->>'amount_byn')::numeric = 0)
        OR EXISTS (SELECT (item->>'output_entry_id')::integer
          FROM jsonb_array_elements(p.command->'material_outputs') item
          GROUP BY (item->>'output_entry_id')::integer HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'V3 pool package output selection is invalid';
      END IF;
      SELECT jsonb_array_length(p.command->'material_outputs') INTO expected;
      SELECT count(*) INTO actual FROM accounting.late_pool_output_cost_link
        WHERE package_id=p.id;
      IF actual <> expected THEN RAISE EXCEPTION 'V3 pool package output links are incomplete'; END IF;
      FOR link IN SELECT * FROM accounting.late_pool_output_cost_link WHERE package_id=p.id LOOP
        SELECT item INTO output_item FROM jsonb_array_elements(p.command->'material_outputs') item
          WHERE (item->>'output_entry_id')::integer=link.output_entry_id;
        SELECT * INTO revision FROM accounting.production_output_cost_revision
          WHERE id=link.output_revision_id;
        IF output_item IS NULL OR link.amount IS DISTINCT FROM (output_item->>'amount_byn')::numeric
          OR NOT EXISTS (SELECT 1 FROM accounting.entry output WHERE output.id=link.output_entry_id
                         AND output.organization_id=p.organization_id)
          OR revision.id IS NULL OR revision.organization_id IS DISTINCT FROM p.organization_id
          OR revision.original_entry_id IS DISTINCT FROM link.output_entry_id
          OR revision.entry_id IS NULL OR revision.entry_id <= p.late_entry_id
          OR revision.actor IS DISTINCT FROM p.actor
          OR link.evidence IS DISTINCT FROM (SELECT item->'prospective_evidence'
              FROM jsonb_array_elements(p.preview->'outputs') item
              WHERE (item->>'output_entry_id')::integer=link.output_entry_id)
          OR link.evidence IS DISTINCT FROM revision.preview::jsonb->'ledger_evidence'
          OR EXISTS (SELECT 1 FROM jsonb_array_elements(link.origins) origin
              WHERE jsonb_typeof(origin) <> 'object'
                OR coalesce(origin->>'source_entry_id', '') !~ '^[1-9][0-9]*$'
                OR coalesce(origin->>'source_line_id', '') !~ '^[1-9][0-9]*$'
                OR coalesce(origin->>'amount_byn', '') !~ '^-?[0-9]{1,16}[.][0-9]{2}$'
                OR NOT EXISTS (SELECT 1 FROM accounting.line source_line
                  JOIN accounting.entry source_entry ON source_entry.id=source_line.entry_id
                  WHERE source_line.id=(origin->>'source_line_id')::integer
                    AND source_line.entry_id=(origin->>'source_entry_id')::integer
                    AND source_entry.organization_id=p.organization_id))
          OR link.amount IS DISTINCT FROM (SELECT sum((origin->>'amount_byn')::numeric)
              FROM jsonb_array_elements(link.origins) origin) THEN
          RAISE EXCEPTION 'V3 pool output link differs from its immutable package';
        END IF;
      END LOOP;
    END $$;

    CREATE FUNCTION accounting.complete_late_pool_package() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME='late_pool_package' THEN
        PERFORM accounting.verify_late_pool_package(NEW.id);
      ELSE
        PERFORM accounting.verify_late_pool_package(NEW.package_id);
      END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER complete_late_pool_package
      AFTER INSERT ON accounting.late_pool_package DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_pool_package();
    CREATE CONSTRAINT TRIGGER complete_late_pool_link
      AFTER INSERT ON accounting.late_pool_output_cost_link DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_pool_package();

    CREATE FUNCTION accounting.reject_late_pool_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'V3 pool package is immutable'; END $$;
    CREATE TRIGGER immutable_late_pool_package BEFORE UPDATE OR DELETE OR TRUNCATE
      ON accounting.late_pool_package FOR EACH STATEMENT
      EXECUTE FUNCTION accounting.reject_late_pool_mutation();
    CREATE TRIGGER immutable_late_pool_link BEFORE UPDATE OR DELETE OR TRUNCATE
      ON accounting.late_pool_output_cost_link FOR EACH STATEMENT
      EXECUTE FUNCTION accounting.reject_late_pool_mutation();
    """)


def downgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION accounting.check_late_cost_complete() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE target integer; e accounting.entry%ROWTYPE; r accounting.late_cost_receipt%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='entry' THEN target:=NEW.id; ELSE target:=NEW.entry_id; END IF;
      SELECT * INTO e FROM accounting.entry WHERE id=target;
      IF e.operation IS DISTINCT FROM 'inventory_late_cost' THEN RETURN NULL; END IF;
      SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
      IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM accounting.source_control c
        WHERE c.organization_id=e.organization_id AND c.source=e.source
          AND c.version=e.source_version AND c.entry_id=e.id) THEN
        RAISE EXCEPTION 'Late cost entry requires its complete receipt and source control';
      END IF;
      PERFORM procurement.check_additional_expense(r.expense_id);
      PERFORM accounting.verify_late_cost_lines(target);
      RETURN NULL;
    END $$;
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM accounting.late_pool_package) THEN
        RAISE EXCEPTION 'Cannot downgrade V3 pool package history';
      END IF;
    END $$;
    DROP TABLE accounting.late_pool_output_cost_link;
    DROP TABLE accounting.late_pool_package;
    DROP FUNCTION accounting.complete_late_pool_package();
    DROP FUNCTION accounting.verify_late_pool_package(integer);
    DROP FUNCTION accounting.reject_late_pool_mutation();
    """)
