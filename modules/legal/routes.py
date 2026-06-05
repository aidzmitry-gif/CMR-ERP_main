"""HTTP-API модуля Legal. Монтируется под префиксом ``/legal``."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.legal.models import LegalCase
from modules.legal.schemas import LegalCaseCreate, LegalCaseOut, StageUpdate
from modules.legal.stages import STAGES

router = APIRouter(tags=["legal"])


def _fmt_money(value: float) -> str:
    return f"{int(value):,} ₽".replace(",", " ")


def _to_card(r: LegalCase) -> FunnelCard:
    # Разворот «что нужно сделать» по претензии: ключ-значение, как в референсе
    details: list[dict[str, str]] = []
    if r.stage == "claim" and r.amount:
        debt = float(r.amount)
        details = [
            {"k": "Сумма долга", "v": _fmt_money(debt)},
            {"k": "Неустойка (пени)", "v": _fmt_money(debt * 0.08)},
            {"k": "Способ", "v": "Почта + ЭДО"},
        ]
    action = "Открыть документ →" if r.stage in ("claim", "writ", "court") else ""
    return FunnelCard(
        id=r.id,
        code=r.number or f"ДЕЛО-{r.id}",
        title=r.company,
        subtitle=r.title,
        amount=float(r.amount),
        priority=r.urgency,
        owner=r.owner,
        date=r.due_date or "",
        next_step=r.next_step,
        details=details,
        action=action,
    )


@router.get("/cases", response_model=list[LegalCaseOut])
async def list_cases(session: AsyncSession = Depends(get_session)):
    """Юр-дела и документы (плоский список)."""
    return (await session.execute(select(LegalCase).order_by(LegalCase.id.desc()))).scalars().all()


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> FunnelBoardOut:
    """Воронка юр-отдела: дела сгруппированы по стадиям контроля и взыскания."""
    rows = (await session.execute(select(LegalCase))).scalars().all()
    return build_board(STAGES, rows, _to_card)


@router.post("/cases", response_model=LegalCaseOut, status_code=201)
async def create_case(payload: LegalCaseCreate, session: AsyncSession = Depends(get_session)):
    """Создать дело. Номер генерируется автоматически, если не задан."""
    data = payload.model_dump()
    data["amount"] = Decimal(str(data["amount"]))
    obj = LegalCase(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"ДЕЛО-2026-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/cases/{case_id}", response_model=LegalCaseOut)
async def update_case(
    case_id: int, payload: StageUpdate, session: AsyncSession = Depends(get_session)
):
    """Сменить стадию юр-дела."""
    obj = await session.get(LegalCase, case_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    obj.stage = payload.stage
    await session.commit()
    await session.refresh(obj)
    return obj
