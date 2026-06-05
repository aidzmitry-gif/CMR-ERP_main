"""HTTP-API модуля Production. Монтируется под префиксом ``/production``."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.production.models import ProductionOrder
from modules.production.schemas import ProductionOrderCreate, ProductionOrderOut, StageUpdate
from modules.production.stages import STAGES

router = APIRouter(tags=["production"])

# Переход в эту стадию = наряд готов → приход на склад (production → wms).
COMPLETED_STAGE = "done"


def _to_card(r: ProductionOrder) -> FunnelCard:
    return FunnelCard(
        id=r.id,
        code=r.number or f"ПЗ-{r.id}",
        title=r.product,
        priority=r.priority,
        owner=r.owner,
        date=r.due_date or "",
        progress=r.progress,
        insight=r.insight,
        tags=[f"{r.qty} шт"] if r.qty else [],
    )


@router.get("/orders", response_model=list[ProductionOrderOut])
async def list_orders(session: AsyncSession = Depends(get_session)):
    """Производственные наряды (плоский список — для аналитики и совместимости)."""
    return (
        await session.execute(select(ProductionOrder).order_by(ProductionOrder.id.desc()))
    ).scalars().all()


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> FunnelBoardOut:
    """Канбан цеха: наряды сгруппированы по этапам производства."""
    rows = (await session.execute(select(ProductionOrder))).scalars().all()
    return build_board(STAGES, rows, _to_card)


@router.post("/orders", response_model=ProductionOrderOut, status_code=201)
async def create_order(
    payload: ProductionOrderCreate, session: AsyncSession = Depends(get_session)
):
    """Создать наряд. Номер генерируется автоматически, если не задан."""
    obj = ProductionOrder(**payload.model_dump())
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ПЗ-2026-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/orders/{order_id}", response_model=ProductionOrderOut)
async def update_order(
    order_id: int,
    payload: StageUpdate,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
):
    """Сменить этап наряда. При «Готово → склад» — приход на склад (production → wms)."""
    obj = await session.get(ProductionOrder, order_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Наряд не найден")
    obj.stage = payload.stage
    if payload.stage == COMPLETED_STAGE:
        obj.progress = 100
        core.event_bus.emit(
            session,
            "production.completed",
            {
                "item": obj.product,
                "qty": obj.qty,
                "warehouse": "Главный",
                "entity_ref": f"production:{obj.id}",
            },
        )
    await session.commit()
    await session.refresh(obj)
    return obj
