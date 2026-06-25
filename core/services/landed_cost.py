"""Контракт шлюза landed cost — фасад ядра к себестоимости партии (читать, не считать).

Себестоимость считает модуль ``procurement`` (партия/инвойс/фрахт/пошлина ТН ВЭД/брокер) и
регистрирует реализацию в фасаде: ``core.services.landed_cost = LandedCostService()``. Ядро
держит лишь протокол — карточка номенклатуры и расчёт маржи в сделке читают себестоимость через
``core.services.landed_cost``, НЕ импортируя procurement и не дублируя транзакционные данные (CQRS,
§6). Пока модуль не реализовал — поле ``None``, потребители деградируют (нет себестоимости, не 0).

Возврат ``last_landed_cost`` — ``{unit_landed_cost_byn, shipment_id, fixed_at, stage, fx_rate,
fx_date}`` или ``None`` (нет закрытого расчёта по этой номенклатуре). ``None`` ≠ 0: отсутствие
себестоимости не маскируем нулём (скрыло бы дыру в марже).
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class LandedCostGateway(Protocol):
    """Чтение последней посчитанной себестоимости номенклатуры (по коду SKU)."""

    async def last_landed_cost(self, session: AsyncSession, sku_code: str) -> dict | None: ...

    async def last_landed_cost_batch(
        self, session: AsyncSession, sku_codes: list[str]
    ) -> dict[str, dict | None]: ...
