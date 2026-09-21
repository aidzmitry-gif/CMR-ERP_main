"""Add explicit TN/TTN scenarios to versioned accounting policy."""
from alembic import op

revision = "0159"
down_revision = "0158"
branch_labels = None
depends_on = None


def upgrade():
    # NULL means not configured.  No default scenario may be inferred from
    # a WMS act, sales document, or an earlier accounting policy version.
    op.execute("ALTER TABLE accounting.policy ADD COLUMN shipment_documents JSONB")


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.policy WHERE shipment_documents IS NOT NULL) THEN
        RAISE EXCEPTION 'Cannot downgrade configured shipment document policies';
      END IF;
    END $$;
    ALTER TABLE accounting.policy DROP COLUMN shipment_documents;
    """)
