"""Confirmed CRM owners use the employee link of an active local account."""
from __future__ import annotations

from collections import Counter

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import User

CRM_OWNER_ROLES = frozenset({"sales_head", "sales", "sales_manager", "sales_cli"})


def _eligible_owners():
    return select(User).where(
        User.employee_id.is_not(None),
        User.status == "active",
        User.department == "Продажи",
        User.role.in_(CRM_OWNER_ROLES),
    )


async def list_crm_owners(session: AsyncSession) -> list[User]:
    """Return real candidates addressable by the existing exact-name lead API."""
    owners = (await session.execute(
        _eligible_owners().order_by(User.employee_id).execution_options(populate_existing=True)
    )).scalars().all()
    counts = Counter(owner.full_name for owner in owners)
    return [owner for owner in owners if owner.full_name.strip() and counts[owner.full_name] == 1]


async def resolve_crm_owner(
    session: AsyncSession,
    *,
    employee_id: int | None = None,
    name: str | None = None,
    lock: bool = False,
) -> User:
    """Resolve an employee ID or an unambiguous exact display name.

    The optional row lock keeps eligibility stable until the caller commits.
    No fuzzy name matching or app_user primary-key fallback is allowed.
    """
    stmt = _eligible_owners()
    if employee_id is not None:
        stmt = stmt.where(User.employee_id == employee_id)
    elif name and name.strip():
        stmt = stmt.where(User.full_name == name)
    else:
        raise HTTPException(status_code=422, detail="Не выбран активный сотрудник CRM")
    if lock:
        stmt = stmt.with_for_update(read=True)
    owners = (await session.execute(
        stmt.execution_options(populate_existing=True)
    )).scalars().all()
    if not owners:
        raise HTTPException(status_code=422, detail="Владелец сделки не является активным сотрудником CRM")
    if len(owners) != 1:
        raise HTTPException(status_code=422, detail="Имя менеджера неоднозначно: выберите другого сотрудника CRM")
    return owners[0]
