"""Default-off warehouse execution, with immutable per-operation mode evidence."""
from alembic import op

revision = "crm_rel_001_wms_mode_01"
down_revision = "0193"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE wms.warehouse_directory ADD COLUMN wms_enabled BOOLEAN NOT NULL DEFAULT FALSE")
    # NULL is reserved for rows predating this migration. Do not rewrite history.
    op.execute("ALTER TABLE wms.invoice_reservation ADD COLUMN execution_modes JSONB")
    op.execute("""
    CREATE FUNCTION wms.validate_reservation_execution_modes() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE place text; enabled boolean;
    BEGIN
      IF jsonb_typeof(NEW.execution_modes) IS DISTINCT FROM 'object'
         OR jsonb_typeof(NEW.snapshot::jsonb->'allocations') IS DISTINCT FROM 'array'
         OR jsonb_array_length(NEW.snapshot::jsonb->'allocations') = 0 THEN
        RAISE EXCEPTION 'New reservations require explicit warehouse execution modes';
      END IF;
      IF EXISTS (
        SELECT key FROM jsonb_object_keys(NEW.execution_modes) AS keys(key)
        EXCEPT SELECT a->>'warehouse' FROM jsonb_array_elements(NEW.snapshot::jsonb->'allocations') a
      ) OR EXISTS (
        SELECT a->>'warehouse' FROM jsonb_array_elements(NEW.snapshot::jsonb->'allocations') a
        EXCEPT SELECT key FROM jsonb_object_keys(NEW.execution_modes) AS keys(key)
      ) THEN
        RAISE EXCEPTION 'Reservation execution modes must match all allocated warehouses';
      END IF;
      PERFORM id FROM accounting.organization WHERE id=NEW.organization_id FOR UPDATE;
      FOR place IN SELECT key FROM jsonb_object_keys(NEW.execution_modes) AS keys(key) ORDER BY key LOOP
        IF jsonb_typeof(NEW.execution_modes->place) IS DISTINCT FROM 'boolean' THEN
          RAISE EXCEPTION 'Warehouse execution mode must be boolean';
        END IF;
        SELECT wms_enabled INTO enabled FROM wms.warehouse_directory
          WHERE organization_id=NEW.organization_id AND name=place AND is_active FOR UPDATE;
        IF NOT FOUND OR NEW.execution_modes->place IS DISTINCT FROM to_jsonb(enabled) THEN
          RAISE EXCEPTION 'Warehouse execution mode is unknown or changed';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE TRIGGER reservation_execution_modes_insert BEFORE INSERT ON wms.invoice_reservation
      FOR EACH ROW EXECUTE FUNCTION wms.validate_reservation_execution_modes();

    CREATE FUNCTION wms.validate_shipment_execution_mode() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE modes jsonb; item jsonb; enabled boolean; origin text;
    BEGIN
      SELECT execution_modes INTO modes FROM wms.invoice_reservation
        WHERE document_id=NEW.document_id AND organization_id=NEW.organization_id;
      IF NOT FOUND THEN RAISE EXCEPTION 'Shipment reservation is missing'; END IF;
      origin := NEW.snapshot::jsonb->>'execution_mode';
      IF origin IS NULL OR origin NOT IN ('document', 'wms')
         OR jsonb_typeof(NEW.snapshot::jsonb->'lines') IS DISTINCT FROM 'array'
         OR jsonb_array_length(NEW.snapshot::jsonb->'lines')=0 THEN
        RAISE EXCEPTION 'Shipment requires trusted execution mode evidence';
      END IF;
      FOR item IN SELECT value FROM jsonb_array_elements(NEW.snapshot::jsonb->'lines') LOOP
        IF modes IS NULL THEN
          enabled := TRUE;
        ELSE
          IF jsonb_typeof(modes->(item->>'warehouse')) IS DISTINCT FROM 'boolean' THEN
            RAISE EXCEPTION 'Shipment warehouse has no frozen execution mode';
          END IF;
          enabled := (modes->>(item->>'warehouse'))::boolean;
        END IF;
        IF enabled IS DISTINCT FROM (origin='wms') THEN
          RAISE EXCEPTION 'Shipment origin does not match warehouse execution mode';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$;
    CREATE TRIGGER shipment_execution_mode_insert BEFORE INSERT ON wms.physical_shipment_act
      FOR EACH ROW EXECUTE FUNCTION wms.validate_shipment_execution_mode();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM wms.warehouse_directory)
         OR EXISTS (SELECT 1 FROM wms.invoice_reservation WHERE execution_modes IS NOT NULL) THEN
        RAISE EXCEPTION 'Cannot remove warehouse modes after warehouse configuration or use';
      END IF;
    END $$;
    DROP TRIGGER shipment_execution_mode_insert ON wms.physical_shipment_act;
    DROP FUNCTION wms.validate_shipment_execution_mode();
    DROP TRIGGER reservation_execution_modes_insert ON wms.invoice_reservation;
    DROP FUNCTION wms.validate_reservation_execution_modes();
    ALTER TABLE wms.invoice_reservation DROP COLUMN execution_modes;
    ALTER TABLE wms.warehouse_directory DROP COLUMN wms_enabled;
    """)
