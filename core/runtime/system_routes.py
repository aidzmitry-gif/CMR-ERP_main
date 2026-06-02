"""Системные роуты ядра: health-check и интроспекция реестра подключённых модулей."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Approval, AuditLog, Counterparty, OutboxEvent, Sku
from core.runtime.deps import get_session

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Проверка живости приложения."""
    return {"status": "ok"}


@router.get("/system/modules")
async def system_modules(request: Request) -> dict:
    """Показать, что именно зарегистрировали загруженные модули.

    Это «живой пример» из §6: видно, как модуль подключается к ядру —
    какие роуты, события, процессы, права, виджеты и команды он отдал.
    """
    core = request.app.state.core
    return {
        "loaded_modules": core.loaded_modules,
        "routers": [{"module": r.module, "prefix": r.prefix} for r in core.routers],
        "events": [{"module": e.module, "event_type": e.event_type} for e in core.events],
        "workflows": [{"module": w.module, "name": w.name} for w in core.workflows],
        "permissions": [p.code for p in core.permissions],
        "roles": [{"name": r.name, "permissions": list(r.permissions)} for r in core.roles],
        "telegram_commands": [c.command for c in core.telegram_commands],
        "widgets": [{"key": w.key, "title": w.title} for w in core.widgets],
    }


@router.get("/system/events")
async def system_events(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Последние доменные события — журнал outbox (единый event log, часть 3)."""
    rows = (
        await session.execute(select(OutboxEvent).order_by(OutboxEvent.id.desc()).limit(20))
    ).scalars().all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "version": e.version,
            "created_at": str(e.created_at),
            "processed": e.processed_at is not None,
        }
        for e in rows
    ]


@router.get("/system/audit")
async def system_audit(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Неизменяемый журнал аудита (проекция событий, часть 5)."""
    rows = (
        await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(50))
    ).scalars().all()
    return [
        {"id": a.id, "ts": str(a.ts), "actor": a.actor, "action": a.action, "entity_ref": a.entity_ref}
        for a in rows
    ]


@router.get("/system/owner")
async def system_owner(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    """Панель владельца — AI Control Tower без AI (core-8, часть 11).

    Здоровье бизнеса одним взглядом: согласования (ожидают/всего), активность
    (события и аудит), справочники и состав подключённых модулей с их виджетами.
    """
    core = request.app.state.core

    async def _count(model, *where) -> int:
        query = select(func.count()).select_from(model)
        for condition in where:
            query = query.where(condition)
        return (await session.execute(query)).scalar() or 0

    return {
        "approvals_pending": await _count(Approval, Approval.status == "pending"),
        "approvals_total": await _count(Approval),
        "audit_count": await _count(AuditLog),
        "events_count": await _count(OutboxEvent),
        "counterparties": await _count(Counterparty),
        "skus": await _count(Sku),
        "modules": core.loaded_modules,
        "widgets": [{"key": w.key, "title": w.title} for w in core.widgets],
    }
