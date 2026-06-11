"""logistics: тендер-реализм — токен публичной ссылки + журнал рассылки

Аддитивно расширяет ``logistics.carrier_rfq_invite``: ``token`` (секрет публичной
ссылки на подачу ставки ``POST /rfqs/bid/{token}``), ``notified_at`` и ``detail``
(журнал рассылки — когда и с каким результатом уведомили перевозчика). Все колонки
с безопасными значениями по умолчанию → миграция не ломает существующие строки.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "carrier_rfq_invite",
        sa.Column("token", sa.String(40), server_default="", nullable=False),
        schema="logistics",
    )
    op.add_column(
        "carrier_rfq_invite",
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        schema="logistics",
    )
    op.add_column(
        "carrier_rfq_invite",
        sa.Column("detail", sa.String(255), server_default="", nullable=False),
        schema="logistics",
    )


def downgrade() -> None:
    op.drop_column("carrier_rfq_invite", "detail", schema="logistics")
    op.drop_column("carrier_rfq_invite", "notified_at", schema="logistics")
    op.drop_column("carrier_rfq_invite", "token", schema="logistics")
