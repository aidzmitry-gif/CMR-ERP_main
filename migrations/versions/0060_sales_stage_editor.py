"""sales: редактируемый справочник стадий воронки (редактор стадий, Сделки 2.0)

``sales.stage`` — стадия воронки: ``code`` (= значение ``Deal.stage``), ``title``,
``sort_order`` (порядок колонок доски), ``probability`` (дефолт вероятности, SALES-44),
``kind`` (normal|won|cond_lost|lost), ``color``, ``is_active``. Источник истины доски/
группировки, когда таблица заполнена; код падает на канон ``modules/sales/stages.py``,
пока пусто. Сид — 11 канонических стадий (контракт «Сделки 2.0», цена ДО встречи).

Revision ID: 0060
Revises: 0059
Create Date: 2026-06-28

Примечание: номер взят атомарно через scripts/next_migration.py (полоса «Продажи/CRM»).
Чейн: 0057 (reference) → 0058 (wms) → 0059 (wms) → 0060 (этот). Сид инлайн (миграция
самодостаточна, не зависит от эволюции app-констант).
"""
import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

# Канон 11 стадий (заморожен на этой ревизии) — зеркало modules/sales/stages.py на 2026-06-28.
_STAGES = [
    ("new", "Новая заявка", 10, "normal", "#3B82F6"),
    ("qual", "Квалифицирован", 25, "normal", "#8B5CF6"),
    ("price_req", "Цена запрошена", 35, "normal", "#F59E0B"),
    ("has_price", "Есть цена", 45, "normal", "#EAB308"),
    ("meeting", "Встреча назначена", 55, "normal", "#14B8A6"),
    ("invoice", "Счёт отправлен", 70, "normal", "#0EA5E9"),
    ("protected", "Счёт защищён", 85, "normal", "#6366F1"),
    ("contract", "Договор/предоплата", 95, "normal", "#10B981"),
    ("won", "Успех", 100, "won", "#22C55E"),
    ("cond_lost", "Условный отказ", 5, "cond_lost", "#F97316"),
    ("lost", "Отказ", 0, "lost", "#EF4444"),
]


def upgrade() -> None:
    op.create_table(
        "stage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("probability", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kind", sa.String(16), server_default="normal", nullable=False),
        sa.Column("color", sa.String(16), server_default="#64748B", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage")),
        sa.UniqueConstraint("code", name=op.f("uq_stage_code")),
        schema="sales",
    )
    stage = sa.table(
        "stage",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("probability", sa.Integer),
        sa.column("kind", sa.String),
        sa.column("color", sa.String),
        sa.column("is_active", sa.Boolean),
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
            }
            for i, (code, title, prob, kind, color) in enumerate(_STAGES)
        ],
    )


def downgrade() -> None:
    op.drop_table("stage", schema="sales")
