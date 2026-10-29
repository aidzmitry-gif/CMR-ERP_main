"""Синхронизация из 1С в бизнес-память (контрагенты, SKU, остатки/цены).

Читает данные коннектором и upsert-ит в общую модель; о результате сообщает
событием через шину (часть 6). Контрагенты идут через идемпотентный входной
адаптер ядра (`core.services.reference_import`): матч по УНП + alias-провенанс
источника в golden record. Основной учёт остаётся в 1С. Локальная проекция
не подменяет недоступные данные учётной системы нулями или demo-значениями.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Sku
from core.services import reference_import
from core.services.onec import OneCGateway
from modules.integrations.models import StockItem


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def sync_1c(session: AsyncSession, event_bus, client: OneCGateway) -> dict:
    # Контрагенты (по УНП) → идемпотентный входной адаптер ядра: матч/создание +
    # alias-провенанс источника в golden record (reference_import — сердце «1С=адаптер»).
    counterparties = await client.fetch_counterparties()
    cp = await reference_import.import_counterparties(session, counterparties, source="1c")

    # Остатки/цены + SKU
    stock = await client.fetch_stock()
    skus = {s.code: s for s in (await session.execute(select(Sku))).scalars().all()}
    items = {
        (si.sku_code, si.warehouse): si
        for si in (await session.execute(select(StockItem))).scalars().all()
    }
    imported_stock = 0
    unknown_stock = 0
    for row in stock:
        if row["sku_code"] not in skus:
            skus[row["sku_code"]] = Sku(code=row["sku_code"], title=row["title"], unit="шт")
            session.add(skus[row["sku_code"]])
        # A catalogue row does not prove any warehouse balance. Preserve an old
        # projection rather than overwriting it with invented zeros; consumers
        # separately require an available stock source before using that mirror.
        if getattr(client, "stock_source_available", False) is not True or not row.get("warehouse") or any(
            row.get(key) is None for key in ("qty_available", "qty_reserved", "qty_forecast", "price")
        ):
            unknown_stock += 1
            continue
        key = (row["sku_code"], row["warehouse"])
        item = items.get(key)
        if item is None:
            item = StockItem(sku_code=row["sku_code"], warehouse=row["warehouse"])
            session.add(item)
            items[key] = item
        item.qty_available = Decimal(str(row["qty_available"]))
        item.qty_reserved = Decimal(str(row["qty_reserved"]))
        item.qty_forecast = Decimal(str(row["qty_forecast"]))
        item.price = Decimal(str(row["price"]))
        item.cost = Decimal(str(row["cost"])) if row.get("cost") is not None else None
        item.updated_at = _utcnow()
        imported_stock += 1

    await session.flush()
    summary = {
        "counterparties": cp["total"],
        "new_counterparties": cp["created"],
        "counterparty_aliases": cp["aliases_added"],
        "stock": imported_stock,
        "stock_unknown": unknown_stock,
        "stock_source_available": getattr(client, "stock_source_available", None),
    }
    event_bus.emit(session, "integration.1c.synced", summary)
    return summary
