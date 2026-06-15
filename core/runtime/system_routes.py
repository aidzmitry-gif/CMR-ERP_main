"""Системные роуты ядра: health-check и интроспекция реестра подключённых модулей."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import ACCESS_MATRIX, ROLE_ORDER, ROLE_TITLES, users_with_titles
from core.domain.models import Approval, AuditLog, Counterparty, OutboxEvent, Sku
from core.runtime.access import roles_from_request
from core.runtime.deps import get_session
from core.services import mdm, reference_query

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Проверка живости приложения."""
    return {"status": "ok"}


@router.get("/system/access")
async def system_access(request: Request) -> dict:
    """Матрица доступа ролей к модулям (единый источник — ``config/access.py``).

    Фронт использует это, чтобы спрятать недоступные модули в сайдбаре и нарисовать
    dev-переключатель роли. ``current_roles`` — роли текущего запроса (заголовок
    ``X-User-Roles``); по ним фронт считает доступные модули без знания матрицы.
    """
    return {
        "matrix": ACCESS_MATRIX,
        "roles": [{"slug": s, "title": ROLE_TITLES.get(s, s)} for s in ROLE_ORDER],
        "current_roles": roles_from_request(request),
    }


@router.get("/system/users")
async def system_users() -> dict:
    """Список сотрудников для dev-логина (логин → ФИО + роль). Единый источник — config/access.py."""
    return {"users": users_with_titles()}


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


@router.get("/system/references")
async def system_references(request: Request) -> dict:
    """Каталог справочников, сгруппированный по отделам (реестр-витрина «Справочники»).

    Один источник для трёх целей: вкладка «Справочники» (UI-дерево + таблица), права
    на справочник (RBAC) и каталог для AI. Данные остаются у владельца (``owner_schema``),
    реестр отдаёт только метаданные.
    """
    core = request.app.state.core
    by_dept: dict[str, list[dict]] = {}
    for rr in core.references:
        r = rr.reference
        by_dept.setdefault(r.department, []).append(
            {
                "key": r.key,
                "title": r.title,
                "module": rr.module,
                "endpoint": r.endpoint,
                "owner_schema": r.owner_schema,
                "columns": [c.__dict__ for c in r.columns],
                "permissions": list(r.permissions),
                "archivable": r.archivable,
                "versioned": r.versioned,
                "ai_exposed": r.ai_exposed,
                "description": r.description,
            }
        )
    return {"departments": by_dept}


@router.get("/system/references/ai-catalog")
async def system_references_ai_catalog(request: Request) -> dict:
    """Узкий каталог только ``ai_exposed`` — машинный «что есть и как точно запросить».

    AI-агент берёт отсюда точные поля и эндпоинты, чтобы делать структурные запросы
    (не угадывать и не использовать эмбеддинги для точных значений).
    """
    core = request.app.state.core
    return {
        "tool": {
            "name": "reference.query",
            "endpoint": "/system/references/query",
            "params": ["ref", "key", "as_of", "name", "limit"],
            "note": "точные значения структурно, с историчностью as_of; pgvector — вторично",
        },
        "references": [
            {
                "key": rr.reference.key,
                "title": rr.reference.title,
                "endpoint": rr.reference.endpoint,
                "owner_schema": rr.reference.owner_schema,
                "versioned": rr.reference.versioned,
                "columns": [
                    {"name": c.name, "type": c.type, "semantic": c.semantic}
                    for c in rr.reference.columns
                ],
                "description": rr.reference.description,
            }
            for rr in core.references
            if rr.reference.ai_exposed
        ]
    }


@router.post("/system/references/query")
async def references_query(
    payload: dict = Body(...), session: AsyncSession = Depends(get_session)
) -> dict:
    """Структурный lookup AI по справочнику (tool reference.query): точное значение с историчностью."""
    ref = payload.get("ref")
    if not ref:
        raise HTTPException(status_code=422, detail="нужно поле ref")
    as_of = payload.get("as_of")
    if isinstance(as_of, str):
        try:
            as_of = date.fromisoformat(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of должен быть YYYY-MM-DD") from exc
    try:
        return await reference_query.query(
            session,
            ref,
            key=payload.get("key"),
            as_of=as_of,
            name=payload.get("name"),
            limit=int(payload.get("limit", 10)),
        )
    except reference_query.ReferenceQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/system/mdm/duplicates")
async def mdm_duplicates(session: AsyncSession = Depends(get_session)) -> dict:
    """Кластеры дублей контрагентов по УНП — кандидаты на слияние (golden record)."""
    return {"clusters": await mdm.duplicate_clusters(session)}


@router.post("/system/mdm/merge")
async def mdm_merge(
    request: Request, payload: dict = Body(...), session: AsyncSession = Depends(get_session)
) -> dict:
    """Слить дубль в эталон (survivorship + архив дубля + alias). Обратимо через unmerge."""
    core = request.app.state.core
    actor = next(iter(roles_from_request(request)), "")
    try:
        survivor = await mdm.merge(
            session, core.event_bus, int(payload["survivor_id"]), int(payload["duplicate_id"]),
            by=actor,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": survivor.id, "name": survivor.name, "unp": survivor.unp}


@router.post("/system/mdm/unmerge")
async def mdm_unmerge(
    request: Request, payload: dict = Body(...), session: AsyncSession = Depends(get_session)
) -> dict:
    """Расклеить ранее слитый дубль (вернуть активность, убрать merge-alias)."""
    core = request.app.state.core
    actor = next(iter(roles_from_request(request)), "")
    try:
        duplicate = await mdm.unmerge(
            session, core.event_bus, int(payload["duplicate_id"]), by=actor
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": duplicate.id, "is_active": duplicate.is_active}


@router.get("/system/mdm/counterparty/{counterparty_id}")
async def mdm_counterparty_card(
    counterparty_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """Карточка эталона контрагента: реквизиты + источники (1С/Bitrix), слитые дубли, контакты, аудит."""
    card = await mdm.counterparty_card(session, counterparty_id)
    if card is None:
        raise HTTPException(status_code=404, detail="контрагент не найден")
    return card


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


@router.get("/system/owner/insight")
async def system_owner_insight(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    """AI-инсайт по здоровью бизнеса — AI Control Tower (Итерация 1).

    Под-фича за feature-flag: 503 при выключенном AI. Метрики идут в общий шлюз
    ``core.services.llm``; AI-действие фиксируется событием ``ai.insight.generated``.
    """
    core = request.app.state.core
    llm = core.services.llm
    if not llm.enabled:
        raise HTTPException(status_code=503, detail="AI-слой выключен (feature-flag)")

    async def _count(model, *where) -> int:
        query = select(func.count()).select_from(model)
        for condition in where:
            query = query.where(condition)
        return (await session.execute(query)).scalar() or 0

    context = (
        f"Согласований ожидают: {await _count(Approval, Approval.status == 'pending')}. "
        f"Событий в шине: {await _count(OutboxEvent)}. "
        f"Контрагентов: {await _count(Counterparty)}."
    )
    text = await llm.complete(
        f"Метрики бизнеса: {context} Дай краткий инсайт и точку роста.",
        system="Ты — аналитик бизнеса. Дай инсайт по здоровью бизнеса на русском.",
        kind="insight",
    )
    model = llm.model or "mock"
    core.event_bus.emit(
        session, "ai.insight.generated", {"actor": "AI", "entity_ref": "owner", "model": model}
    )
    await session.commit()
    return {"text": text, "model": model}
