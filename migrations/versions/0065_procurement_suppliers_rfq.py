"""procurement: справочник поставщиков + RFQ/тендер + связи supplier_id + поля претензий

- ``procurement.supplier`` — профиль поставщика закупок (условия/срок/incoterms/статус),
  ``unp`` soft-ref на MDM-контрагента (без FK).
- ``procurement.rfq`` / ``rfq_bid`` — запрос цен + предложения поставщиков (тендер закупки).
- ``supplier_id`` (soft-ref) в purchase_request / purchase_order / supplier_claim — связь с эталоном.
- supplier_claim: типизация (claim_type/qty_affected/amount_byn/resolution) — ручные претензии.
- purchase_order.status: дефолт draft (черновик до размещения, не «в пути»).

Revision ID: 0065
Revises: 0064
Create Date: 2026-06-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- справочник поставщиков ---
    op.create_table(
        "supplier",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unp", sa.String(32), server_default="", nullable=False),
        sa.Column("country", sa.String(64), server_default="", nullable=False),
        sa.Column("flag", sa.String(8), server_default="", nullable=False),
        sa.Column("contact_person", sa.String(128), server_default="", nullable=False),
        sa.Column("phone", sa.String(64), server_default="", nullable=False),
        sa.Column("email", sa.String(128), server_default="", nullable=False),
        sa.Column("payment_terms", sa.String(255), server_default="", nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("incoterms", sa.String(16), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("notes", sa.String(1000), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier")),
        schema="procurement",
    )

    # --- RFQ / тендер ---
    op.create_table(
        "rfq",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item", sa.String(255), server_default="", nullable=False),
        sa.Column("sku_code", sa.String(64), server_default="", nullable=False),
        sa.Column("qty", sa.Numeric(14, 2), server_default="1", nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rfq")),
        schema="procurement",
    )
    op.create_table(
        "rfq_bid",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rfq_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("price_byn", sa.Numeric(14, 2), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("incoterms", sa.String(16), server_default="", nullable=False),
        sa.Column("note", sa.String(400), server_default="", nullable=False),
        sa.Column("is_winner", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rfq_id"], ["procurement.rfq.id"],
            name=op.f("fk_rfq_bid_rfq_id_rfq"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rfq_bid")),
        schema="procurement",
    )
    op.create_index("ix_rfq_bid_rfq", "rfq_bid", ["rfq_id"], schema="procurement")

    # --- связи supplier_id (soft-ref, без FK) ---
    op.add_column("purchase_request", sa.Column("supplier_id", sa.Integer(), nullable=True), schema="procurement")
    op.add_column("purchase_order", sa.Column("supplier_id", sa.Integer(), nullable=True), schema="procurement")
    op.add_column("supplier_claim", sa.Column("supplier_id", sa.Integer(), nullable=True), schema="procurement")

    # --- типизация претензий ---
    op.add_column("supplier_claim", sa.Column("claim_type", sa.String(32), server_default="", nullable=False), schema="procurement")
    op.add_column("supplier_claim", sa.Column("qty_affected", sa.Integer(), server_default="0", nullable=False), schema="procurement")
    op.add_column("supplier_claim", sa.Column("amount_byn", sa.Numeric(14, 2), nullable=True), schema="procurement")
    op.add_column("supplier_claim", sa.Column("resolution", sa.String(500), server_default="", nullable=False), schema="procurement")

    # --- PO: дефолт статуса draft (черновик до размещения) ---
    op.alter_column("purchase_order", "status", server_default="draft", schema="procurement")


def downgrade() -> None:
    op.alter_column("purchase_order", "status", server_default="ordered", schema="procurement")
    op.drop_column("supplier_claim", "resolution", schema="procurement")
    op.drop_column("supplier_claim", "amount_byn", schema="procurement")
    op.drop_column("supplier_claim", "qty_affected", schema="procurement")
    op.drop_column("supplier_claim", "claim_type", schema="procurement")
    op.drop_column("supplier_claim", "supplier_id", schema="procurement")
    op.drop_column("purchase_order", "supplier_id", schema="procurement")
    op.drop_column("purchase_request", "supplier_id", schema="procurement")
    op.drop_index("ix_rfq_bid_rfq", "rfq_bid", schema="procurement")
    op.drop_table("rfq_bid", schema="procurement")
    op.drop_table("rfq", schema="procurement")
    op.drop_table("supplier", schema="procurement")
