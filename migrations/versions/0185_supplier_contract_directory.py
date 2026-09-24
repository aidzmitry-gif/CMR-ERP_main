"""Owned supplier contract references; no legacy name-based adoption.

Existing office contracts and procurement receipt revisions retain their
original facts until a user explicitly matches them to a legal entity and
supplier. This migration does not alter posted receipts.
"""

import sqlalchemy as sa
from alembic import op

revision = "0185"
down_revision = "0184"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "supplier_contract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("accounting.organization.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("procurement.supplier.id"), nullable=False),
        sa.Column("number", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("signed_on", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("evidence", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("organization_id > 0", name="supplier_contract_org_positive"),
        sa.CheckConstraint("supplier_id > 0", name="supplier_contract_supplier_positive"),
        sa.CheckConstraint("expires_on IS NULL OR expires_on >= signed_on", name="supplier_contract_valid_dates"),
        sa.UniqueConstraint("organization_id", "supplier_id", "number", name="uq_supplier_contract_identity"),
        schema="procurement",
    )
    op.create_index("ix_procurement_supplier_contract_organization_id", "supplier_contract",
                    ["organization_id"], schema="procurement")
    op.create_index("ix_procurement_supplier_contract_supplier_id", "supplier_contract",
                    ["supplier_id"], schema="procurement")
    op.execute("""
        CREATE FUNCTION procurement.guard_supplier_contract() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'Supplier contract identity is append-only';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER guard_supplier_contract
        BEFORE UPDATE OR DELETE ON procurement.supplier_contract
        FOR EACH ROW EXECUTE FUNCTION procurement.guard_supplier_contract()
    """)
    op.execute("""
        CREATE TRIGGER guard_supplier_contract_truncate
        BEFORE TRUNCATE ON procurement.supplier_contract
        FOR EACH STATEMENT EXECUTE FUNCTION procurement.guard_supplier_contract()
    """)


def downgrade():
    raise RuntimeError("Supplier contract catalogue cannot be dropped without reviewing linked receipts")
