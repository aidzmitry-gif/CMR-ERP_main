"""HTTP-API модуля Production. Монтируется под префиксом ``/production``."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from modules.production.models import ProductionOrder
from modules.production.schemas import ProductionOrderCreate, ProductionOrderOut, StatusUpdate

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


@router.patch("/orders/{order_id}", response_model=ProductionOrderOut)
async def update_order(
    order_id: int,
    payload: StatusUpdate,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
):
    """Сменить статус заказа. При ``done`` — приход на склад (production → wms)."""
    obj = await session.get(ProductionOrder, order_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    obj.status = payload.status
    if payload.status == "done":
        core.event_bus.emit(
            session,
            "production.completed",
            {"item": obj.product, "qty": obj.qty, "warehouse": "Главный", "entity_ref": f"production:{obj.id}"},
        )
    await session.commit()
    await session.refresh(obj)
    return obj
