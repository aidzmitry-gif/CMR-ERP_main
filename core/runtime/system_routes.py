"""Системные роуты ядра: health-check и интроспекция реестра подключённых модулей."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.access import ACCESS_MATRIX, ROLE_ORDER, ROLE_TITLES, users_with_titles
from core.domain.models import Approval, AuditLog, Counterparty, OutboxEvent, Sku, SyncLink
from core.domain.reference import NomenclatureCategory, SkuVersion, VatRate
from core.runtime.access import roles_from_request
from core.runtime.deps import get_session
from core.services import (
    mdm,
    reference_quality,
    reference_query,
    scd2,
    sku_history,
    sku_master,
    tnved,
)
from core.services.auth import CurrentUser, require_permission

#: предел подъёма по дереву групп при построении breadcrumb (защита от цикла parent_id).
_GROUP_PATH_MAX_DEPTH = 32

#: свободные атрибуты карточки SKU, наследуемые от группы (ключи в Sku/Category.attributes).
#: «производительские» (Производитель/Марка/Импортёр) + упаковка/габариты для калькулятора себеса.
_INHERITABLE_ATTR_KEYS = (
    "Производитель", "Марка", "Бренд", "Импортёр",
    "Кол-во в коробке", "Габариты", "Объём",
)

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
            "params": ["ref", "key", "as_of", "name", "category_id",
                       "aggregate", "group_by", "resolve", "limit"],
            "note": "точные значения структурно, с историчностью as_of; pgvector — вторично",
            "capabilities": {
                "aggregate": {
                    "count": list(reference_query._COUNTABLE.keys()),
                    "group_by": {k: sorted(v) for k, v in reference_query._AGG_GROUP_BY.items()},
                    "note": "count/group_by по whitelist — сырой SQL от AI запрещён",
                },
                "resolve": {
                    "core.skus": "SKU + эффективные ТН ВЭД/НДС/ед/страна (own ∨ от группы)",
                },
            },
            # отдельный read-эндпоинт (не reference.query): мастер-входы landed cost по SKU
            "related": [
                {
                    "name": "sku.landed_inputs",
                    "endpoint": "/system/sku/{code}/landed-inputs",
                    "params": ["on_date"],
                    "note": "пошлина ТН ВЭД+НДС (на дату) + вес/объём/страна с провенансом по полю",
                },
            ],
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


#: верхний предел строк одного structural-query (защита от data-volume через большой limit).
# 250 — с запасом над реальными 232 SKU (backfill 1С, нояб.2024); растёт вместе с каталогом.
_QUERY_LIMIT_MAX = 250


@router.post("/system/references/query")
async def references_query(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Структурный lookup AI по справочнику (tool reference.query): точное значение с историчностью.

    Под правом ``refs.view``: отдаёт коммерческие мастер-данные (контрагенты/номенклатура),
    ``/system`` пропускается middleware → защищаем пообъектно (как quality/MDM-карточки).
    """
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
        category_id = payload.get("category_id")
        category_id = int(category_id) if category_id is not None else None
        limit = max(1, min(int(payload.get("limit", 10)), _QUERY_LIMIT_MAX))  # clamp от DoS
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="category_id/limit должны быть числами") from exc
    try:
        return await reference_query.query(
            session,
            ref,
            key=payload.get("key"),
            as_of=as_of,
            name=payload.get("name"),
            category_id=category_id,
            aggregate=payload.get("aggregate"),
            group_by=payload.get("group_by"),
            resolve=bool(payload.get("resolve")),
            limit=limit,
        )
    except reference_query.ReferenceQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _quality_by_kind(issues: list[dict]) -> dict:
    """Свернуть проблемы по классам (для колонок дашборда: пропуски/дубли/битые/сироты)."""
    out = {"missing": 0, "duplicate": 0, "broken_ref": 0, "orphan": 0}
    for i in issues:
        out[i["kind"]] = out.get(i["kind"], 0) + i["count"]
    return out


