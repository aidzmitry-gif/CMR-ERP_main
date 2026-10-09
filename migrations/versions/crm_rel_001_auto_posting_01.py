"""Explicit versioned automatic document accounts; existing policies stay NULL."""
from alembic import op

revision = "crm_rel_001_auto_posting_01"
down_revision = "crm_rel_001_native_docs_01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE accounting.policy ADD COLUMN document_posting JSONB")


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting.policy WHERE document_posting IS NOT NULL) THEN
        RAISE EXCEPTION 'Cannot downgrade configured automatic document policies';
      END IF;
    END $$;
    ALTER TABLE accounting.policy DROP COLUMN document_posting;
    """)
