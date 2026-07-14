"""Reference-backed ``PriceCostGateway``: цена/себес из ``StockItem`` (наполнение из 1С).

Потребители в ``modules/sales`` уже читают ``core.services.price_cost`` — этот источник
регистрируется в ``IntegrationsModule``, когда задан ``onec_base_url``. ``source='onec'``
включает UI-метку «из 1С».

Себестоимость: на живой ``ka_copy`` регистры
``AccumulationRegister_СебестоимостьТоваров`` / ``СтоимостьТоваров`` /
``ВыручкаИСебестоимостьПродаж`` в OData **не опубликованы** (проверено 2026-07-14, HTTP 404).
Пока ``StockItem.cost`` пуст — ``cost_byn=None`` (честная деградация, не ноль).
Цена — из ``StockItem.price`` (ETL: строки ``Document_РеализацияТоваровУслуг`` /
опционально ``InformationRegister_ЦеныНоменклатуры``).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.services.price_cost import ItemPriceCost
from modules.integrations.models import StockItem


class StockPriceCostSource:
    """Цена/себес по коду SKU из синхронизированных остатков ``StockItem``."""

    async def get_item_price_cost(
        self, session: AsyncSession, sku_codes: list[str]
    ) -> dict[str, ItemPriceCost]:
        if not sku_codes:
            return {}
        rows = (
            await session.execute(
                select(StockItem).where(StockItem.sku_code.in_(sku_codes))
            )
        ).scalars().all()
        # один SKU может быть на нескольких складах — берём запись с ненулевой ценой,
        # иначе первую; prefer max(updated_at)
        best: dict[str, StockItem] = {}
        for row in rows:
            prev = best.get(row.sku_code)
            if prev is None:
                best[row.sku_code] = row
                continue
            prev_price = float(prev.price or 0)
            row_price = float(row.price or 0)
            if row_price > 0 and prev_price <= 0:
                best[row.sku_code] = row
            elif row.updated_at and prev.updated_at and row.updated_at > prev.updated_at:
                if row_price > 0 or prev_price <= 0:
                    best[row.sku_code] = row

        out: dict[str, ItemPriceCost] = {}
        for code, row in best.items():
            price = float(row.price) if row.price is not None and float(row.price) > 0 else None
            cost = float(row.cost) if row.cost is not None else None
            if price is None and cost is None:
                continue
            as_of: date | None = row.updated_at.date() if row.updated_at else None
            out[code] = ItemPriceCost(
                cost_byn=cost,
                price_byn=price,
                currency="BYN",
                price_type=None,
                as_of=as_of,
                source="onec",
            )
        return out
