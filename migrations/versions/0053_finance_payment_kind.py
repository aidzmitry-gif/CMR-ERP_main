"""finance: payment.kind (receivable | freight)

Разводит платежи на доход (``receivable`` — счёт к получению) и расход
(``freight`` — стоимость перевозки из logistics → finance), чтобы можно было
считать валовую прибыль (доход − фрахт). Дефолт ``receivable`` — старые строки валидны.

Revision ID: 0053
Revises: 0052
Create Date: 2026-06-26

Примечание: чейн линейный 0052 → 0053. Если параллельная сессия уже заняла 0053 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="receivable"),
        schema="finance",
    )


def downgrade() -> None:
    op.drop_column("payment", "kind", schema="finance")
