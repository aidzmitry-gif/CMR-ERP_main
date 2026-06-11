"""production: нормо-часы на нарядах + справочник норм

Аддитивные колонки к ``production.production_order`` (``nh_per_unit``,
``made_qty`` — с ``server_default``, безопасно для существующих строк)
и новая таблица ``production.production_norm`` — справочник норм
нормо-часов на изделия/операции со статусами утверждения
(none → pending → approved), как на экране «Нормы и нормативы».

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_order",
        sa.Column("nh_per_unit", sa.Float(), server_default="0", nullable=False),
        schema="production",
    )
    op.add_column(
        "production_order",
        sa.Column("made_qty", sa.Integer(), server_default="0", nullable=False),
        schema="production",
    )
    op.create_table(
        "production_norm",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), server_default="product", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("nh", sa.Float(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("note", sa.String(length=400), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("production_norm", schema="production")
    op.drop_column("production_order", "made_qty", schema="production")
    op.drop_column("production_order", "nh_per_unit", schema="production")
