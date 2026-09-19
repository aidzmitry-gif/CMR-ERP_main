"""Independent CRM clients; local reservation CRM-READY-001-migration-0126.md."""
import sqlalchemy as sa
from alembic import op

revision = "0126"
down_revision = "0123"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "crm_client",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("name_key", sa.String(1024), nullable=False),
        sa.Column("unp", sa.String(9)),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("counterparty_id", sa.Integer(), sa.ForeignKey("counterparty.id")),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_crm_client_owner_request"),
        sa.UniqueConstraint("owner_id", "name_key", name="uq_crm_client_owner_name"),
        sa.UniqueConstraint("owner_id", "unp", name="uq_crm_client_owner_unp"),
        schema="sales",
    )
    op.create_index("ix_sales_crm_client_owner_id", "crm_client", ["owner_id"], schema="sales")
    op.add_column("deal", sa.Column("crm_client_id", sa.Integer()), schema="sales")
    op.create_foreign_key("fk_deal_crm_client_id_crm_client", "deal", "crm_client",
                          ["crm_client_id"], ["id"], source_schema="sales", referent_schema="sales")
    op.create_index("ix_sales_deal_crm_client_id", "deal", ["crm_client_id"], schema="sales")


def downgrade():
    op.drop_index("ix_sales_deal_crm_client_id", table_name="deal", schema="sales")
    op.drop_constraint("fk_deal_crm_client_id_crm_client", "deal", schema="sales", type_="foreignkey")
    op.drop_column("deal", "crm_client_id", schema="sales")
    op.drop_table("crm_client", schema="sales")
