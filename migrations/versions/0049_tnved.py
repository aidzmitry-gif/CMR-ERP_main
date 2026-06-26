"""core: справочник кодов ТН ВЭД ЕАЭС с таможенными ставками — историчный (SCD2)

``ref_tnved`` — Единый таможенный тариф ЕАЭС (ЕТТ): код + ввозная пошлина (``duty_rate`` %)
+ акциз; ставка НДС — мягкой ссылкой ``vat_code`` на ``ref_vat_rate`` (не дублируем).
Историчность как у курсов/НДС: полуоткрытый интервал ``[start_date, end_date)``, расчёт
landed cost берёт ставку, действовавшую на дату оформления.

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-26

Примечание: чейн линейный 0048 → 0049. Если параллельная сессия уже заняла 0049 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ref_tnved",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("duty_rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("vat_code", sa.String(length=16), nullable=True),
        sa.Column("excise", sa.String(length=128), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_ref_tnved_lookup", "ref_tnved", ["code", "start_date"])


def downgrade() -> None:
    op.drop_index("ix_ref_tnved_lookup", table_name="ref_tnved")
    op.drop_table("ref_tnved")
