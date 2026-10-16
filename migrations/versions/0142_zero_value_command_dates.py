"""Validate versioned zero-value disposal command dates."""
from alembic import op

revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None

DDL = r"""
CREATE OR REPLACE FUNCTION accounting.validate_zero_value_disposal_command(c jsonb) RETURNS void LANGUAGE plpgsql AS $$
DECLARE field text; value text; parsed date;
BEGIN
  IF jsonb_typeof(c) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Zero-value command must be an object'; END IF;
  IF c ? 'command_version' THEN
    IF jsonb_typeof(c->'command_version') IS DISTINCT FROM 'number' OR c->>'command_version' IS DISTINCT FROM '2'
       OR c->'command_version'::text IS DISTINCT FROM '2' THEN
      RAISE EXCEPTION 'Zero-value command version must be integer 2';
    END IF;
    FOREACH field IN ARRAY ARRAY['document_date','operation_date'] LOOP
      IF jsonb_typeof(c->field) IS DISTINCT FROM 'string' OR c->>field !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        RAISE EXCEPTION 'Zero-value command date is invalid';
      END IF;
      value := c->>field;
      BEGIN parsed := value::date; EXCEPTION WHEN others THEN RAISE EXCEPTION 'Zero-value command date is invalid'; END;
      IF to_char(parsed,'YYYY-MM-DD') IS DISTINCT FROM value THEN RAISE EXCEPTION 'Zero-value command date is invalid'; END IF;
    END LOOP;
  ELSIF c ? 'document_date' OR c ? 'operation_date' THEN
    RAISE EXCEPTION 'Legacy zero-value command must not contain dated fields';
  END IF;
END $$;
CREATE OR REPLACE FUNCTION accounting.guard_zero_value_disposal_command_dates() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM accounting.validate_zero_value_disposal_command(NEW.command::jsonb); RETURN NEW; END $$;
CREATE TRIGGER ab_guard_zero_value_disposal_command_dates BEFORE INSERT ON accounting.inventory_zero_value_disposal_receipt
FOR EACH ROW EXECUTE FUNCTION accounting.guard_zero_value_disposal_command_dates();
SELECT accounting.validate_zero_value_disposal_command(command::jsonb) FROM accounting.inventory_zero_value_disposal_receipt;
"""

def upgrade(): op.execute(DDL)

def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.inventory_zero_value_disposal_receipt WHERE command::jsonb ? 'command_version') THEN
        RAISE EXCEPTION 'Cannot downgrade 0142 while versioned zero-value history exists';
      END IF;
    END $$;
    DROP TRIGGER ab_guard_zero_value_disposal_command_dates ON accounting.inventory_zero_value_disposal_receipt;
    DROP FUNCTION accounting.guard_zero_value_disposal_command_dates();
    DROP FUNCTION accounting.validate_zero_value_disposal_command(jsonb);""")
