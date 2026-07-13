"""Dev-фикстура источника цены/себестоимости — ТОЛЬКО для локальной разработки и демонстрации.

Пока живая 1С не подключена (см. ``cost-price-from-1c-decision``), этот источник даёт
ДЕТЕРМИНИРОВАННЫЕ демо-значения по существующим SKU, чтобы прогнать UI провенанса и дефолты
конструктора «как будто из 1С». Значения помечены ``source='demo'`` — потребители обязаны
показать метку «демо, не 1С», чтобы никто не принял их за настоящие деньги (PLATFORM #1).

Активируется ТОЛЬКО в ``create_app`` при ``AIOS_ENVIRONMENT=dev`` И ``AIOS_DEMO_PRICE_COST=1``
(прод не импортирует этот модуль). Не в ``integrations``, не в проде. Когда 1С оживёт —
реальный reference-backed источник за фасадом ``PriceCostGateway`` подменяет фикстуру,
потребители не трогаются.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Sku
from core.services.price_cost import ItemPriceCost

# Демо-наценка на себестоимость → цена продажи. Не бизнес-число, лишь чтобы демо было связным.
_DEMO_MARKUP = 1.35


def _pseudo_cost_byn(code: str) -> float:
    """Стабильная псевдо-себестоимость 20..500 BYN по коду SKU (детерминированно, без БД-полей —
    в ``Sku`` нет цены/себеса, они транзакционные). Один код → всегда одно значение."""
    h = int(hashlib.sha256(code.encode("utf-8")).hexdigest(), 16)
    return round(20 + (h % 48001) / 100.0, 2)  # 20.00 .. 500.01


class DemoPriceCostSource:
    """Реализация ``PriceCostGateway`` для dev: демо-цена/себес по РЕАЛЬНЫМ SKU (golden record).

    Возвращает данные только по кодам, которые есть в справочнике номенклатуры (как поступил бы
    reference-backed источник) — по несуществующим кодам данных нет (потребитель деградирует).
    """

    async def get_item_price_cost(
        self, session: AsyncSession, sku_codes: list[str]
    ) -> dict[str, ItemPriceCost]:
        if not sku_codes:
            return {}
        known = (
            await session.execute(select(Sku.code).where(Sku.code.in_(sku_codes)))
        ).scalars().all()
        out: dict[str, ItemPriceCost] = {}
        for code in known:
            cost = _pseudo_cost_byn(code)
            out[code] = ItemPriceCost(
                cost_byn=cost,
                price_byn=round(cost * _DEMO_MARKUP, 2),
                currency="BYN",
                price_type="демо-прайс",
                as_of=None,  # демо — не датированная запись учёта; давность не выдумываем
                source="demo",
            )
        return out
