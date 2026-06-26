"""Контракт складского шлюза — операции над остатками (StockItem из 1С).

Симметрично ``onec``: реализация живёт в модуле ``integrations`` (владелец
остатков) и регистрируется в фасаде при загрузке — ``core.services.stock =
StockService()``. Sales резервирует остатки под документ через фасад, не
обращаясь к таблицам integrations напрямую (правило границ, §2.4).
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class StockGateway(Protocol):
    """Складские операции над остатками; ``items`` — список ``{sku_code, qty}``."""

    async def reserve(self, session: AsyncSession, items: list[dict]) -> list[dict]: ...
    # SALES-51: снять резерв (``qty_reserved`` уменьшается); реализация — в integrations.
    async def release(self, session: AsyncSession, items: list[dict]) -> list[dict]: ...
    # Чтение остатков по SKU (для карточки номенклатуры): строки по складам + сводка.
    # Возврат: ``{rows: [{warehouse, qty_available, qty_reserved, qty_forecast, price, cost}],
    #           total_available, total_reserved, price, cost, updated_at}`` или ``None`` — нет остатков.
    async def stock_by_sku(self, session: AsyncSession, sku_code: str) -> dict | None: ...
