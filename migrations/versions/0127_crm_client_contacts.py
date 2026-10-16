"""Numeric CRM client contacts; local reservation CRM-READY-001-migration-0127.md."""
import sqlalchemy as sa
from alembic import op

revision = "0127"
down_revision = "0126"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_client_contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crm_client_id", sa.Integer(), sa.ForeignKey("sales.crm_client.id"), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(64)),
        sa.Column("email", sa.String(255)),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("contact_key", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("crm_client_id", "request_key", name="uq_crm_contact_request"),
        sa.UniqueConstraint("crm_client_id", "contact_key", name="uq_crm_contact_exact"),
        schema="sales",
    )
    op.create_index("ix_sales_crm_client_contact_crm_client_id", "crm_client_contact", ["crm_client_id"], schema="sales")
    op.create_index("uq_crm_contact_primary", "crm_client_contact", ["crm_client_id"],
                    unique=True, schema="sales", postgresql_where=sa.text("is_primary"))


def downgrade():
    op.drop_table("crm_client_contact", schema="sales")
