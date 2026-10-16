"""Allow one audited revocation without changing historical contract identity."""

import sqlalchemy as sa
from alembic import op

revision = "0186"
down_revision = "0185"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("supplier_contract", sa.Column("deactivated_by", sa.String(length=200)), schema="procurement")
    op.add_column("supplier_contract", sa.Column("deactivated_at", sa.DateTime(timezone=True)), schema="procurement")
    op.add_column("supplier_contract", sa.Column("deactivation_reason", sa.String(length=500)), schema="procurement")
    op.add_column("supplier_contract", sa.Column("deactivation_key", sa.String(length=36)), schema="procurement")
    op.drop_constraint("uq_supplier_contract_identity", "supplier_contract", schema="procurement", type_="unique")
    op.create_index("uq_supplier_contract_active_identity", "supplier_contract",
                    ["organization_id", "supplier_id", "number"], schema="procurement",
                    unique=True, postgresql_where=sa.text("is_active"))
    op.execute("""
        CREATE OR REPLACE FUNCTION procurement.guard_supplier_contract() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'Supplier contract identity is append-only';
          END IF;
          IF OLD.is_active IS DISTINCT FROM TRUE OR NEW.is_active IS DISTINCT FROM FALSE
             OR NEW.id IS DISTINCT FROM OLD.id
             OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
             OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
             OR NEW.number IS DISTINCT FROM OLD.number
             OR NEW.title IS DISTINCT FROM OLD.title
             OR NEW.signed_on IS DISTINCT FROM OLD.signed_on
             OR NEW.expires_on IS DISTINCT FROM OLD.expires_on
             OR NEW.evidence IS DISTINCT FROM OLD.evidence
             OR NEW.created_by IS DISTINCT FROM OLD.created_by
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR OLD.deactivated_by IS NOT NULL OR OLD.deactivated_at IS NOT NULL
             OR OLD.deactivation_reason IS NOT NULL OR OLD.deactivation_key IS NOT NULL
             OR NEW.deactivated_by IS NULL OR length(trim(NEW.deactivated_by)) = 0
             OR NEW.deactivated_at IS NULL
             OR NEW.deactivation_reason IS NULL OR length(trim(NEW.deactivation_reason)) = 0
             OR NEW.deactivation_key IS NULL OR length(NEW.deactivation_key) <> 36 THEN
            RAISE EXCEPTION 'Supplier contract can only be revoked once with audit evidence';
          END IF;
          RETURN NEW;
        END $$
    """)


def downgrade():
    raise RuntimeError("Supplier contract revocation history cannot be discarded")
