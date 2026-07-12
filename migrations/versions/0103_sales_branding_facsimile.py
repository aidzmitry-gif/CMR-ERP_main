"""sales: факсимиле продавца — печать (штамп) и подпись руководителя.

Два nullable-поля к singleton ``company_branding``: ``stamp_data_url`` (печать) и
``signature_data_url`` (подпись руководителя) — data-URI изображений, накладываются на
печатные формы счёта и договора. Хранятся так же, как ``logo_data_url`` (текст в колонке).

Revision ID: 0103
Revises: 0102
Create Date: 2026-07-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_branding", sa.Column("stamp_data_url", sa.Text(), nullable=True), schema="sales")
    op.add_column("company_branding", sa.Column("signature_data_url", sa.Text(), nullable=True), schema="sales")


def downgrade() -> None:
    op.drop_column("company_branding", "signature_data_url", schema="sales")
    op.drop_column("company_branding", "stamp_data_url", schema="sales")
