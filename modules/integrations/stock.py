"""Складские операции над остатками из 1С (``StockItem``).

Резерв под документы сделки (часть 9). В прототипе резерв отражается на локальной
проекции остатков; при реальной 1С он уйдёт документом резервирования и подтянется
обратно синхронизацией — контракт ``StockGateway`` при этом не изменится.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.integrations.models import Batch, StockItem

# Порог FEFO-предупреждения по сроку годности — менее года до «годен до» (макет batch).
_FEFO_WARN_DAYS = 365


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

    async def batches_by_sku(self, session: AsyncSession, sku_code: str) -> dict | None:
        """Партии закупки по SKU (lot/batch + FEFO): строки партий + сводка.

        ``None``, если партий по коду нет (отсутствие не маскируем). Партии сортируются по
        сроку годности (FEFO — раньше истекающие первыми; без срока — в конец). У каждой —
        ``days_to_expiry`` и флаг ``fefo`` (``expired`` / ``warn`` <1 года / ``ok`` / ``none``
        без срока). ``unit_landed_cost`` — себес единицы партии (вход маржи); ``None`` пока
        расчёта нет.
        """
        rows = (
            await session.execute(select(Batch).where(Batch.sku_code == sku_code))
        ).scalars().all()
        if not rows:
            return None

        today = date.today()
        out: list[dict] = []
        for b in rows:
            days = (b.expiry_date - today).days if b.expiry_date else None
            if days is None:
                fefo = "none"
            elif days < 0:
                fefo = "expired"
            elif days < _FEFO_WARN_DAYS:
                fefo = "warn"
            else:
                fefo = "ok"
            out.append({
                "lot_no": b.lot_no,
                "supplier": b.supplier,
                "warehouse": b.warehouse,
                "qty": float(b.qty or 0),
                "mfg_date": b.mfg_date.isoformat() if b.mfg_date else None,
                "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                "unit_landed_cost": (
                    float(b.unit_landed_cost) if b.unit_landed_cost is not None else None
                ),
                "external_ref": b.external_ref,
                "days_to_expiry": days,
                "fefo": fefo,
            })
        # FEFO-порядок: раньше истекающие первыми, без срока — в конец.
        out.sort(key=lambda r: (r["days_to_expiry"] is None, r["days_to_expiry"] or 0))
        # «Ближайший срок годности» — соонейший НЕ истёкший (будущий) срок: просроченные
        # партии в подпись не идут (иначе показали бы прошедшую дату как «годен до»).
        nearest = next(
            (r["expiry_date"] for r in out if r["expiry_date"] and r["fefo"] != "expired"),
            None,
        )
        return {
            "rows": out,
            "total_qty": float(sum((r.qty or Decimal("0")) for r in rows)),
            "nearest_expiry": nearest,
        }
