"""sales: воронка 6→9 стадий (Сделки 2.0) — миграция данных существующих сделок

Старые 6 стадий (new/qual/prop/appr/won/lost) → 9 новых
(new/qual/price_req/has_price/meeting/invoice/protected/contract/won + cond_lost/lost).
Маппинг: prop→price_req («КП» ≈ цена запрошена), appr→meeting («согласование» ≈ встреча).
Остальные id (new/qual/won/lost) совпадают. Новые промежуточные стадии
(has_price/invoice/protected/contract/cond_lost) на старте пустые.

Источник истины — stages.py; контракт — coordination/sales-2.0-contract.md.

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-15
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

# старая стадия → новая (только переименованные; совпадающие не трогаем)
_STAGE_MAP = {"prop": "price_req", "appr": "meeting"}


def _remap(mapping: dict[str, str]) -> None:
    """UPDATE стадии в deal и истории deal_stage_event по словарю old→new."""
    for old, new in mapping.items():
        op.execute(f"UPDATE sales.deal SET stage = '{new}' WHERE stage = '{old}'")
        op.execute(
            f"UPDATE sales.deal_stage_event SET to_stage = '{new}' WHERE to_stage = '{old}'"
        )
        op.execute(
            f"UPDATE sales.deal_stage_event SET from_stage = '{new}' WHERE from_stage = '{old}'"
        )


def upgrade() -> None:
    _remap(_STAGE_MAP)


def downgrade() -> None:
    # обратный маппинг (price_req→prop, meeting→appr). ⚠ необратимо смешает сделки,
    # реально попавшие на новые промежуточные стадии после апгрейда, со старыми —
    # на момент миграции эти стадии пусты, поэтому корректно.
    _remap({new: old for old, new in _STAGE_MAP.items()})
