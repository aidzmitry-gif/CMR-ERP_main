"""Reject new retroactive employment bindings after an accounting close."""
from alembic import op

revision = "0165"
down_revision = "0164"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION accounting.guard_closed_payroll_employment_insert()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      -- Serialize against accounting period closing and direct SQL inserts.
      PERFORM 1 FROM accounting.organization WHERE id = NEW.organization_id FOR UPDATE;
      IF EXISTS (
        SELECT 1 FROM accounting.period
        WHERE organization_id = NEW.organization_id
          AND month >= to_char(NEW.effective_from, 'YYYY-MM')
          AND closed IS TRUE
      ) THEN
        RAISE EXCEPTION 'Closed period blocks a new payroll employment binding';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER zz_guard_closed_payroll_employment_insert
      BEFORE INSERT ON accounting.payroll_employment_binding
      FOR EACH ROW EXECUTE FUNCTION accounting.guard_closed_payroll_employment_insert();
    """)


def downgrade():
    op.execute("""
    DROP TRIGGER zz_guard_closed_payroll_employment_insert
      ON accounting.payroll_employment_binding;
    DROP FUNCTION accounting.guard_closed_payroll_employment_insert();
    """)
