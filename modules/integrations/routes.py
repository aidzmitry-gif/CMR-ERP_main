"""HTTP-API модуля Integrations. Монтируется под префиксом ``/integrations``."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from modules.integrations.models import StockItem
from modules.integrations.schemas import RegistryOut, StockOut
from modules.integrations.service import sync_1c

router = APIRouter(tags=["integrations"])


@router.post("/1c/sync")
async def sync(core: Core = Depends(get_core), session: AsyncSession = Depends(get_session)) -> dict:
    """Прочитать данные из 1С и синхронизировать в бизнес-память."""
    summary = await sync_1c(session, core.event_bus, core.services.onec)
    await session.commit()
    return {"ok": True, **summary}


@router.get("/1c/stock", response_model=list[StockOut])
async def stock(session: AsyncSession = Depends(get_session)):
    """Остатки/цены (синхронизированные из 1С)."""
    return (await session.execute(select(StockItem).order_by(StockItem.sku_code))).scalars().all()


@router.get("/egr/{unp}", response_model=RegistryOut)
async def egr_lookup(unp: str, core: Core = Depends(get_core)):
    """Подтянуть контрагента по УНП из реестра ЕГР РБ (sales-28)."""
    if core.services.registry is None:
        raise HTTPException(status_code=503, detail="Реестр ЕГР не подключён")
    data = await core.services.registry.lookup(unp)
    if data is None:
        raise HTTPException(status_code=404, detail="Контрагент по УНП не найден")
    return data
