"""Синхронизация из 1С в бизнес-память (контрагенты, SKU, остатки/цены).

Читает данные коннектором и upsert-ит в общую модель; о результате сообщает
событием через шину (часть 6). Контрагенты идут через идемпотентный входной
адаптер ядра (`core.services.reference_import`): матч по УНП + alias-провенанс
источника в golden record. ERP — система-источник, 1С — временный адаптер:
отключение 1С = перестать звать sync, структура мастер-данных не меняется.
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
    for row in stock:
        if row["sku_code"] not in skus:
            skus[row["sku_code"]] = Sku(code=row["sku_code"], title=row["title"], unit="шт")
            session.add(skus[row["sku_code"]])
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
        item.updated_at = _utcnow()

    await session.flush()
    summary = {
        "counterparties": cp["total"],
        "new_counterparties": cp["created"],
        "counterparty_aliases": cp["aliases_added"],
        "stock": len(stock),
    }
    event_bus.emit(session, "integration.1c.synced", summary)
    return summary
