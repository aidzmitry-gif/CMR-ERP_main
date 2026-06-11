"""logistics: тендер на перевозку — RFQ, приглашения, предложения (Блок 4)

Таблицы ``carrier_rfq`` (запрос предложений на перевозку наёмным перевозчиком),
``carrier_rfq_invite`` (кому разослан тендер) и ``carrier_bid`` (предложения
перевозчиков по раундам). Поддерживают процесс: рассылка → сбор предложений →
переговоры → заключение договора → создание отгрузки.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carrier_rfq",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(64), server_default="", nullable=False),
        sa.Column("cargo", sa.String(255), server_default="", nullable=False),
        sa.Column("weight_kg", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("max_dim_cm", sa.Integer(), server_default="0", nullable=False),
        sa.Column("category", sa.String(32), server_default="", nullable=False),
        sa.Column("needs_temp", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("adr", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("route_from", sa.String(128), server_default="", nullable=False),
        sa.Column("route_to", sa.String(128), server_default="", nullable=False),
        sa.Column("zone_code", sa.String(8), server_default="", nullable=False),
        sa.Column("pickup_date", sa.String(32), server_default="", nullable=False),
        sa.Column("declared_value", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("office_doc_ref", sa.String(64), server_default="", nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(128), server_default="", nullable=False),
        sa.Column("deadline", sa.String(32), server_default="", nullable=False),
        sa.Column("awarded_carrier_code", sa.String(32), server_default="", nullable=False),
        sa.Column("awarded_price", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )

    op.create_table(
        "carrier_rfq_invite",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(16), server_default="manual", nullable=False),
        sa.Column("status", sa.String(16), server_default="sent", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rfq_id", "carrier_code", name="uq_rfq_invite"),
        schema="logistics",
    )

    op.create_table(
        "carrier_bid",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("eta_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vehicle_class", sa.String(64), server_default="", nullable=False),
        sa.Column("valid_until", sa.String(32), server_default="", nullable=False),
        sa.Column("comment", sa.String(255), server_default="", nullable=False),
        sa.Column("round", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        schema="logistics",
    )


def downgrade() -> None:
    op.drop_table("carrier_bid", schema="logistics")
    op.drop_table("carrier_rfq_invite", schema="logistics")
    op.drop_table("carrier_rfq", schema="logistics")
