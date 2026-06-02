"""Складские операции над остатками из 1С (``StockItem``).

Резерв под документы сделки (часть 9). В прототипе резерв отражается на локальной
проекции остатков; при реальной 1С он уйдёт документом резервирования и подтянется
обратно синхронизацией — контракт ``StockGateway`` при этом не изменится.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.integrations.models import StockItem


class StockService:
    async def reserve(self, session: AsyncSession, items: list[dict]) -> list[dict]:
        """Зарезервировать остатки под позиции ``[{sku_code, qty}]`` — ``qty_reserved`` растёт.

        Резерв ставится на первый склад с таким SKU; позиции без остатка пропускаются.
        Возвращает сводку фактически зарезервированного.
        """
        reserved: list[dict] = []
        for it in items:
            code = it.get("sku_code")
            qty = Decimal(str(it.get("qty", 0)))
            if not code or qty <= 0:
                continue
            row = (
                await session.execute(
                    select(StockItem).where(StockItem.sku_code == code).order_by(StockItem.id)
                )
            ).scalars().first()
            if row is None:
                continue
            row.qty_reserved = (row.qty_reserved or Decimal("0")) + qty
            reserved.append({"sku_code": code, "qty": float(qty), "warehouse": row.warehouse})
        return reserved
