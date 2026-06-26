"""Системные роуты ядра: health-check и интроспекция реестра подключённых модулей."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import ACCESS_MATRIX, ROLE_ORDER, ROLE_TITLES, users_with_titles
from core.domain.models import Approval, AuditLog, Counterparty, OutboxEvent, Sku, SyncLink
from core.domain.reference import NomenclatureCategory
from core.runtime.access import roles_from_request
from core.runtime.deps import get_session
from core.services import mdm, reference_query, tnved
from core.services.auth import CurrentUser, require_permission

#: предел подъёма по дереву групп при построении breadcrumb (защита от цикла parent_id).
_GROUP_PATH_MAX_DEPTH = 32

router = APIRouter(tags=["system"])

# Системные мутации (MDM/справочники) живут под открытым префиксом /system (его пропускает
# middleware матрицы доступа), поэтому защищаем их пообъектно на уровне роута: право
# `system.write` есть только у супер-ролей (Админ/director/commercial), см. has_permission.
# Гость и обычные роли получают 403. SECURITY.md P0-2.
SYSTEM_WRITE = "system.write"


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


@router.get("/system/mdm/rules")
async def mdm_rules(
    entity_type: str | None = None, session: AsyncSession = Depends(get_session)
) -> dict:
    """Правила слияния (survivorship, M2): за каким источником закреплено каждое поле.

    Витрина ``survivorship_rule`` — чем синк из 1С не имеет права затереть ручную правку/
    реквизит ЕГР. ``entity_type`` фильтрует (counterparty/sku). Только чтение (метаданные
    политики, не PII) — под общим /system без отдельного права.
    """
    return {"rules": await mdm.survivorship_rules(session, entity_type)}


@router.get("/system/tnved/lookup")
async def tnved_lookup(
    code: str, on: date, session: AsyncSession = Depends(get_session)
) -> dict:
    """Таможенные ставки по коду ТН ВЭД на дату ``on`` — вход расчёта landed cost.

    Один lookup отдаёт пошлину (ЕТТ ЕАЭС) и ставку НДС, действовавшие на дату оформления
    (НДС резолвится из ``ref_vat_rate`` по мягкой ссылке ``vat_code``). 404 — нет версии
    кода на эту дату. ``on`` обязателен (дата оформления), чтобы ставка была исторически
    корректной — расчёт не должен молча брать «сегодняшнюю».
    """
    result = await tnved.resolve(session, code, on)
    if result is None:
        raise HTTPException(status_code=404, detail="код ТН ВЭД не найден на эту дату")
    return result


@router.get("/system/mdm/fuzzy")
async def mdm_fuzzy(
    name: str, exclude_id: int | None = None, session: AsyncSession = Depends(get_session)
) -> dict:
    """Похожие по имени контрагенты — fuzzy-кандидаты на дедуп (опечатки/орг-форма, без УНП).

    Кандидаты на ручную проверку (approval), не авто-merge. Дополняет точный матч по УНП.
    """
    return {"candidates": await mdm.fuzzy_candidates(session, name=name, exclude_id=exclude_id)}


@router.post("/system/mdm/merge")
async def mdm_merge(
    request: Request,
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
) -> dict:
    """Слить дубль в эталон (survivorship + архив дубля + alias). Обратимо через unmerge."""
    core = request.app.state.core
    try:
        survivor = await mdm.merge(
            session, core.event_bus, int(payload["survivor_id"]), int(payload["duplicate_id"]),
            by=user.username,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": survivor.id, "name": survivor.name, "unp": survivor.unp}


@router.post("/system/mdm/unmerge")
async def mdm_unmerge(
    request: Request,
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
) -> dict:
    """Расклеить ранее слитый дубль (вернуть активность, убрать merge-alias)."""
    core = request.app.state.core
    try:
        duplicate = await mdm.unmerge(
            session, core.event_bus, int(payload["duplicate_id"]), by=user.username
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"id": duplicate.id, "is_active": duplicate.is_active}


@router.get("/system/mdm/counterparty/{counterparty_id}")
async def mdm_counterparty_card(
    counterparty_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("sales.deal.read")),
) -> dict:
    """Карточка эталона контрагента: реквизиты + источники (1С/Bitrix), дубли, контакты, аудит, 360°.

    История касаний (звонки/письма/сделки, M5) читается через ``core.services.touch_history`` —
    если модуль sales не подключён/не реализовал фасад, ``touches=[]`` (graceful, карточка без 360°).
    ⚠ Под правом ``sales.deal.read``: карточка несёт контакты (PII) и историю общения (тексты
    переписки/транскрипты — коммерческая тайна), а ``/system`` пропускается middleware → защищаем
    пообъектно (как карточка SKU/landed cost в M4). Реализация фасада в sales — своя проверка прав.
    """
    card = await mdm.counterparty_card(session, counterparty_id)
    if card is None:
        raise HTTPException(status_code=404, detail="контрагент не найден")

    gateway = request.app.state.core.services.touch_history
    card["touches"] = []
    card["touch_summary"] = None
    if gateway is not None:
        try:
            card["touches"] = await gateway.touches(session, counterparty_id)
            card["touch_summary"] = await gateway.summary(session, counterparty_id)
        except Exception:  # noqa: BLE001 — sales недоступен → карточка без истории, не 500
            pass
    return card


@router.get("/system/sku/{code}")
async def sku_card(
    code: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("sales.deal.read")),
) -> dict:
    """Карточка номенклатуры (мастер-данные): горячие поля + категория + себестоимость (фасад, M4).

    Себестоимость (landed cost) читается через ``core.services.landed_cost`` — если модуль
    procurement не подключён или расчёта нет, поле ``None`` (не 0 — отсутствие не маскируем).
    ⚠ Под правом ``sales.deal.read``: ``landed_cost`` — коммерческая тайна (себес/маржа),
    а ``/system`` пропускается middleware → защищаем пообъектно (как MDM-мутации).
    """
    sku = (
        await session.execute(select(Sku).where(Sku.code == code))
    ).scalars().first()
    if sku is None:
        raise HTTPException(status_code=404, detail="номенклатура не найдена")

    landed = None
    gateway = request.app.state.core.services.landed_cost
    if gateway is not None:
        try:
            landed = await gateway.last_landed_cost(session, code)
        except Exception:  # noqa: BLE001 — БД/сеть procurement недоступна → карточка без себеса, не 500
            landed = None

    # Эффективный ТН ВЭД: свой код товара или унаследованный от группы (вверх по дереву).
    effective_tnved = await tnved.effective_code_for_sku(session, sku)

    # Ставки по эффективному коду на сегодня (пошлина + НДS) — для блока «Учёт и налоги».
    # None, если кода нет или нет версии на дату (отсутствие не маскируем — см. tnved.resolve).
    tnved_rates = None
    if effective_tnved.get("code"):
        tnved_rates = await tnved.resolve(session, effective_tnved["code"], date.today())

    group_path = await _group_breadcrumb(session, sku.category_id)
    sync = await _sku_sync_link(session, sku.id)

    return {
        "code": sku.code,
        "title": sku.title,
        "unit": sku.unit,
        "category_id": sku.category_id,
        "group_path": group_path,  # [{code, name}, …] от корня к группе товара (breadcrumb)
        "weight_kg": sku.weight_kg,
        "tnved_code": sku.tnved_code,  # собственный код (может быть None → наследуется)
        "effective_tnved": effective_tnved,  # {code, source: own|group|None, group_code, group_name}
        "tnved_rates": tnved_rates,  # {duty_rate, vat_rate, …} на сегодня или None
        "shelf_life_days": sku.shelf_life_days,
        "is_active": sku.is_active,
        "attributes": sku.attributes,
        "provenance": sku.provenance,
        "landed_cost": landed,  # None — нет расчёта/модуль не подключён (не 0)
        "sync": sync,  # {origin, state, last_synced_at, external_ref} или None — синк из 1С
    }


async def _group_breadcrumb(session: AsyncSession, category_id: int | None) -> list[dict]:
    """Путь по дереву групп от корня к группе товара: ``[{code, name}, …]``.

    Поднимается по ``parent_id`` (как ``tnved.effective_code_for_sku``), ограничен глубиной —
    защита от цикла. Пустой список, если у товара нет группы.
    """
    if category_id is None:
        return []
    chain: list[dict] = []
    cat_id: int | None = category_id
    for _ in range(_GROUP_PATH_MAX_DEPTH):
        cat = await session.get(NomenclatureCategory, cat_id)
        if cat is None:
            break
        chain.append({"code": cat.code, "name": cat.name})
        if cat.parent_id is None:
            break
        cat_id = cat.parent_id
    chain.reverse()  # от корня к листу
    return chain


async def _sku_sync_link(session: AsyncSession, sku_id: int) -> dict | None:
    """Связь товара с 1С (M3): происхождение и статус выгрузки. None — связи нет."""
    link = (
        await session.execute(
            select(SyncLink).where(
                SyncLink.entity_type == "sku", SyncLink.entity_id == sku_id
            )
        )
    ).scalars().first()
    if link is None:
        return None
    return {
        "origin": link.origin,  # erp | 1c | bitrix — где запись родилась
        "state": link.state,  # local | pending | synced | error
        "external_ref": link.external_ref,
        "last_synced_at": str(link.last_synced_at) if link.last_synced_at else None,
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
