"""Согласования (human-in-the-loop) — лёгкий движок без Temporal.

Запрос на согласование висит в БД (переживает рестарт), маршрутизируется по
матрице ``kind → роль``, эскалируется по таймеру фоновым воркером. События идут
через outbox (часть 3). Реальный Temporal подключается позже без смены контракта
(§ часть 4 архитектуры).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Approval

# Матрица согласований: kind -> (роль-согласующий, SLA в часах до эскалации).
ROUTES: dict[str, tuple[str, int]] = {
    "deal.contract": ("Юрист", 24),
    "deal.discount": ("РОП", 4),
    "payment.large": ("Главбух", 8),
}
DEFAULT_ROUTE: tuple[str, int] = ("РОП", 24)
ESCALATION_STEP_HOURS = 24


def _utcnow() -> datetime:
    # наивный UTC — единообразно для SQLite и PostgreSQL
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApprovalRequest(BaseModel):
    kind: str
    requested_by: str = ""


class ApprovalDecision(BaseModel):
    by: str = ""
    reason: str | None = None


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    entity_ref: str
    subject: str
    route: str
    status: str
    requested_by: str
    decided_by: str | None = None
    reason: str | None = None
    escalation_level: int
    created_at: datetime | None = None
    due_at: datetime | None = None
    decided_at: datetime | None = None


class ApprovalService:
    """Движок согласований: запрос, решение, эскалация. События — через outbox."""

    def __init__(self, event_bus) -> None:
        self.event_bus = event_bus

    async def request(
        self,
        session: AsyncSession,
        kind: str,
        entity_ref: str,
        subject: str,
        requested_by: str = "",
    ) -> Approval:
        route, sla_hours = ROUTES.get(kind, DEFAULT_ROUTE)
        approval = Approval(
            kind=kind,
            entity_ref=entity_ref,
            subject=subject,
            route=route,
            requested_by=requested_by,
            due_at=_utcnow() + timedelta(hours=sla_hours),
        )
        session.add(approval)
        await session.flush()
        self.event_bus.emit(
            session,
            "approval.requested",
            {"id": approval.id, "kind": kind, "entity_ref": entity_ref, "route": route},
        )
        return approval

    async def decide(
        self,
        session: AsyncSession,
        approval: Approval,
        approved: bool,
        by: str = "",
        reason: str | None = None,
    ) -> Approval:
        approval.status = "approved" if approved else "rejected"
        approval.decided_by = by
        approval.reason = reason
        approval.decided_at = _utcnow()
        self.event_bus.emit(
            session,
            f"approval.{approval.status}",
            {"id": approval.id, "kind": approval.kind, "entity_ref": approval.entity_ref, "by": by},
        )
        return approval

    async def escalate_once(self, session: AsyncSession) -> int:
        """Поднять уровень эскалации у просроченных ожидающих согласований."""
        now = _utcnow()
        rows = (
            await session.execute(
                select(Approval).where(
                    Approval.status == "pending",
                    Approval.due_at.is_not(None),
                    Approval.due_at < now,
                )
            )
        ).scalars().all()
        for approval in rows:
            approval.escalation_level += 1
            approval.due_at = now + timedelta(hours=ESCALATION_STEP_HOURS)
            self.event_bus.emit(
                session,
                "approval.escalated",
                {"id": approval.id, "level": approval.escalation_level, "route": approval.route},
            )
        if rows:
            await session.commit()
        return len(rows)
