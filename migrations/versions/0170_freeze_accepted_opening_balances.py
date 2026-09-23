"""Freeze opening entries once their import receipt is accepted."""

from alembic import op

revision = "0170"
down_revision = "0169"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM accounting.opening_import_receipt r
        WHERE (SELECT count(DISTINCT ids.value::bigint)
               FROM jsonb_array_elements_text(r.entry_ids::jsonb) ids(value)) <> r.entry_count
           OR EXISTS (
             SELECT 1 FROM accounting.entry e
             WHERE e.organization_id = r.organization_id AND e.opening
               AND NOT EXISTS (
                 SELECT 1 FROM jsonb_array_elements_text(r.entry_ids::jsonb) ids(value)
                 WHERE ids.value::bigint = e.id
               )
           )
      ) THEN
        RAISE EXCEPTION 'Existing opening entries are outside an accepted import; reconcile before upgrade';
      END IF;
    END $$;

    CREATE OR REPLACE FUNCTION accounting.guard_opening_entry_after_receipt()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.opening THEN
        PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
        IF EXISTS (
          SELECT 1 FROM accounting.opening_import_receipt
          WHERE organization_id = NEW.organization_id
        ) THEN
          RAISE EXCEPTION 'Opening balances are frozen after the accepted import';
        END IF;
      END IF;
      RETURN NEW;
    END $$;

    CREATE TRIGGER opening_entry_after_receipt_guard
    BEFORE INSERT ON accounting.entry
    FOR EACH ROW EXECUTE FUNCTION accounting.guard_opening_entry_after_receipt();

    CREATE OR REPLACE FUNCTION accounting.guard_opening_import_complete()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      IF (SELECT count(DISTINCT ids.value::bigint)
          FROM jsonb_array_elements_text(NEW.entry_ids::jsonb) ids(value)) <> NEW.entry_count
         OR EXISTS (
           SELECT 1 FROM accounting.entry e
           WHERE e.organization_id = NEW.organization_id AND e.opening
             AND NOT EXISTS (
               SELECT 1 FROM jsonb_array_elements_text(NEW.entry_ids::jsonb) ids(value)
               WHERE ids.value::bigint = e.id
             )
         ) THEN
        RAISE EXCEPTION 'Opening import receipt omits or repeats opening entries';
      END IF;
      RETURN NEW;
    END $$;

    CREATE CONSTRAINT TRIGGER opening_import_receipt_z_complete_guard
    AFTER INSERT ON accounting.opening_import_receipt
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
    EXECUTE FUNCTION accounting.guard_opening_import_complete();
    """)


def downgrade():
    op.execute("""
    DROP TRIGGER opening_import_receipt_z_complete_guard ON accounting.opening_import_receipt;
    DROP FUNCTION accounting.guard_opening_import_complete();
    DROP TRIGGER opening_entry_after_receipt_guard ON accounting.entry;
    DROP FUNCTION accounting.guard_opening_entry_after_receipt();
    """)
