"""Default-on warehouse negative-stock prohibition; scoped audited override."""
from alembic import op

revision = "0194"
down_revision = "crm_rel_001_wms_mode_01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE wms.warehouse_directory ADD COLUMN prohibit_negative_stock BOOLEAN NOT NULL DEFAULT TRUE")


def downgrade():
    # Older code always prohibits negative stock; an enabled exception cannot be
    # silently discarded during a schema rollback.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM wms.warehouse_directory WHERE NOT prohibit_negative_stock) THEN
        RAISE EXCEPTION 'Disable negative-stock exceptions before removing the policy';
      END IF;
    END $$""")
    op.execute("ALTER TABLE wms.warehouse_directory DROP COLUMN prohibit_negative_stock")
