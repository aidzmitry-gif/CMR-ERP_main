"""logistics: синхронизация дрейфа — поля shipment + таблицы import_shipment, carrier

Модели logistics (LOG-6) обросли колонками и новыми таблицами (``ImportShipment``,
``Carrier``, расширенный ``Shipment``), но миграции на это не писались — на Postgres
схема рассинхронена с моделями. Эта миграция приводит схему в соответствие. Всё
аддитивно (``server_default``), безопасно для существующих строк ``logistics.shipment``.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Колонки, добавленные к logistics.shipment поверх 0015/0017 (name, type, server_default).
_SHIPMENT_COLS = [
    ("number", sa.String(64), ""),
    ("route_from", sa.String(128), ""),
    ("route_to", sa.String(128), ""),
    ("carrier_code", sa.String(32), ""),
    ("carrier_order_no", sa.String(64), ""),
    ("cargo", sa.String(255), ""),
    ("payer", sa.String(32), "компания"),
    ("priority", sa.String(32), "Средний"),
    ("owner", sa.String(128), ""),
    ("tracking_no", sa.String(64), ""),
    ("tracking_status", sa.String(128), ""),
    ("insight", sa.String(400), ""),
]


def upgrade() -> None:
    for name, type_, default in _SHIPMENT_COLS:
        op.add_column(
            "shipment", sa.Column(name, type_, server_default=default, nullable=False),
            schema="logistics",
        )
    op.add_column(
        "shipment", sa.Column("weight_kg", sa.Numeric(12, 2), server_default="0", nullable=False),
        schema="logistics",
    )
    op.add_column(
        "shipment", sa.Column("amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        schema="logistics",
    )
    op.add_column("shipment", sa.Column("eta", sa.String(32), nullable=True), schema="logistics")

    op.create_table(
        "import_shipment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("supplier", sa.String(255), nullable=False),
        sa.Column("flag", sa.String(8), server_default="🇨🇳", nullable=False),
        sa.Column("container_no", sa.String(64), server_default="", nullable=False),
        sa.Column("route", sa.String(255), server_default="", nullable=False),
        sa.Column("incoterms", sa.String(16), server_default="FOB", nullable=False),
        sa.Column("mode", sa.String(32), server_default="море", nullable=False),
        sa.Column("cargo", sa.String(255), server_default="", nullable=False),
        sa.Column("qty", sa.Integer(), server_default="0", nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("priority", sa.String(32), server_default="Средний", nullable=False),
        sa.Column("owner", sa.String(128), server_default="", nullable=False),
        sa.Column("stage", sa.String(32), server_default="factory", nullable=False),
        sa.Column("customs_status", sa.String(64), server_default="", nullable=False),
        sa.Column("eta", sa.String(32), nullable=True),
        sa.Column("po_ref", sa.String(64), server_default="", nullable=False),
        sa.Column("insight", sa.String(400), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )

    op.create_table(
        "carrier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(32), server_default="", nullable=False),
        sa.Column("kind", sa.String(32), server_default="РБ", nullable=False),
        sa.Column("mode", sa.String(32), server_default="авто", nullable=False),
        sa.Column("contact", sa.String(255), server_default="", nullable=False),
        sa.Column("integration", sa.String(16), server_default="manual", nullable=False),
        sa.Column("track_url", sa.String(255), server_default="", nullable=False),
        sa.Column("on_time_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("avg_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("shipments_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )


def downgrade() -> None:
    op.drop_table("carrier", schema="logistics")
    op.drop_table("import_shipment", schema="logistics")
    op.drop_column("shipment", "eta", schema="logistics")
    op.drop_column("shipment", "amount", schema="logistics")
    op.drop_column("shipment", "weight_kg", schema="logistics")
    for name, _type, _default in reversed(_SHIPMENT_COLS):
        op.drop_column("shipment", name, schema="logistics")
