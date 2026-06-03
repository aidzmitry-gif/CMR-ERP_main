"""HTTP-API модуля Production. Монтируется под префиксом ``/production``."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from modules.production.models import ProductionOrder
from modules.production.schemas import ProductionOrderCreate, ProductionOrderOut

router = APIRouter(tags=["production"])


@router.get("/orders", response_model=list[ProductionOrderOut])
async def list_orders(session: AsyncSession = Depends(get_session)):
    """Производственные заказы."""
    return (
        await session.execute(select(ProductionOrder).order_by(ProductionOrder.id.desc()))
    ).scalars().all()


@router.post("/orders", response_model=ProductionOrderOut, status_code=201)
async def create_order(
    payload: ProductionOrderCreate, session: AsyncSession = Depends(get_session)
):
    """Создать производственный заказ."""
    obj = ProductionOrder(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj
