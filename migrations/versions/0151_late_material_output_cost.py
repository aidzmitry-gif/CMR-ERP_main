"""Bind an atomic late material package to its output-cost revision."""
import runpy
from pathlib import Path

from alembic import op

revision = "0151"
down_revision = "0150"
branch_labels = None
depends_on = None


def prospective_evidence_definition():
    """Reuse the frozen 0150 calculation without registering hypothetical rows."""
    previous = runpy.run_path(str(Path(__file__).with_name("0147_zero_value_allocation_runtime.py")))
    definitions = previous["cost_definitions"]()
    legacy = "z.command::jsonb->>'command_version' IS DISTINCT FROM '4'"
    if definitions.count(legacy) != 1:
        raise RuntimeError("0151 legacy stream anchor changed")
    definitions = definitions.replace(legacy, "coalesce(z.command::jsonb->>'command_version','') NOT IN ('4','5')")
    sql = previous["_function"](definitions, "output_cost_revision_evidence")
    sql = sql.replace("accounting.output_cost_revision_evidence(", "accounting.preview_output_cost_with_wip(", 1)
    signature = "org integer, output_id integer, cutoff date, excluded_entry integer"
    if sql.count(signature) != 1:
        raise RuntimeError("0151 evidence signature changed")
    sql = sql.replace(signature, signature + ", prospective jsonb", 1)
    anchor = "  SELECT coalesce(jsonb_agg(jsonb_build_object('dimensions', dims, 'amount', amount)"
    if sql.count(anchor) != 1:
        raise RuntimeError("0151 source aggregation anchor changed")
    overlay = """
  IF prospective IS NULL OR jsonb_typeof(prospective)<>'array' OR jsonb_array_length(prospective)=0 THEN
    RAISE EXCEPTION 'Prospective WIP debits must be a nonempty array';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(prospective) p WHERE
    jsonb_typeof(p)<>'object' OR p->>'account' IS DISTINCT FROM wip
    OR jsonb_typeof(p->'dimensions') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p->'amount_byn') IS DISTINCT FROM 'string'
    OR coalesce(p->>'amount_byn','') !~ '^[0-9]{1,16}\\.[0-9]{2}$'
  ) THEN RAISE EXCEPTION 'Invalid prospective WIP debit'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(prospective) p WHERE
    (p->>'amount_byn')::numeric<=0
    OR p->'dimensions'->>order_key IS DISTINCT FROM order_value
    OR (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_object_keys(p->'dimensions') k)
       IS DISTINCT FROM (SELECT jsonb_agg(k ORDER BY k) FROM jsonb_array_elements_text(required_keys) k)
    OR EXISTS (SELECT 1 FROM jsonb_each(p->'dimensions') d WHERE
       jsonb_typeof(d.value)<>'string' OR btrim(d.value#>>'{}')='')
  ) THEN RAISE EXCEPTION 'Prospective WIP analytic source differs from output'; END IF;
  source_rows := source_rows || (SELECT jsonb_agg(jsonb_build_object(
    'prospective',true,'posting_date',cutoff,'account',wip,'side','debit',
    'amount',(p->>'amount_byn')::numeric,'dimensions',p->'dimensions') ORDER BY ord)
    FROM jsonb_array_elements(prospective) WITH ORDINALITY t(p,ord));
  source_cost := source_cost + (SELECT sum((p->>'amount_byn')::numeric)
    FROM jsonb_array_elements(prospective) p);
"""
    return sql.replace(anchor, overlay + anchor, 1)


