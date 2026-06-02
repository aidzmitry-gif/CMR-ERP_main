"""core: shared kernel (контрагент, контакт, SKU, пользователь)

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparty",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unp", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["counterparty_id"], ["counterparty.id"],
            name=op.f("fk_contact_counterparty_id_counterparty"),
        ),
    )
    op.create_table(
        "sku",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=16), server_default="шт", nullable=False),
        sa.UniqueConstraint("code", name=op.f("uq_sku_code")),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.UniqueConstraint("username", name=op.f("uq_app_user_username")),
    )


def downgrade() -> None:
    op.drop_table("app_user")
    op.drop_table("sku")
    op.drop_table("contact")
    op.drop_table("counterparty")