@router.get("/system/references/quality")
async def references_quality(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Сводка качества по всем справочникам: score + число проблем по классам (под ``refs.view``).

    Пересчёт на запрос (# ponytail: материализованная вьюха/кэш, если станет тяжело).
    """
    rows = await reference_quality.audit_all(session)
    return {
        "references": [
            {
                "ref": r["ref"],
                "title": r["title"],
                "total": r["total"],
                "score": r["score"],
                "issues_count": sum(i["count"] for i in r["issues"]),
                "by_kind": _quality_by_kind(r["issues"]),
            }
            for r in rows
        ]
    }


@router.get("/system/references/quality/{ref_key}")
async def reference_quality_detail(
    ref_key: str,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Детализация качества одного справочника: issues + sample_keys (под ``refs.view``)."""
    res = await reference_quality.audit_reference(session, ref_key)
    if res is None:
        raise HTTPException(status_code=404, detail="справочник без проверок качества")
    return res


@router.get("/system/mdm/duplicates")
async def mdm_duplicates(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Кластеры дублей контрагентов по УНП — кандидаты на слияние (golden record).

    Под ``refs.view``: УНП/имена контрагентов — коммерческие мастер-данные; ``/system``
    пропускается middleware → защищаем пообъектно.
    """
    return {"clusters": await mdm.duplicate_clusters(session)}


@router.get("/system/mdm/import-preview")
async def mdm_import_preview(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Dry-run предпросмотр импорта контрагентов из кэша 1С → MDM (REF3-9): сколько создалось бы /
    совпало по УНП / без УНП — БЕЗ единой записи. Реальный прогон (upsert/дедуп) — зона Синк.

    Фасад 1С не подключён (``core.services.onec is None``) → 503 graceful (не 500). Под ``refs.view``
    (мастер-данные контрагентов; ``/system`` минует middleware → защищаем пообъектно).
    """
    onec = request.app.state.core.services.onec
    if onec is None:
        raise HTTPException(status_code=503, detail="фасад 1С не подключён (модуль integrations)")
    return await mdm.import_preview(session, onec)


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
    name: str,
    exclude_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("refs.view")),
) -> dict:
    """Похожие по имени контрагенты — fuzzy-кандидаты на дедуп (опечатки/орг-форма, без УНП).

    Кандидаты на ручную проверку (approval), не авто-merge. Дополняет точный матч по УНП.
    Под ``refs.view``: имена контрагентов — коммерческие мастер-данные (см. mdm_duplicates).
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

    # Прочие «общие данные группы», наследуемые товаром (ед.изм/страна по умолчанию, ставка НДС
    # по умолчанию группы). Тот же обход вверх по дереву; источник (own|group) — для метки «↑ из группы».
    effective_unit = await tnved.effective_group_field(session, sku, "unit")
    # Страна: типизированная колонка country (своя ∨ группы). Фоллбэк на свободный JSONB-ключ
    # «Страна происхождения»/«Страна» — легаси-данные (синк 1С пишет туда), чтобы страна не
    # пропадала с карточки, когда типизированной колонки ещё нет. Типизированная важнее.
    effective_country = await tnved.effective_group_field(session, sku, "country")
    if effective_country["value"] is None:
        for legacy_key in ("Страна происхождения", "Страна"):
            legacy = await tnved.effective_group_attr(session, sku, legacy_key)
            if legacy["value"] is not None:
                effective_country = legacy
                break
    # НДС по умолчанию группы — отдельно от ТН-ВЭД-резолва: у Sku своего поля нет, берётся от группы.
    group_vat = await tnved.effective_group_field(session, sku, "vat_code")
    if group_vat.get("value"):
        vat_ver = await scd2.version_as_of(session, VatRate, "code", group_vat["value"], date.today())
        group_vat["rate"] = float(vat_ver.rate) if vat_ver is not None else None
    else:
        group_vat["rate"] = None

    # Свободные атрибуты с наследованием от группы (Производитель/Марка/Импортёр, упаковка/габариты):
    # свой ключ в Sku.attributes ∨ ключ группы вверх по дереву. {key: {value, source, group_*}} —
    # только непустые (нигде не задан → не кладём). Карточка по ним рисует «↑ из группы» / «задано здесь».
    effective_attrs: dict[str, dict] = {}
    for key in _INHERITABLE_ATTR_KEYS:
        eff = await tnved.effective_group_attr(session, sku, key)
        if eff["value"] is not None:
            effective_attrs[key] = eff

    group_path = await _group_breadcrumb(session, sku.category_id)
    sync = await _sku_sync_link(session, sku.id)

    # Остатки/цена/себестоимость по складам (зеркало 1С) — через фасад stock (integrations).
    # None, если модуль выключен или по коду остатков нет (отсутствие не маскируем нулём).
    stock = None
    batches = None
    stock_gw = request.app.state.core.services.stock
    if stock_gw is not None:
        try:
            stock = await stock_gw.stock_by_sku(session, code)
        except Exception:  # noqa: BLE001 — integrations недоступен → карточка без остатка, не 500
            stock = None
        try:
            batches = await stock_gw.batches_by_sku(session, code)
        except Exception:  # noqa: BLE001 — нет фасада/партий → карточка без партий, не 500
            batches = None

    # История мастер-характеристик (SCD2): датированные версии, новая — первой. Пусто, пока
    # версий не записывали (record_sku_version из точки правки SKU). Только мастер-данные.
    history = [
        {
            "start_date": v.start_date,
            "end_date": v.end_date,
            # проекция мастер-полей — единый источник sku_history.SNAPSHOT_FIELDS (DRY, без ручного дубля)
            **{f: getattr(v, f) for f in sku_history.SNAPSHOT_FIELDS},
        }
        for v in (
            await session.execute(
                select(SkuVersion)
                .where(SkuVersion.sku_code == code)
                .order_by(SkuVersion.start_date.desc())
            )
        ).scalars().all()
    ]

    return {
        "code": sku.code,
        "title": sku.title,
        "unit": sku.unit,
        "category_id": sku.category_id,
        "group_path": group_path,  # [{code, name}, …] от корня к группе товара (breadcrumb)
        "weight_kg": sku.weight_kg,
        "volume_m3": sku.volume_m3,  # объём м³ — вход разнесения фрахта по объёму
        "vat_code": sku.vat_code,  # свой код НДС (None → наследуется от группы, см. group_vat)
        "tnved_code": sku.tnved_code,  # собственный код (может быть None → наследуется)
        "effective_tnved": effective_tnved,  # {code, source: own|group|None, group_code, group_name}
        "tnved_rates": tnved_rates,  # {duty_rate, vat_rate, …} на сегодня или None
        "effective_unit": effective_unit,  # {value, source, group_*} — ед.изм своя ∨ от группы
        "effective_country": effective_country,  # {value, source, group_*} — страна своя ∨ от группы
        "group_vat": group_vat,  # {value(код), rate, source, group_*} — НДС по умолч. группы или None
        "effective_attrs": effective_attrs,  # {ключ: {value, source: own|group, group_*}} — своё ∨ от группы
        "shelf_life_days": sku.shelf_life_days,
        "is_active": sku.is_active,
        "attributes": sku.attributes,
        "provenance": sku.provenance,
        "landed_cost": landed,  # None — нет расчёта/модуль не подключён (не 0)
        "sync": sync,  # {origin, state, last_synced_at, external_ref} или None — синк из 1С
        "stock": stock,  # {rows, total_available, price, cost, …} из 1С или None — нет остатков
        "batches": batches,  # {rows, total_qty, nearest_expiry} партии+FEFO или None — нет партий
        "history": history,  # [{start_date, end_date, …}] версии мастер-характеристик (SCD2), новые сверху
    }


@router.get("/system/sku/{code}/landed-inputs")
async def sku_landed_inputs(
    code: str,
    on_date: date | None = None,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_permission("sales.deal.read")),
) -> dict:
    """Мастер-входы landed cost по SKU на дату — те же числа, что считает закупка (REF3-2).

    Тонкая обёртка над ``core.services.sku_master.landed_inputs``: эффективная пошлина ТН ВЭД +
    ставка НДС (на дату), вес/объём/страна/ед. + провенанс по каждому полю. Дефолт ``on_date`` —
    сегодня; ``on_date`` до открытия версии ТН ВЭД → ставки ``None`` (не падение). 404 — нет SKU.
    ⚠ Под правом ``sales.deal.read``: несёт коммерческий вход маржи (себестоимость), а ``/system``
    пропускается middleware → защищаем пообъектно (как карточка SKU/landed cost).
    """
    result = await sku_master.landed_inputs(session, code, on_date)
    if result is None:
        raise HTTPException(status_code=404, detail="номенклатура не найдена")
    return result


#: мастер-поля SKU, правимые через витрину. Совпадают со снимком истории (sku_history.SNAPSHOT_FIELDS):
#: что версионируем, то и правим. Операционные (цена/остаток/себес) — НЕ здесь (владелец 1С/склад).
_SKU_EDITABLE = sku_history.SNAPSHOT_FIELDS


@router.patch("/system/sku/{code}")
async def update_sku(
    code: str,
    request: Request,
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
) -> dict:
    """Правка мастер-полей номенклатуры (витрина) + датированная версия истории (SCD2, REF3-8).

    Смена ``weight_kg``/``volume_m3``/``tnved_code``/``vat_code``/… фиксирует снимок в
    ``ref_sku_version`` через единый путь ``sku_history.record_sku_version`` (идемпотентно — без
    изменений версию не плодим). Правка в тот же день, что уже открытая версия, обновляет её
    снимок на месте (SCD2 запрещает две версии с одной даты). Под ``system.write`` (мутация
    мастер-данных, как прочие справочники — право не ослабляем); эмитит ``reference.sku.changed``
    (ref_key=core.skus) — downstream-сигнал смены ТН ВЭД/НДС товара (REF3-7).

    История стартует с ПЕРВОЙ правки: первая версия фиксирует ПОСТ-правочное состояние (дату начала
    исходного значения мы не знаем — у Sku нет created_at), поэтому ``as_of`` до первой правки →
    None (а не «нули»). Сам факт смены аудируется ``reference.sku.changed``; живой расчёт маржи
    читает поля из ``Sku`` напрямую (``sku_master``), а не из истории, и от этого не страдает.
    """
    sku = (await session.execute(select(Sku).where(Sku.code == code))).scalars().first()
    if sku is None:
        raise HTTPException(status_code=404, detail="номенклатура не найдена")
    # реально изменившиеся мастер-поля (значение отличается). no-op PATCH — те же значения ИЛИ без
    # мастер-полей в payload — не эмитит событие и не плодит версию: downstream без ложного пересчёта.
    changed = [f for f in _SKU_EDITABLE if f in payload and getattr(sku, f) != payload[f]]
    for field in changed:
        setattr(sku, field, payload[field])
    if changed:
        try:
            await sku_history.record_sku_version(session, sku, date.today())
        except ValueError:
            # повторная правка в тот же день: SCD2 не открывает вторую версию с той же даты —
            # обновляем снимок текущей открытой версии на месте (today-версия = последнее состояние дня).
            current = await scd2.current_version(session, SkuVersion, "sku_code", sku.code)
            if current is not None:
                for field in sku_history.SNAPSHOT_FIELDS:
                    setattr(current, field, getattr(sku, field))
        request.app.state.core.event_bus.emit(
            session,
            "reference.sku.changed",
            {"action": "update", "ref_key": "core.skus", "entity_ref": f"sku:{code}",
             "value_hint": ",".join(changed), "actor": user.username},
        )
    await session.commit()
    return {"code": sku.code, "changed": changed}


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
