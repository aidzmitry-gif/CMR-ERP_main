"""leads: UTM-поля на лиде (Цикл 4 — качество лида → реклама).

Разрыв контракта (см. coordination/DEPENDENCY-MAP.md): веб-форма/письмо несут
utm_source/utm_medium/utm_campaign (``_extract_utm`` в modules/integrations/routes.py),
но у ``Lead`` не было колонок под них — атрибуция лида к маркетинговой кампании не
работала. Три колонки, чтобы протянуть UTM через приём (веб-интейк/ручной POST/
запуск кампании) до события ``leads.lead.received``, на которое подписан marketing.

Revision ID: 0095
Revises: 0094
Create Date: 2026-07-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("utm_source", "utm_medium", "utm_campaign"):
        op.add_column(
            "lead",
            sa.Column(col, sa.String(length=128), server_default="", nullable=False),
            schema="leads",
        )


def downgrade() -> None:
    for col in ("utm_campaign", "utm_medium", "utm_source"):
        op.drop_column("lead", col, schema="leads")
