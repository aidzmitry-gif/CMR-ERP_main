"""API согласований (human-in-the-loop). Монтируется ядром."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Approval
from core.runtime.core import Core
from core.runtime.deps import get_core, get_session
from core.services.approvals import ApprovalDecision, ApprovalOut
from core.services.auth import require_permission

router = APIRouter(tags=["approvals"])


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    status: str | None = None,
    entity_ref: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("sales.deal.approve")),
):
    """Список согласований (фильтры: статус и/или сущность, например ``deal:7``)."""
    query = select(Approval).order_by(Approval.id.desc())
    if status:
        query = query.where(Approval.status == status)
    if entity_ref:
        query = query.where(Approval.entity_ref == entity_ref)
    return (await session.execute(query)).scalars().all()


async def _decide(
    approval_id: int,
    approved: bool,
    payload: ApprovalDecision,
    core: Core,
    session: AsyncSession,
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Согласование не найдено")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Согласование уже обработано")
    await core.services.approvals.decide(session, approval, approved, payload.by, payload.reason)
    await session.commit()
    return approval


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: int,
    payload: ApprovalDecision,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("sales.deal.approve")),
):
    return await _decide(approval_id, True, payload, core, session)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: int,
    payload: ApprovalDecision,
    core: Core = Depends(get_core),
    session: AsyncSession = Depends(get_session),
    _: object = Depends(require_permission("sales.deal.approve")),
):
    return await _decide(approval_id, False, payload, core, session)
