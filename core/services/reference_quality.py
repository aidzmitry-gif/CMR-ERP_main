"""Data-Quality движок справочников — аудит качества БЕЗ записи (только SELECT).

Считает по каждому справочнику три класса проблем и сводный ``score`` (1.0 = чисто):
- **missing** — пустые обязательные/«горячие» поля (Sku без unit/category_id/tnved_code,
  группа без tnved_code/vat_code, контрагент без УНП);
- **duplicate** — для контрагентов ЧИТАЕМ счётчик кластеров MDM (``mdm.duplicate_clusters`` —
  логику дедупа не дублируем, merge — зона Синк); для простых справочников — одинаковый
  нормализованный ``title`` при разных ``code``;
- **broken_ref** — мягкие ссылки, не находящие цель (Sku.tnved_code/category_id, поля группы
  vat/tnved/unit/country) и ``parent_id``-сироты (ссылка на несуществующий/архивный родитель).

Чистый сервис: транзакцию не меняем, в ``modules/integrations`` не ходим (контрагентов лишь
читаем через ядро как метрику качества). Структура ответа на ref:
``{ref, title, total, issues:[{kind, field, count, sample_keys}], score}``.

# ponytail: проверки грузят ключи/значения в Python и сравнивают множествами (O(n) на ref) —
# ок на dev/малых объёмах; на проде с млн строк переписать на SQL ``NOT EXISTS``/``LEFT JOIN``
# + материализованную вьюху, и пересчитывать по расписанию, а не на каждый запрос.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.models import Counterparty, Sku
from core.domain.reference import (
    Account,
    Bank,
    Country,
    Currency,
    NomenclatureCategory,
    Region,
    TnvedCode,
    Unit,
    VatRate,
)
from core.services import mdm, tnved

#: вес класса проблемы в сводном score (доля «веса проблем» к числу строк). # ponytail:
#: веса-эвристика; дубли мягче пропусков/битых ссылок. Калибровать, когда появится эталон качества.
WEIGHTS: dict[str, float] = {
    "missing": 1.0,
    "broken_ref": 1.0,
    "orphan": 1.0,
    "duplicate": 0.5,
    # «слепой по марже» SKU — нельзя посчитать landed cost (ось A, деньги). # ponytail: частично
    # пересекается с missing/tnved_code (то проверяет ТОЛЬКО своё поле; margin_blind — эффективный
    # код own ∨ group); двойной учёт допускаем (score clamp в [0,1]), это разные линзы.
    "margin_blind": 1.0,
}
#: сколько ключей-примеров отдавать на проблему (для дрилдауна в UI).
SAMPLE = 5

#: подписи справочников для сводки (совпадают с реестром; дублируем малую часть, чтобы
#: движок не зависел от Core при unit-тесте). # ponytail: при росте — читать title из реестра.
_TITLES: dict[str, str] = {
    "core.skus": "Номенклатура",
    "core.nomenclature_groups": "Группы номенклатуры",
    "core.counterparties": "Контрагенты",
    "core.units": "Единицы измерения",
    "core.currencies": "Валюты",
    "core.countries": "Страны",
    "core.banks": "Банки",
    "core.accounts": "План счетов",
    "core.regions": "Регионы и города",
}


def _norm_title(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _issue(kind: str, field: str, keys: list) -> dict:
    """Сборка записи проблемы; ключи приводим к строке и обрезаем до SAMPLE."""
    return {
        "kind": kind,
        "field": field,
        "count": len(keys),
        "sample_keys": [str(k) for k in keys[:SAMPLE]],
    }


def _score(total: int, issues: list[dict]) -> float:
    """``1 − взвешенная доля проблемных`` (clamp в [0,1]); пустой/чистый справочник → 1.0."""
    if total <= 0:
        return 1.0
    weighted = sum(WEIGHTS.get(i["kind"], 1.0) * i["count"] for i in issues)
    return round(max(0.0, 1.0 - weighted / total), 3)


async def _all(session: AsyncSession, model):
    return (await session.execute(select(model))).scalars().all()


async def _keyset(session: AsyncSession, model, attr: str, *, active_only: bool = False) -> set:
    """Множество значений ``attr`` справочника (для проверки мягких ссылок). None отбрасываем."""
    stmt = select(getattr(model, attr))
    if active_only and hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))
    return {v for (v,) in (await session.execute(stmt)).all() if v is not None}


def _missing(rows, key_attr: str, fields: tuple[str, ...]) -> list[dict]:
    """Проблемы-пропуски: для каждого поля — строки с None/пустым значением."""
    out: list[dict] = []
    for field in fields:
        bad = [getattr(r, key_attr) for r in rows if not getattr(r, field)]
        if bad:
            out.append(_issue("missing", field, bad))
    return out


def _broken(rows, key_attr: str, field: str, valid: set, kind: str = "broken_ref") -> dict | None:
    """Проблема битой мягкой ссылки: значение поля задано, но не найдено в ``valid``."""
    bad = [getattr(r, key_attr) for r in rows if getattr(r, field) and getattr(r, field) not in valid]
    return _issue(kind, field, bad) if bad else None


def _dup_by_title(rows) -> dict | None:
    """Дубли простого справочника: одинаковый нормализованный title при разных code."""
    by_title: dict[str, set] = {}
    for r in rows:
        by_title.setdefault(_norm_title(r.title), set()).add(r.code)
    dup_codes = [c for codes in by_title.values() if len(codes) > 1 for c in sorted(codes)]
    return _issue("duplicate", "title", dup_codes) if dup_codes else None


def _result(ref: str, total: int, issues: list[dict]) -> dict:
    issues = [i for i in issues if i]  # отбросить None от опциональных проверок
    return {
        "ref": ref,
        "title": _TITLES.get(ref, ref),
        "total": total,
        "issues": issues,
        "score": _score(total, issues),
    }


# ── Аудиторы по справочникам ─────────────────────────────────────────────────


async def _margin_blind(session: AsyncSession, rows) -> dict | None:
    """SKU, по которым НЕЛЬЗЯ посчитать landed cost (ось маржи): нет эфф. ТН ВЭД (ни своего, ни
    от группы) ИЛИ есть ТН ВЭД (импортный), но нет ни веса, ни объёма (фрахт не на что разнести).

    Переиспользует ``tnved.effective_code_for_sku`` (own ∨ group). # ponytail: эффективный код
    резолвится по каждому SKU отдельным обходом дерева групп (O(n·глубина)) — как и весь движок
    (см. шапку модуля); на проде вынести в SQL ``LEFT JOIN``/материализованную вьюху.
    """
    blind: list = []
    for sku in rows:
        eff = await tnved.effective_code_for_sku(session, sku)
        if not eff.get("code"):
            blind.append(sku.code)  # нет ставки пошлины (ни своей, ни от группы) → себес не посчитать
        elif not sku.weight_kg and not sku.volume_m3:
            # импортный (есть ТН ВЭД), но фрахт не разнести: ни веса, ни объёма. 0.0 = та же дыра,
            # что и None (нулевой вес физического товара не валиден) — не маскируем нулём.
            blind.append(sku.code)
    return _issue("margin_blind", "landed_cost", blind) if blind else None


async def _audit_skus(session: AsyncSession) -> dict:
    rows = await _all(session, Sku)
    tnved_codes = await _keyset(session, TnvedCode, "code")
    cat_ids = await _keyset(session, NomenclatureCategory, "id")
    issues = _missing(rows, "code", ("unit", "category_id", "tnved_code"))
    issues.append(_broken(rows, "code", "tnved_code", tnved_codes))
    issues.append(_broken(rows, "code", "category_id", cat_ids))
    issues.append(await _margin_blind(session, rows))  # ось A: «слепые по марже» SKU
    return _result("core.skus", len(rows), issues)


async def _audit_categories(session: AsyncSession) -> dict:
    rows = await _all(session, NomenclatureCategory)
    vat_codes = await _keyset(session, VatRate, "code")
    tnved_codes = await _keyset(session, TnvedCode, "code")
    unit_codes = await _keyset(session, Unit, "code")
    country_codes = await _keyset(session, Country, "code")
    active_ids = {r.id for r in rows if r.is_active}
    issues = _missing(rows, "code", ("tnved_code", "vat_code"))
    issues.append(_broken(rows, "code", "vat_code", vat_codes))
    issues.append(_broken(rows, "code", "tnved_code", tnved_codes))
    issues.append(_broken(rows, "code", "unit", unit_codes))
    issues.append(_broken(rows, "code", "country", country_codes))
    # сироты: parent_id ссылается на несуществующую/архивную группу
    orphans = [r.code for r in rows if r.parent_id is not None and r.parent_id not in active_ids]
    if orphans:
        issues.append(_issue("orphan", "parent_id", orphans))
    return _result("core.nomenclature_groups", len(rows), issues)


async def _audit_counterparties(session: AsyncSession) -> dict:
    # только эталоны (активные, не слитые) — дубли-архивы не считаем «пропуском».
    rows = [
        r for r in await _all(session, Counterparty)
        if r.is_active and r.merged_into_id is None
    ]
    # ponytail: модель Counterparty без поля региона → проверяем только УНП; добавить регион,
    # когда появится колонка (сейчас регион живёт в адресных полях, которых в ядре нет).
    issues = _missing(rows, "id", ("unp",))
    # дубли — читаем счётчик кластеров MDM (merge — зона Синк, логику не дублируем)
    clusters = await mdm.duplicate_clusters(session)
    if clusters:
        issues.append(_issue("duplicate", "unp", [c["unp"] for c in clusters]))
    return _result("core.counterparties", len(rows), issues)


async def _audit_simple(session: AsyncSession, ref: str, model) -> dict:
    rows = await _all(session, model)
    return _result(ref, len(rows), [_dup_by_title(rows)])


async def _audit_hierarchical(session: AsyncSession, ref: str, model) -> dict:
    rows = await _all(session, model)
    active_ids = {r.id for r in rows if r.is_active}
    orphans = [r.code for r in rows if r.parent_id is not None and r.parent_id not in active_ids]
    issues = [_dup_by_title(rows)]
    if orphans:
        issues.append(_issue("orphan", "parent_id", orphans))
    return _result(ref, len(rows), issues)


#: ref_key → (вид аудита, аргументы). Известные простые/иерархические справочники.
_SIMPLE = {"core.units": Unit, "core.currencies": Currency, "core.countries": Country,
           "core.banks": Bank}
_HIER = {"core.accounts": Account, "core.regions": Region}


async def audit_reference(session: AsyncSession, ref: str) -> dict | None:
    """Аудит одного справочника по ключу реестра; ``None`` — для ref без определённых проверок."""
    if ref == "core.skus":
        return await _audit_skus(session)
    if ref == "core.nomenclature_groups":
        return await _audit_categories(session)
    if ref == "core.counterparties":
        return await _audit_counterparties(session)
    if ref in _SIMPLE:
        return await _audit_simple(session, ref, _SIMPLE[ref])
    if ref in _HIER:
        return await _audit_hierarchical(session, ref, _HIER[ref])
    return None


#: справочники с определёнными проверками качества (порядок сводки = по ценности).
AUDITED_REFS: tuple[str, ...] = (
    "core.skus", "core.nomenclature_groups", "core.counterparties",
    "core.units", "core.currencies", "core.countries", "core.banks",
    "core.accounts", "core.regions",
)


async def audit_all(session: AsyncSession) -> list[dict]:
    """Сводка качества по всем покрытым справочникам (без sample_keys — это в детализации)."""
    out: list[dict] = []
    for ref in AUDITED_REFS:
        res = await audit_reference(session, ref)
        if res is not None:
            out.append(res)
    return out
