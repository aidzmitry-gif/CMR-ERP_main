"""sales: мульти-воронки — Deal.funnel + Stage.funnel + сид «Постоянные клиенты»

Добавляет колонку ``funnel`` (String(32), NOT NULL, server_default ``new_clients``) в
``sales.deal`` и ``sales.stage``; существующие строки получают дефолт автоматически.
В сид воронки добавлены 5 стадий «Постоянные клиенты» (укороченный цикл перезаказа:
запрос → счёт → договор → успех/отказ) — без cond_lost (шум для повторных).

Revision ID: 0062
Revises: 0061
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса CRM/Продажи).
Чейн: 0060 (sales.stage) → 0061 (finance) → 0062 (этот). 0061 был оперативно занят
финансовой полосой, мой ТЗ-номер сдвинулся.
"""
import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None

# Стадии воронки repeat_clients — мини-цикл перезаказа (заморожено на этой ревизии).
_REPEAT = [
    ("rp_request", "Запрос повтор", 30, "normal", "#3B82F6"),
    ("rp_invoice", "Счёт повтор", 70, "normal", "#0EA5E9"),
    ("rp_contract", "Договор/предоплата", 90, "normal", "#10B981"),
    ("rp_won", "Успех", 100, "won", "#22C55E"),
    ("rp_lost", "Отказ", 0, "lost", "#EF4444"),
]


def upgrade() -> None:
    op.add_column(
        "deal",
        sa.Column("funnel", sa.String(32), server_default="new_clients", nullable=False),
        schema="sales",
    )
    op.add_column(
        "stage",
        sa.Column("funnel", sa.String(32), server_default="new_clients", nullable=False),
        schema="sales",
    )
    # Сид новой воронки. Если строки с такими code уже есть (re-up или ручной сид) — пропустим
    # детерминированно: проверим существование одного из ключевых кодов, иначе вставим.
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM sales.stage WHERE code = 'rp_won' LIMIT 1")
    ).first()
    if exists:
        return
    stage = sa.table(
        "stage",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("probability", sa.Integer),
        sa.column("kind", sa.String),
        sa.column("color", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("funnel", sa.String),
        schema="sales",
    )
    op.bulk_insert(
        stage,
        [
            {
                "code": code,
                "title": title,
                "sort_order": i,
                "probability": prob,
                "kind": kind,
                "color": color,
                "is_active": True,
                "funnel": "repeat_clients",
            }
            for i, (code, title, prob, kind, color) in enumerate(_REPEAT)
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sales.stage WHERE funnel = 'repeat_clients'"))
    op.drop_column("stage", "funnel", schema="sales")
    op.drop_column("deal", "funnel", schema="sales")
