"""Generic-CRUD для системных справочников ядра (схема ``public``), под эндпоинты каталога.

Две фабрики роутеров — эталон, который модули переиспользуют для своих классификаторов:
- ``build_simple_ref_router`` — простой справочник: list (с архивом), create, patch,
  archive (мягкое удаление через ``is_active``);
- ``build_versioned_ref_router`` — версионный (SCD2): список версий, current, as-of,
  добавление новой версии с даты.

Транзакцию коммитит роут (вызывающий код владеет границей транзакции, §ядро).
Данные остаются у владельца — это CRUD поверх таблиц public, не второе хранилище.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import Date, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.reference import (
    Account,
    Bank,
    Country,
    Currency,
    CurrencyRate,
    NomenclatureCategory,
    Region,
    SkuVersion,
    TnvedCode,
    Unit,
    VatRate,
)
from core.runtime.deps import get_session
from core.services import scd2
from core.services.auth import CurrentUser, require_permission

# Мутации справочников живут под открытым /system/refs/* — защищаем пообъектно на роуте.
# Право `system.write` есть только у супер-ролей (см. has_permission). SECURITY.md P0-2.
SYSTEM_WRITE = "system.write"


def _row(obj, fields: tuple[str, ...]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def _coerce(model: type, field: str, value):
    """ISO-строку → ``date`` для Date-колонок (JSON шлёт строки; простой CRUD их не парсил).

    Прочие типы/значения возвращаем как есть; кривую дату — тоже как есть (валидацию отдаём БД).
    """
    if isinstance(value, str):
        col = model.__table__.columns.get(field)
        if col is not None and isinstance(col.type, Date):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return value
    return value


async def _by_key(session: AsyncSession, model: type, key_field: str, value):
    obj = (
        await session.execute(select(model).where(getattr(model, key_field) == value))
    ).scalars().first()
    if obj is None:
        raise HTTPException(status_code=404, detail="запись не найдена")
    return obj


def _emit_change(request: Request, session, model, action: str, key, actor: str) -> None:
    """Записать правку справочника в аудит (concept §8): outbox-событие → проекция в audit_log.

    Эмитится в той же транзакции, что и мутация (до commit) — at-least-once. ``entity_ref``
    указывает на конкретную запись справочника, ``actor`` — кто правил (личность из X-User).
    """
    request.app.state.core.event_bus.emit(
        session,
        f"reference.{model.__tablename__}.changed",
        {"action": action, "entity_ref": f"{model.__tablename__}:{key}", "actor": actor},
    )


#: чувствительные справочники — правка ставок/пошлин = деньги/налог (приоритет #1-2), не
#: применяется сразу, а уходит на согласование (human-in-the-loop). Только версионные ставки.
#: # ponytail: при необходимости добавить ref_account (структура плана счетов) — но он не
#: «ставка», а структура; пока модерация только на денежных ставках НДС/пошлины.
SENSITIVE_REFS = {"ref_vat_rate", "ref_tnved"}


async def _moderate_version(request: Request, session, model, key, payload, actor: str) -> dict | None:
    """Чувствительный ref → создать Approval (pending) вместо записи версии; иначе ``None``.

    Не изобретаем свою таблицу: используем ``core.services.approvals`` (Approval, эскалация по
    таймеру). Если движок согласований не подключён — не блокируем (``None``, # ponytail: в проде
    согласование обязательно для денежных ставок). Коммитит запрос (граница транзакции — роут).
    """
    if model.__tablename__ not in SENSITIVE_REFS:
        return None
    approvals = request.app.state.core.services.approvals
    if approvals is None:
        return None
    subject = f"Новая версия {model.__tablename__} «{key}» с {payload.get('start_date')}"
    approval = await approvals.request(
        session, "reference.change", f"{model.__tablename__}:{key}", subject, requested_by=actor
    )
    await session.commit()
    return {"status": "pending_approval", "approval_id": approval.id, "route": approval.route}


def build_simple_ref_router(
    model: type,
    *,
    fields: tuple[str, ...],
    editable: tuple[str, ...],
    required: tuple[str, ...] = (),
    key_field: str = "code",
) -> APIRouter:
    """Роутер простого справочника: list (с архивом), create, patch, archive."""
    router = APIRouter()

    @router.get("")
    async def list_items(
        archived: bool = False, session: AsyncSession = Depends(get_session)
    ) -> list[dict]:
        query = select(model)
        if not archived:
            query = query.where(model.is_active.is_(True))
        query = query.order_by(getattr(model, key_field))
        return [_row(o, fields) for o in (await session.execute(query)).scalars().all()]

    @router.post("")
    async def create_item(
        request: Request,
        payload: dict = Body(...),
        session: AsyncSession = Depends(get_session),
        user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    ) -> dict:
        missing = [k for k in required if k not in payload]
        if missing:
            raise HTTPException(status_code=422, detail=f"не хватает полей: {', '.join(missing)}")
        obj = model(**{k: _coerce(model, k, payload[k]) for k in editable if k in payload})
        session.add(obj)
        try:
            await session.flush()
        except IntegrityError as exc:
            # дубль уникального ключа (code уже есть) → 409, а не голый 500
            await session.rollback()
            raise HTTPException(
                status_code=409, detail=f"запись с таким {key_field} уже существует"
            ) from exc
        _emit_change(request, session, model, "create", getattr(obj, key_field), user.username)
        await session.commit()
        await session.refresh(obj)
        return _row(obj, fields)

    @router.patch("/{code}")
    async def update_item(
        code: str,
        request: Request,
        payload: dict = Body(...),
        session: AsyncSession = Depends(get_session),
        user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    ) -> dict:
        obj = await _by_key(session, model, key_field, code)
        for field in editable:
            if field in payload:
                setattr(obj, field, _coerce(model, field, payload[field]))
        _emit_change(request, session, model, "update", code, user.username)
        await session.commit()
        return _row(obj, fields)

    @router.delete("/{code}")
    async def archive_item(
        code: str,
        request: Request,
        session: AsyncSession = Depends(get_session),
        user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    ) -> dict:
        obj = await _by_key(session, model, key_field, code)
        obj.is_active = False
        _emit_change(request, session, model, "archive", code, user.username)
        await session.commit()
        return {"archived": code}

    @router.post("/bulk")
    async def bulk_upsert(
        request: Request,
        payload: dict = Body(...),
        session: AsyncSession = Depends(get_session),
        user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    ) -> dict:
        """Массовый идемпотентный upsert по ``key_field``: создать отсутствующие, обновить
        existing editable-поля. ``dry_run=true`` → план (would_create/would_update/conflicts)
        без записи. Реальный прогон эмитит ``bulk_upsert`` per-row (та же транзакция). Контрагенты
        НЕ через эту фабрику (их upsert/дедуп — зона Синк)."""
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise HTTPException(status_code=422, detail="нужно поле rows: список объектов")
        dry_run = bool(payload.get("dry_run"))
        existing = {
            getattr(o, key_field): o
            for o in (await session.execute(select(model))).scalars().all()
        }
        would_create: list[dict] = []
        would_update: list[dict] = []
        conflicts: list[dict] = []
        seen: set = set()
        for raw in rows:
            key = raw.get(key_field) if isinstance(raw, dict) else None
            if not key:
                conflicts.append({"key": None, "reason": f"нет поля {key_field}"})
                continue
            if key in seen:
                conflicts.append({"key": key, "reason": "дубль ключа в наборе"})
                continue
            seen.add(key)
            # коэрция ISO-дат и пр.: сравнение/запись против типов модели, не сырых строк
            coerced = {f: _coerce(model, f, raw[f]) for f in editable if f in raw}
            if key in existing:
                obj = existing[key]
                changes = {f: v for f, v in coerced.items() if getattr(obj, f) != v}
                if not changes:
                    continue  # идемпотентность: нет изменений — не трогаем, не эмитим
                would_update.append({"key": key, "changes": changes})
                if not dry_run:
                    for field, value in changes.items():
                        setattr(obj, field, value)
                    _emit_change(request, session, model, "bulk_upsert", key, user.username)
            else:
                missing = [f for f in required if not raw.get(f)]
                if missing:
                    conflicts.append({"key": key, "reason": f"не хватает: {', '.join(missing)}"})
                    continue
                would_create.append({"key": key})
                if not dry_run:
                    session.add(model(**coerced))
                    _emit_change(request, session, model, "bulk_upsert", key, user.username)
        if dry_run:
            return {
                "dry_run": True,
                "would_create": would_create,
                "would_update": would_update,
                "conflicts": conflicts,
            }
        try:
            await session.commit()
        except IntegrityError as exc:  # гонка/нарушение уникальности на коммите
            await session.rollback()
            raise HTTPException(status_code=409, detail="конфликт уникальности при bulk") from exc
        return {
            "created": len(would_create),
            "updated": len(would_update),
            "conflicts": conflicts,
        }

    return router


def build_versioned_ref_router(
    model: type,
    *,
    key_field: str,
    value_fields: tuple[str, ...],
    list_fields: tuple[str, ...],
) -> APIRouter:
    """Роутер версионного справочника (SCD2): список версий, current, as-of, добавить версию."""
    router = APIRouter()

    @router.get("")
    async def list_versions(
        key: str | None = None, session: AsyncSession = Depends(get_session)
    ) -> list[dict]:
        query = select(model)
        if key is not None:
            query = query.where(getattr(model, key_field) == key)
        query = query.order_by(getattr(model, key_field), model.start_date.desc())
        return [_row(o, list_fields) for o in (await session.execute(query)).scalars().all()]

    @router.get("/current")
    async def current_version(key: str, session: AsyncSession = Depends(get_session)) -> dict:
        obj = await scd2.current_version(session, model, key_field, key)
        if obj is None:
            raise HTTPException(status_code=404, detail="нет текущей версии")
        return _row(obj, list_fields)

    @router.get("/as-of")
    async def version_as_of(
        key: str, on: date, session: AsyncSession = Depends(get_session)
    ) -> dict:
        obj = await scd2.version_as_of(session, model, key_field, key, on)
        if obj is None:
            raise HTTPException(status_code=404, detail="нет версии на эту дату")
        return _row(obj, list_fields)

    @router.post("/versions")
    async def add_version(
        request: Request,
        payload: dict = Body(...),
        session: AsyncSession = Depends(get_session),
        user: CurrentUser = Depends(require_permission(SYSTEM_WRITE)),
    ) -> dict:
        key = payload.get(key_field)
        start = payload.get("start_date")
        if key is None or start is None:
            raise HTTPException(status_code=422, detail=f"нужны поля: {key_field}, start_date")
        if isinstance(start, str):
            start = date.fromisoformat(start)
        # чувствительный ref (ставка НДС/пошлина) → на согласование, не пишем сразу
        moderated = await _moderate_version(request, session, model, key, payload, user.username)
        if moderated is not None:
            return moderated
        values = {f: payload[f] for f in value_fields if f in payload}
        try:
            obj = await scd2.add_version(session, model, key_field, key, start, **values)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await session.commit()
        await session.refresh(obj)
        return _row(obj, list_fields)

    return router


def build_reference_router() -> APIRouter:
    """Собрать системный CRUD-роутер справочников ядра под ``/system/refs/*`` (см. каталог)."""
    router = APIRouter(prefix="/system/refs", tags=["references"])
    simple = (
        ("/units", Unit, ("code", "title", "is_active"), ("code", "title")),
        ("/currencies", Currency, ("code", "title", "is_active"), ("code", "title")),
        ("/countries", Country, ("code", "title", "is_active"), ("code", "title")),
        ("/banks", Bank, ("code", "title", "swift", "is_active"), ("code", "title")),
    )
    for prefix, model, fields, required in simple:
        router.include_router(
            build_simple_ref_router(model, fields=fields, editable=fields, required=required),
            prefix=prefix,
        )
    router.include_router(
        build_versioned_ref_router(
            CurrencyRate,
            key_field="currency_code",
            value_fields=("rate",),
            list_fields=("id", "currency_code", "rate", "start_date", "end_date"),
        ),
        prefix="/currency-rates",
    )
    router.include_router(
        build_versioned_ref_router(
            VatRate,
            key_field="code",
            value_fields=("title", "rate"),
            list_fields=("id", "code", "title", "rate", "start_date", "end_date"),
        ),
        prefix="/vat-rates",
    )
    # Группы номенклатуры — иерархия (parent_id); дерево собирает фронт из плоского списка.
    router.include_router(
        build_simple_ref_router(
            NomenclatureCategory,
            fields=("id", "code", "name", "parent_id", "tnved_code",
                    "vat_code", "unit", "country", "attributes", "is_active"),
            editable=("code", "name", "parent_id", "tnved_code", "vat_code",
                      "unit", "country", "attributes"),
            required=("code", "name"),
        ),
        prefix="/nomenclature-groups",
    )
    # План счетов (РБ) и гео-регионы — иерархические справочники (parent_id), как группы.
    router.include_router(
        build_simple_ref_router(
            Account,
            fields=("id", "code", "title", "kind", "parent_id",
                    "effective_from", "effective_to", "is_active"),
            editable=("code", "title", "kind", "parent_id", "effective_from", "effective_to"),
            required=("code", "title"),
        ),
        prefix="/accounts",
    )
    router.include_router(
        build_simple_ref_router(
            Region,
            fields=("id", "code", "title", "kind", "parent_id",
                    "effective_from", "effective_to", "is_active"),
            editable=("code", "title", "kind", "parent_id", "effective_from", "effective_to"),
            required=("code", "title"),
        ),
        prefix="/regions",
    )
    # ТН ВЭД ЕАЭС — версионный (SCD2): ставки меняются решениями ЕЭК, расчёт берёт ставку на дату.
    router.include_router(
        build_versioned_ref_router(
            TnvedCode,
            key_field="code",
            value_fields=("name", "duty_rate", "vat_code", "excise", "unit"),
            list_fields=(
                "id", "code", "name", "duty_rate", "vat_code", "excise", "unit",
                "start_date", "end_date",
            ),
        ),
        prefix="/tnved",
    )
    # История мастер-характеристик SKU — версионная (SCD2): датированные снимки полей товара.
    # Запись версий — через core.services.sku_history.record_sku_version (из точки правки SKU);
    # этот роутер даёт чтение (список/current/as-of) + ручное добавление версии.
    router.include_router(
        build_versioned_ref_router(
            SkuVersion,
            key_field="sku_code",
            value_fields=(
                "title", "unit", "category_id", "weight_kg", "volume_m3",
                "tnved_code", "vat_code", "shelf_life_days", "attributes",
            ),
            list_fields=(
                "id", "sku_code", "title", "unit", "category_id", "weight_kg", "volume_m3",
                "tnved_code", "vat_code", "shelf_life_days", "attributes", "start_date", "end_date",
            ),
        ),
        prefix="/sku-history",
    )
    return router
