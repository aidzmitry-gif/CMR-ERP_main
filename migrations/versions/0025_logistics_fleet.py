"""logistics: парк машин перевозчиков и пригодность груза (Блок 2)

Таблицы ``carrier_vehicle`` (какие машины у перевозчика) и
``carrier_cargo_capability`` (какие грузы он возит: категория + допуски/лимиты).
Питают подбор пригодного перевозчика (``fleet.eligible_carriers``) и таргет
рассылки тендера. Новые таблицы, наполняются seed-эндпоинтом ``/fleet/seed``.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carrier_vehicle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("vehicle_class", sa.String(64), nullable=False),
        sa.Column("capacity_kg", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("volume_m3", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("temp_control", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )

    op.create_table(
        "carrier_cargo_capability",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("adr", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("oversize", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("max_weight_kg", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("max_dim_cm", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("carrier_code", "category", name="uq_cargo_capability"),
        schema="logistics",
    )


def downgrade() -> None:
    op.drop_table("carrier_cargo_capability", schema="logistics")
    op.drop_table("carrier_vehicle", schema="logistics")
