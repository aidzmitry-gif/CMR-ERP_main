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

from core.domain.models import User
from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from core.services.auth import CurrentUser, get_current_user, has_permission, require_permission
from modules.office import events
from modules.office.carriers import CARRIERS
from modules.office.models import LegalClaim, LegalContract, OfficeDoc
from modules.office.schemas import (
    CarrierOut,
    LegalClaimCreate,
    LegalClaimOut,
    LegalClaimPatch,
    LegalContractCreate,
    LegalContractOut,
    LegalContractPatch,
    OfficeDocCreate,
    OfficeDocOut,
    StageUpdate,
)
from modules.office.shipping_access import (
    current_actor,
    latest_assignment,
    locked_doc,
    visible_docs,
)
from modules.office.shipping_producer import OfficeShippingProducer, RequestInput
from modules.office.shipping_producer import router as shipping_router
from modules.office.shipping_producer import transaction as shipping_transaction
from modules.office.stages import STAGES

router = APIRouter(tags=["office"])
router.include_router(shipping_router)


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
async def list_docs(session: AsyncSession = Depends(get_session), core: Core = Depends(get_core), user=Depends(get_current_user)):
    """Документы по сделкам (плоский список)."""
    return await visible_docs(core, session, user)


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session), core: Core = Depends(get_core), user=Depends(get_current_user)) -> FunnelBoardOut:
    """Воронка офис-менеджера: документы сгруппированы по стадиям."""
    rows = await visible_docs(core, session, user)
    return build_board(STAGES, rows, _to_card)


@router.get("/review-queue")
async def review_queue(session: AsyncSession = Depends(get_session), core: Core = Depends(get_core), user=Depends(get_current_user)):
    """Supervisor-only draft queue; expose stable reviewer identities, never emails."""
    await current_actor(core, session, user, "office.shipping.review.assign")
    documents = []
    for doc in await visible_docs(core, session, user):
        if doc.stage != "draft":
            continue
        assignment = await latest_assignment(session, doc.id)
        documents.append({"id": doc.id, "number": doc.number, "title": doc.title, "company": doc.company,
            "assignment_revision": assignment.revision if assignment else 0,
            "reviewer_subject": assignment.subject if assignment else None})
    reviewers = []
    for target in await session.scalars(select(User).where(User.status == "active").order_by(User.full_name, User.id)):
        subject = target.keycloak_user_id
        if not subject and core.services.config.auth_mode == "dev":
            subject = target.username
        candidate = CurrentUser(target.username, [target.role] if target.role else [])
        if subject and subject != "anonymous" and all(has_permission(core, candidate, permission)
            for permission in ("office.doc.read", "office.stage.move")):
            reviewers.append({"subject": subject, "name": target.full_name or target.username})
    return {"documents": documents, "reviewers": reviewers}


@router.get("/carriers", response_model=list[CarrierOut])
async def list_carriers() -> list[dict]:
    """Справочник перевозчиков для доставки по РБ (для кнопки в карточке)."""
    return CARRIERS


