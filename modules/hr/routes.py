"""HTTP-API модуля HR. Монтируется под префиксом ``/hr``."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from core.runtime.funnel import FunnelBoardOut, FunnelCard, build_board
from modules.hr.models import Candidate, Employee
from modules.hr.schemas import (
    CandidateCreate,
    CandidateOut,
    EmployeeCreate,
    EmployeeOut,
    StageUpdate,
)
from modules.hr.stages import STAGES

router = APIRouter(tags=["hr"])


# --- Сотрудники (штат) ---


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(session: AsyncSession = Depends(get_session)):
    """Сотрудники."""
    return (await session.execute(select(Employee).order_by(Employee.id.desc()))).scalars().all()


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(payload: EmployeeCreate, session: AsyncSession = Depends(get_session)):
    """Добавить сотрудника."""
    obj = Employee(**payload.model_dump())
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return obj


# --- Воронка подбора (кандидаты) ---


def _to_card(r: Candidate) -> FunnelCard:
    return FunnelCard(
        id=r.id,
        code=r.number or f"CAND-{r.id}",
        title=r.name,
        subtitle=r.position,
        amount=float(r.salary),
        priority=r.priority,
        owner=r.recruiter,
        next_step=r.next_step,
    )


@router.get("/candidates", response_model=list[CandidateOut])
async def list_candidates(session: AsyncSession = Depends(get_session)):
    """Кандидаты (плоский список)."""
    return (await session.execute(select(Candidate).order_by(Candidate.id.desc()))).scalars().all()


@router.get("/board", response_model=FunnelBoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> FunnelBoardOut:
    """Воронка подбора: кандидаты сгруппированы по этапам найма."""
    rows = (await session.execute(select(Candidate))).scalars().all()
    return build_board(STAGES, rows, _to_card)


@router.post("/candidates", response_model=CandidateOut, status_code=201)
async def create_candidate(payload: CandidateCreate, session: AsyncSession = Depends(get_session)):
    """Создать кандидата. Номер генерируется автоматически, если не задан."""
    data = payload.model_dump()
    data["salary"] = Decimal(str(data["salary"]))
    obj = Candidate(**data)
    session.add(obj)
    await session.flush()
    if not obj.number:
        obj.number = f"CAND-2026-{obj.id:04d}"
    await session.commit()
    await session.refresh(obj)
    return obj


@router.patch("/candidates/{cand_id}", response_model=CandidateOut)
async def update_candidate(
    cand_id: int, payload: StageUpdate, session: AsyncSession = Depends(get_session)
):
    """Сменить этап подбора кандидата."""
    obj = await session.get(Candidate, cand_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    obj.stage = payload.stage
    await session.commit()
    await session.refresh(obj)
    return obj
