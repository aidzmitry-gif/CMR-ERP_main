"""sales: комментарий РОПа/причина возврата к плану продавца — plan_target.rop_comment

Один текст-канал обратной связи РОП↔продавец по метрике: пишется при согласовании/
отклонении (``POST /plans/{id}/decide``) и при возврате плана в работу
(``POST /plans/{id}/reopen``). Хранится как ``rop_comment`` (Text) в схеме ``sales``.

Revision ID: 0104
Revises: 0103
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_target", sa.Column("rop_comment", sa.Text(), nullable=True), schema="sales"
    )


def downgrade() -> None:
    op.drop_column("plan_target", "rop_comment", schema="sales")
