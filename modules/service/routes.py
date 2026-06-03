"""HTTP-API модуля Service. Монтируется под префиксом ``/service``."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from modules.service.models import Ticket
from modules.service.schemas import TicketCreate, TicketOut

router = APIRouter(tags=["service"])


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(session: AsyncSession = Depends(get_session)):
    """Обращения в поддержку."""
    return (await session.execute(select(Ticket).order_by(Ticket.id.desc()))).scalars().all()


@router.post("/tickets", response_model=TicketOut, status_code=201)
async def create_ticket(payload: TicketCreate, session: AsyncSession = Depends(get_session)):
    """Создать обращение."""
    obj = Ticket(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj
