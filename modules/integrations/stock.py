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

    async def release(self, session: AsyncSession, items: list[dict]) -> list[dict]:
        """Снять резерв под позиции ``[{sku_code, qty}]`` — ``qty_reserved`` уменьшается.

        Зеркально ``reserve`` (SALES-51); не опускает резерв ниже нуля. Применяется
        при аннулировании просроченного счёта. Возвращает сводку фактически снятого.
        """
        released: list[dict] = []
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
            current = row.qty_reserved or Decimal("0")
            row.qty_reserved = current - qty if current > qty else Decimal("0")
            released.append({"sku_code": code, "qty": float(qty), "warehouse": row.warehouse})
        return released

    async def stock_by_sku(self, session: AsyncSession, sku_code: str) -> dict | None:
        """Остатки по SKU для карточки номенклатуры: строки по складам + сводка.

        Истина остатка — 1С; здесь читаем локальное зеркало ``stock_item``. ``None``,
        если по коду остатков нет (отсутствие не маскируем нулём). ``cost`` — себестоимость
        из 1С (вход маржи); цена/себес берём из первой строки (одинаковы по складам в demo).
        """
        rows = (
            await session.execute(
                select(StockItem).where(StockItem.sku_code == sku_code).order_by(StockItem.id)
            )
        ).scalars().all()
        if not rows:
            return None
        total_av = sum((r.qty_available or Decimal("0")) for r in rows)
        total_res = sum((r.qty_reserved or Decimal("0")) for r in rows)
        first = rows[0]
        return {
            "rows": [
                {
                    "warehouse": r.warehouse,
                    "qty_available": float(r.qty_available or 0),
                    "qty_reserved": float(r.qty_reserved or 0),
                    "qty_forecast": float(r.qty_forecast or 0),
                    "price": float(r.price) if r.price is not None else None,
                    "cost": float(r.cost) if r.cost is not None else None,
                }
                for r in rows
            ],
            "total_available": float(total_av),
            "total_reserved": float(total_res),
            "price": float(first.price) if first.price is not None else None,
            "cost": float(first.cost) if first.cost is not None else None,
            "updated_at": str(first.updated_at) if first.updated_at else None,
        }
