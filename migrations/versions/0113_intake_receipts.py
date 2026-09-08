"""core: durable intake identities and delivery receipts.

Revision ID: 0113
Revises: 0112
Number reserved by the operator for CRM-INTAKE-001.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intake_identity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("namespace", "source_id", name="uq_intake_identity_namespace"),
    )
    op.create_table(
        "intake_receipt",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("intake_identity.id"), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("delivery_id", sa.String(256), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("namespace", "delivery_id", name="uq_intake_receipt_namespace"),
        sa.CheckConstraint("status IN ('queued', 'delivered', 'failed')", name="intake_status"),
        sa.CheckConstraint(
            "status != 'delivered' OR delivered_at IS NOT NULL", name="intake_delivered_at"
        ),
    )
    op.create_index("ix_intake_receipt_identity_id", "intake_receipt", ["identity_id"])


def downgrade() -> None:
    op.drop_index("ix_intake_receipt_identity_id", table_name="intake_receipt")
    op.drop_table("intake_receipt")
    op.drop_table("intake_identity")