@router.post("/docs", response_model=OfficeDocOut, status_code=201, dependencies=[Depends(require_permission('office.doc.write'))])
async def create_doc(
    payload: OfficeDocCreate,
    session: AsyncSession = Depends(get_session),
    core: Core = Depends(get_core),
    user=Depends(get_current_user),
):
    """Создать документ по сделке. Номер генерируется автоматически, если не задан."""
    effective, actor = await current_actor(core, session, user, "office.doc.write")
    data = payload.model_dump()
    if not has_permission(core, effective, "office.shipping.review.assign"):
        if "stage" in payload.model_fields_set and payload.stage != "draft":
            raise HTTPException(403, "Create a draft and ask a supervisor to assign its reviewer")
        data["stage"] = "draft"
    data["amount"] = Decimal(str(data["amount"]))
    data["draft_owner_subject"] = actor
    obj = OfficeDoc(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ДОК-2026-{obj.id:04d}"
    events.emit_doc_created(core.event_bus, session, obj)
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/docs/{doc_id}", response_model=OfficeDocOut, dependencies=[Depends(require_permission('office.stage.move'))])
async def update_doc(
    doc_id: int,
    payload: StageUpdate,
    session: AsyncSession = Depends(get_session),
    core: Core = Depends(get_core),
    user=Depends(get_current_user),
):
    """Сменить стадию документа. Переход стадии эмитит событие соседнему отделу."""
    obj = await locked_doc(core, session, doc_id, user, "office.stage.move")
    if payload.stage not in {s["id"] for s in STAGES}:
        raise HTTPException(status_code=422, detail="Неизвестная стадия")

    if obj.stage == "draft" and payload.stage != "draft":
        effective, actor = await current_actor(core, session, user, "office.stage.move")
        assignment = await latest_assignment(session, obj.id)
        if not has_permission(core, effective, "office.shipping.review.assign") and (
            assignment is None or assignment.subject != actor
        ):
            raise HTTPException(403, "A supervisor must assign the draft reviewer before processing")

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


@router.post("/docs/{doc_id}/carrier-request", dependencies=[Depends(require_permission('office.carrier.request'))])
async def carrier_request(doc_id: int, payload: RequestInput,
    session: AsyncSession = Depends(shipping_transaction), core: Core = Depends(get_core),
    user=Depends(get_current_user)):
    """Persist one strict v1 request and its outbox event in the same transaction."""
    result = await OfficeShippingProducer(core).prepare(session, doc_id, payload, user)
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
#  Реестр юридических договоров
# --------------------------------------------------------------------------- #

@router.get("/contracts", response_model=list[LegalContractOut])
async def list_contracts(
    status: str | None = None,
    contract_type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Реестр договоров с фильтрами по статусу и типу."""
    q = select(LegalContract).order_by(LegalContract.id.desc())
    if status:
        q = q.where(LegalContract.status == status)
    if contract_type:
        q = q.where(LegalContract.contract_type == contract_type)
    return (await session.execute(q)).scalars().all()


@router.post("/contracts", response_model=LegalContractOut, status_code=201, dependencies=[Depends(require_permission('office.contract.write'))])
async def create_contract(
    payload: LegalContractCreate,
    session: AsyncSession = Depends(get_session),
):
    """Создать договор. Автономер ДОГ-{YYYY}-{NNNN} если number не задан."""
    from datetime import date

    data = payload.model_dump()
    obj = LegalContract(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        year = date.today().year
        obj.number = f"ДОГ-{year}-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/contracts/{contract_id}", response_model=LegalContractOut)
async def get_contract(contract_id: int, session: AsyncSession = Depends(get_session)):
    obj = await session.get(LegalContract, contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Договор не найден")
    return obj


@router.patch("/contracts/{contract_id}", response_model=LegalContractOut, dependencies=[Depends(require_permission('office.contract.write'))])
async def patch_contract(
    contract_id: int,
    payload: LegalContractPatch,
    session: AsyncSession = Depends(get_session),
):
    """Изменить статус, описание, дату истечения или сумму договора."""
    obj = await session.get(LegalContract, contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Договор не найден")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await session.commit()
    await session.refresh(obj)
    return obj


# --------------------------------------------------------------------------- #
#  Реестр юридических претензий
# --------------------------------------------------------------------------- #

@router.get("/claims", response_model=list[LegalClaimOut])
async def list_claims(
    status: str | None = None,
    claim_type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Реестр претензий с фильтрами по статусу и типу."""
    q = select(LegalClaim).order_by(LegalClaim.id.desc())
    if status:
        q = q.where(LegalClaim.status == status)
    if claim_type:
        q = q.where(LegalClaim.claim_type == claim_type)
    return (await session.execute(q)).scalars().all()


@router.post("/claims", response_model=LegalClaimOut, status_code=201, dependencies=[Depends(require_permission('office.claim.write'))])
async def create_claim(
    payload: LegalClaimCreate,
    session: AsyncSession = Depends(get_session),
):
    """Создать претензию. Автономер ПРЕТ-{YYYY}-{NNNN} если number не задан."""
    from datetime import date

    data = payload.model_dump()
    obj = LegalClaim(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        year = date.today().year
        obj.number = f"ПРЕТ-{year}-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.get("/claims/{claim_id}", response_model=LegalClaimOut)
async def get_claim(claim_id: int, session: AsyncSession = Depends(get_session)):
    obj = await session.get(LegalClaim, claim_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Претензия не найдена")
    return obj


@router.patch("/claims/{claim_id}", response_model=LegalClaimOut, dependencies=[Depends(require_permission('office.claim.write'))])
async def patch_claim(
    claim_id: int,
    payload: LegalClaimPatch,
    session: AsyncSession = Depends(get_session),
):
    """Изменить статус, resolved_at, описание или сумму претензии."""
    obj = await session.get(LegalClaim, claim_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Претензия не найдена")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await session.commit()
    await session.refresh(obj)
    return obj
