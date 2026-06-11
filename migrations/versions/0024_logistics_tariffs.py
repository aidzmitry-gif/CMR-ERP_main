"""logistics: зоны, прайс-матрица тарифов, scorecard перевозчиков, аудит счетов

Блок «Стоимость и её улучшение» (BACKEND_SPEC): таблицы ``zones``, ``carrier_tariffs``,
``carrier_scorecard``, ``freight_audit_log`` в схеме ``logistics``. Новые таблицы,
наполняются идемпотентными seed-эндпоинтами. Безопасно для существующих данных.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("coverage", sa.String(255), server_default="", nullable=False),
        sa.Column("cities", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("sla_days_min", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sla_days_max", sa.Integer(), server_default="2", nullable=False),
        sa.UniqueConstraint("code", name="uq_zone_code"),
        schema="logistics",
    )

    op.create_table(
        "carrier_tariffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("zone_code", sa.String(8), nullable=False),
        sa.Column("price_w5", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_w10", sa.Numeric(10, 2), nullable=False),
        sa.Column("price_w30", sa.Numeric(10, 2), nullable=False),
        sa.Column("over30_per_kg", sa.Numeric(10, 2), nullable=False),
        sa.Column("pickup_fee", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("cod_pct", sa.Numeric(5, 3), server_default="0", nullable=False),
        sa.Column("insurance_pct", sa.Numeric(5, 3), server_default="0", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.UniqueConstraint("carrier_code", "zone_code", "effective_from", name="uq_tariff"),
        schema="logistics",
    )

    op.create_table(
        "carrier_scorecard",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("otd_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("otif_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("damage_free_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("billing_accuracy_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("claims_ratio_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("cost_per_delivery", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("shipments", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Numeric(5, 1), server_default="0", nullable=False),
        sa.Column("grade", sa.String(2), server_default="C", nullable=False),
        sa.UniqueConstraint("carrier_code", "period", name="uq_scorecard"),
        schema="logistics",
    )

    op.create_table(
        "freight_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipment_code", sa.String(64), nullable=False),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("invoice_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("expected_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("variance", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(255), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )


def downgrade() -> None:
    op.drop_table("freight_audit_log", schema="logistics")
    op.drop_table("carrier_scorecard", schema="logistics")
    op.drop_table("carrier_tariffs", schema="logistics")
    op.drop_table("zones", schema="logistics")
