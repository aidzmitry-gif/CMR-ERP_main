"""HTTP-API модуля HR. Монтируется под префиксом ``/hr``."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.runtime.deps import get_session
from modules.hr.models import Employee
from modules.hr.schemas import EmployeeCreate, EmployeeOut

router = APIRouter(tags=["hr"])


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
