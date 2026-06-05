"""HTTP-API модуля Office. Монтируется под префиксом ``/office``."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.office.models import OfficeDoc
from modules.office.schemas import OfficeDocCreate, OfficeDocOut, StageUpdate
from modules.office.stages import STAGES

router = APIRouter(tags=["office"])


def _to_card(r: OfficeDoc) -> FunnelCard:
    tags = [t for t in (r.delivery, r.docs_status) if t]
    return FunnelCard(
        id=r.id,
        code=r.number or f"ДОК-{r.id}",
        title=r.company,
        subtitle=r.title,
        amount=float(r.amount),
        priority=r.priority,
        owner=r.owner,
        date=r.op_date or "",
        next_step=r.next_step,
        tags=tags,
    )


@router.get("/docs", response_model=list[OfficeDocOut])
async def list_docs(session: AsyncSession = Depends(get_session)):
    """Документы по сделкам (плоский список)."""
    return (await session.execute(select(OfficeDoc).order_by(OfficeDoc.id.desc()))).scalars().all()


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> FunnelBoardOut:
    """Воронка офис-менеджера: документы сгруппированы по стадиям."""
    rows = (await session.execute(select(OfficeDoc))).scalars().all()
    return build_board(STAGES, rows, _to_card)


@router.post("/docs", response_model=OfficeDocOut, status_code=201)
async def create_doc(payload: OfficeDocCreate, session: AsyncSession = Depends(get_session)):
    """Создать документ по сделке. Номер генерируется автоматически, если не задан."""
    data = payload.model_dump()
    data["amount"] = Decimal(str(data["amount"]))
    obj = OfficeDoc(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ДОК-2026-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/docs/{doc_id}", response_model=OfficeDocOut)
async def update_doc(
    doc_id: int, payload: StageUpdate, session: AsyncSession = Depends(get_session)
):
    """Сменить стадию документа по сделке."""
    obj = await session.get(OfficeDoc, doc_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    obj.stage = payload.stage
    await session.commit()
    await session.refresh(obj)
    return obj
