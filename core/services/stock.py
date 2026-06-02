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