def upgrade():
    op.execute(prospective_evidence_definition())
    op.execute("""
    CREATE TABLE accounting.late_material_package (
      late_entry_id integer PRIMARY KEY REFERENCES accounting.late_cost_receipt(entry_id),
      organization_id integer NOT NULL REFERENCES accounting.organization(id),
      basis_digest text NOT NULL CHECK (basis_digest ~ '^[0-9a-f]{64}$'),
      preview jsonb NOT NULL
    );
    CREATE TABLE accounting.late_material_output_cost_link (
      late_entry_id integer NOT NULL REFERENCES accounting.late_material_package(late_entry_id),
      output_revision_id integer NOT NULL UNIQUE REFERENCES accounting.production_output_cost_revision(id),
      organization_id integer NOT NULL REFERENCES accounting.organization(id),
      output_entry_id integer NOT NULL REFERENCES accounting.entry(id),
      amount numeric NOT NULL CHECK (amount>0 AND amount*100=trunc(amount*100)),
      digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
      source jsonb NOT NULL,
      PRIMARY KEY (late_entry_id, output_entry_id)
    );
    CREATE FUNCTION accounting.verify_late_material_package(target integer) RETURNS void LANGUAGE plpgsql AS $$
    DECLARE r accounting.late_cost_receipt; p accounting.late_material_package;
      e accounting.entry; l record; expected jsonb; declared jsonb; derived jsonb;
    BEGIN
      SELECT * INTO r FROM accounting.late_cost_receipt WHERE entry_id=target;
      IF r.entry_id IS NULL THEN RAISE EXCEPTION 'Late material receipt is missing'; END IF;
      IF r.command::jsonb->>'command_version' IS DISTINCT FROM '2' THEN
        IF EXISTS(SELECT 1 FROM accounting.late_material_package WHERE late_entry_id=target)
          OR EXISTS(SELECT 1 FROM accounting.line WHERE entry_id=target AND split_part(account_code,'.',1)='20') THEN
          RAISE EXCEPTION 'Material package requires versioned command';
        END IF;
        RETURN;
      END IF;
      SELECT * INTO p FROM accounting.late_material_package WHERE late_entry_id=target;
      SELECT * INTO e FROM accounting.entry WHERE id=target;
      IF p.late_entry_id IS NULL OR p.organization_id IS DISTINCT FROM r.organization_id
        OR p.preview->'command' IS DISTINCT FROM r.command::jsonb
        OR p.preview->'calculation' IS DISTINCT FROM r.calculation::jsonb
        OR p.preview->'posting' IS DISTINCT FROM r.posting::jsonb
        OR p.preview->>'posting_digest' IS DISTINCT FROM r.digest
        OR p.preview->>'basis_digest' IS DISTINCT FROM p.basis_digest
        OR p.preview->>'organization_id' IS DISTINCT FROM r.organization_id::text
        OR jsonb_typeof(p.preview->'outputs') IS DISTINCT FROM 'array'
        OR jsonb_typeof(r.command::jsonb->'material_outputs') IS DISTINCT FROM 'array'
      THEN RAISE EXCEPTION 'Late material package evidence is incomplete'; END IF;
      SELECT coalesce(jsonb_agg(jsonb_build_object('output_entry_id',o->'output_entry_id','amount_byn',o->'amount_byn')
        ORDER BY (o->>'output_entry_id')::integer),'[]') INTO declared FROM jsonb_array_elements(p.preview->'outputs') o;
      IF declared IS DISTINCT FROM r.command::jsonb->'material_outputs' THEN
        RAISE EXCEPTION 'Material output selection differs from package'; END IF;
      IF EXISTS (
        WITH actual AS (SELECT account_code a,dimensions::jsonb d,sum(amount) n FROM accounting.line
            WHERE entry_id=target AND side='debit' AND split_part(account_code,'.',1)='20'
            GROUP BY account_code,dimensions::jsonb),
        origins AS (SELECT o->>'expense_account' a,o->'expense_dimensions' d,sum((o->>'amount_byn')::numeric) n
            FROM jsonb_array_elements(r.calculation::jsonb->'shares') share
            CROSS JOIN LATERAL jsonb_array_elements(coalesce(share->'production_origins','[]')) o
            WHERE share->>'destination'='production' AND (o->>'amount_byn')::numeric>0
            GROUP BY o->>'expense_account',o->'expense_dimensions')
        (SELECT * FROM actual EXCEPT ALL SELECT * FROM origins)
        UNION ALL (SELECT * FROM origins EXCEPT ALL SELECT * FROM actual)
      ) THEN RAISE EXCEPTION 'Material origins differ from actual WIP debits'; END IF;
      IF EXISTS (SELECT 1 FROM accounting.line w WHERE w.entry_id=target AND w.side='debit'
          AND split_part(w.account_code,'.',1)='20' AND (SELECT count(*) FROM accounting.production_output_transfer_receipt out
            WHERE out.organization_id=r.organization_id AND out.entry_id<target
              AND EXISTS(SELECT 1 FROM accounting.line c WHERE c.entry_id=out.entry_id AND c.side='credit'
                AND c.account_code=w.account_code AND c.dimensions::jsonb=w.dimensions::jsonb))>1)
      THEN RAISE EXCEPTION 'WIP debits identify ambiguous output origins'; END IF;
      SELECT coalesce(jsonb_agg(jsonb_build_object('output_entry_id',output_id,'amount_byn',to_char(amount,'FM9999999999999990.00')) ORDER BY output_id),'[]')
      INTO derived FROM (
        SELECT out.entry_id output_id,sum(w.amount) amount
        FROM accounting.line w
        JOIN accounting.production_output_transfer_receipt out ON out.organization_id=r.organization_id AND out.entry_id<target
          AND EXISTS(SELECT 1 FROM accounting.line c WHERE c.entry_id=out.entry_id AND c.side='credit'
            AND c.account_code=w.account_code AND c.dimensions::jsonb=w.dimensions::jsonb)
        WHERE w.entry_id=target AND w.side='debit' AND split_part(w.account_code,'.',1)='20'
        GROUP BY out.entry_id
      ) q;
      IF declared IS DISTINCT FROM derived THEN RAISE EXCEPTION 'Material package omits or changes a released output'; END IF;
      IF (SELECT count(*) FROM accounting.late_material_output_cost_link WHERE late_entry_id=target)
         <> jsonb_array_length(declared) THEN RAISE EXCEPTION 'Late material output links are incomplete'; END IF;
      FOR l IN SELECT link.*,rev.entry_id revision_entry,rev.original_entry_id,rev.actor,rev.preview revision_preview,
          rev.organization_id revision_org,rev.command revision_command
        FROM accounting.late_material_output_cost_link link
        JOIN accounting.production_output_cost_revision rev ON rev.id=link.output_revision_id
        WHERE link.late_entry_id=target
      LOOP
        SELECT o INTO expected FROM jsonb_array_elements(p.preview->'outputs') o WHERE (o->>'output_entry_id')::integer=l.output_entry_id;
        IF expected IS NULL OR l.source IS DISTINCT FROM expected OR l.organization_id<>r.organization_id
          OR l.revision_org<>r.organization_id OR l.original_entry_id<>l.output_entry_id
          OR l.revision_entry IS NULL OR l.revision_entry<=target OR l.actor IS DISTINCT FROM r.actor
          OR l.digest IS DISTINCT FROM r.digest OR l.amount IS DISTINCT FROM (expected->>'amount_byn')::numeric
          OR l.revision_command->>'posting_date' IS DISTINCT FROM e.posting_date::text
        THEN RAISE EXCEPTION 'Late material output link differs from reviewed package'; END IF;
        IF EXISTS (
          WITH forecast AS (SELECT x->>'account' a,x->>'side' s,x->'dimensions' d,(x->>'amount')::numeric n
              FROM jsonb_array_elements(expected->'prospective_evidence'->'matrix') x),
          actual AS (SELECT x->>'account' a,x->>'side' s,x->'dimensions' d,(x->>'amount')::numeric n
              FROM jsonb_array_elements(l.revision_preview::jsonb->'ledger_evidence'->'matrix') x)
          (SELECT * FROM forecast EXCEPT ALL SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM forecast)
        ) THEN RAISE EXCEPTION 'Output revision matrix differs from late material preview'; END IF;
      END LOOP;
    END $$;
    CREATE FUNCTION accounting.complete_late_material_package() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME='late_cost_receipt' THEN
        PERFORM accounting.verify_late_material_package(NEW.entry_id);
      ELSE PERFORM accounting.verify_late_material_package(NEW.late_entry_id); END IF;
      RETURN NULL;
    END $$;
    CREATE CONSTRAINT TRIGGER complete_material_receipt AFTER INSERT ON accounting.late_cost_receipt
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_material_package();
    CREATE CONSTRAINT TRIGGER complete_material_package AFTER INSERT ON accounting.late_material_package
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_material_package();
    CREATE CONSTRAINT TRIGGER complete_material_link AFTER INSERT ON accounting.late_material_output_cost_link
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION accounting.complete_late_material_package();
    CREATE TRIGGER immutable_material_package BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.late_material_package
      FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_late_cost_receipt_mutation();
    CREATE TRIGGER immutable_material_link BEFORE UPDATE OR DELETE OR TRUNCATE ON accounting.late_material_output_cost_link
      FOR EACH STATEMENT EXECUTE FUNCTION accounting.reject_late_cost_receipt_mutation();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM accounting.late_material_package) THEN
      RAISE EXCEPTION 'Cannot downgrade late material packages with history'; END IF; END $$;
    DROP TRIGGER complete_material_receipt ON accounting.late_cost_receipt;
    DROP TABLE accounting.late_material_output_cost_link;
    DROP TABLE accounting.late_material_package;
    DROP FUNCTION accounting.complete_late_material_package();
    DROP FUNCTION accounting.verify_late_material_package(integer);
    DROP FUNCTION accounting.preview_output_cost_with_wip(integer,integer,date,integer,jsonb,integer);
    """)
