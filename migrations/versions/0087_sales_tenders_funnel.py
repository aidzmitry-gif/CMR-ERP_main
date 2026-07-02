"""sales: сид воронки «Тендеры» (третья мульти-воронка)

Добавляет 5 стадий воронки «Тендеры» (госзакупки/конкурсы) в ``sales.stage``: колонка
``funnel`` уже существует с 0062 — эта миграция только сидит данные, без DDL. Цвета/коды —
канон из ``modules/sales/stages.py::TENDER_STAGES`` (зеркало sales-board-mockup.html,
~строки 1899-1910).

Revision ID: 0087
Revises: 0086
Create Date: 2026-07-02

Примечание: номер взят атомарно через scripts/next_migration.py (полоса slice3-tenders).
"""
import sqlalchemy as sa
from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None

# Стадии воронки tenders — заморожено на этой ревизии (см. TENDER_STAGES в stages.py).
_TENDER = [
    ("tn_announced", "Объявлен", 15, "normal", "#3B82F6"),
    ("tn_submitted", "Заявка подана", 35, "normal", "#F59E0B"),
    ("tn_bidding", "Торги", 60, "normal", "#14B8A6"),
    ("tn_won", "Выигран", 100, "won", "#22C55E"),
    ("tn_lost", "Проигран", 0, "lost", "#EF4444"),
]


def upgrade() -> None:
    # Idempotent-check: если строки уже есть (re-up или ручной сид) — пропускаем.
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM sales.stage WHERE code = 'tn_won' LIMIT 1")
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
                "funnel": "tenders",
            }
            for i, (code, title, prob, kind, color) in enumerate(_TENDER)
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sales.stage WHERE funnel = 'tenders'"))
