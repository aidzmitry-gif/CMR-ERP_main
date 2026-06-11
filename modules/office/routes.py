"""HTTP-API модуля Office. Монтируется под префиксом ``/office``.

Помимо CRUD и канбан-воронки роуты эмитят доменные события в шину (outbox),
связывая офис с соседними отделами — Склад, Логистика, Финансы, Юрист
(см. ``events.py``). Каждое изменение стадии порождает событие в той же
транзакции, что и запись в БД.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.office import events
from modules.office.carriers import CARRIERS, get_carrier
from modules.office.models import OfficeDoc
from modules.office.schemas import (
    CarrierOut,
    CarrierRequest,
    CarrierRequestOut,
    OfficeDocCreate,
    OfficeDocOut,
    StageUpdate,
)
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


@router.get("/carriers", response_model=list[CarrierOut])
async def list_carriers() -> list[dict]:
    """Справочник перевозчиков для доставки по РБ (для кнопки в карточке)."""
    return CARRIERS


@router.post("/docs", response_model=OfficeDocOut, status_code=201)
async def create_doc(
    payload: OfficeDocCreate,
    session: AsyncSession = Depends(get_session),
    core: Core = Depends(get_core),
):
    """Создать документ по сделке. Номер генерируется автоматически, если не задан."""
    data = payload.model_dump()
    data["amount"] = Decimal(str(data["amount"]))
    obj = OfficeDoc(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ДОК-2026-{obj.id:04d}"
    events.emit_doc_created(core.event_bus, session, obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/docs/{doc_id}", response_model=OfficeDocOut)
async def update_doc(
    doc_id: int,
    payload: StageUpdate,
    session: AsyncSession = Depends(get_session),
    core: Core = Depends(get_core),
):
    """Сменить стадию документа. Переход стадии эмитит событие соседнему отделу."""
    obj = await session.get(OfficeDoc, doc_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if payload.stage not in {s["id"] for s in STAGES}:
        raise HTTPException(status_code=422, detail="Неизвестная стадия")

    obj.stage = payload.stage
    bus = core.event_bus
    if payload.stage == "ready":
        events.emit_shipment_requested(bus, session, obj)      # → Склад
    elif payload.stage == "docs":
        events.emit_docs_collected(bus, session, obj)          # → Финансы
    elif payload.stage == "await_pay":
        events.emit_payment_awaiting(bus, session, obj)        # → Финансы (+ кредитный риск)
        events.escalate_overdue(bus, session, obj)             # лестница 5/15/30/45 (Юрист/РОП)

    await session.commit()
    await session.refresh(obj)
    return obj


@router.post("/docs/{doc_id}/carrier-request", response_model=CarrierRequestOut)
async def carrier_request(
    doc_id: int,
    payload: CarrierRequest,
    session: AsyncSession = Depends(get_session),
    core: Core = Depends(get_core),
):
    """Создать заявку перевозчику на доставку по РБ из карточки документа.

    Пользователь выбирает перевозчика из справочника (``GET /office/carriers``),
    указывает направление и дату забора. Роут генерирует номер заявки
    ``ЛОГ-2026-NNNN``, фиксирует перевозчика в документе и эмитит
    ``logistics.delivery.requested`` → отдел Логистики.

    Бизнес-правило: заявку можно создать только пока документ на стадии
    «Готово к отгрузке» — нельзя заказывать доставку для уже отгруженного/
    оплаченного документа (защита от двойной логистики).
    """
    obj = await session.get(OfficeDoc, doc_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    if not events.is_ready_for_carrier(obj):
        raise HTTPException(
            status_code=409,
            detail="Заявку перевозчику можно создать только на стадии «Готово к отгрузке»",
        )

    carrier = get_carrier(payload.carrier)
    if carrier is None:
        raise HTTPException(status_code=422, detail="Неизвестный перевозчик")

    log_ref = f"ЛОГ-2026-{obj.id:04d}"
    obj.delivery = carrier["name"]
    obj.logistics_ref = log_ref
    if payload.region:
        obj.region = payload.region
    obj.docs_status = f"Заявка перевозчику: {carrier['name']}"
    obj.next_step = "Ожидаем забор груза перевозчиком"

    events.emit_carrier_request(
        core.event_bus,
        session,
        obj,
        log_ref=log_ref,
        carrier=carrier["id"],
        carrier_name=carrier["name"],
        region=payload.region,
        pickup_date=payload.pickup_date,
        contact=payload.contact,
        comment=payload.comment,
    )
    await session.commit()
    await session.refresh(obj)
    return CarrierRequestOut(
        ok=True,
        log_ref=log_ref,
        carrier=carrier["name"],
        region=obj.region,
        doc=OfficeDocOut.model_validate(obj),
    )
