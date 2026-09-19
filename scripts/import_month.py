"""Импорт реальных данных за месяц из Bitrix24 и 1С в ERP (для сквозной проверки).

Период задаётся env (по умолчанию ноябрь 2024):
  IMPORT_FROM=2025-12-01T00:00:00 IMPORT_TO=2026-01-01T00:00:00

Двухфазный ETL с файловым кэшем в data/import_<YYYY-MM>/ (повторный прогон безопасен):
  python scripts/import_month.py extract      # Bitrix REST + 1C OData -> jsonl-кэш
  python scripts/import_month.py extract-onec # только 1С (без Bitrix) — товары/цены
  python scripts/import_month.py load-onec    # Sku + StockItem.price из кэша 1С
  python scripts/import_month.py load-prices  # цены SKU из строк реализаций (кэш)
  python scripts/import_month.py verify       # счётчики по таблицам
  python scripts/import_month.py reconcile    # агрегированная сверка кэша и БД
  python scripts/import_month.py all

Load-only требует явных переменных ``IMPORT_CACHE_DIR`` (абсолютный путь к кэшу),
``AIOS_ENVIRONMENT=dev`` и ``AIOS_DATABASE_URL`` с абсолютным файлом
``sqlite+aiosqlite:///...``. При ``IMPORT_RECONCILE_REPORT`` сверка сохраняется
как агрегированный JSON без исходных значений.
При ``IMPORT_RECONCILE_DETAIL_REPORT`` дополнительно сохраняется приватный
JSON с деталями расхождений; путь должен быть абсолютным.

Идемпотентность load: контрагент — CounterpartyAlias(source, external_ref) + склейка по УНП;
сделка — Deal.number = "BX-<id>"; звонок — CallLog.call_id; лид — служебный marker в message;
платёж (реализация 1С) — Payment.entity_ref = "1c:sale:<Ref_Key>"; SKU — по коду 1С;
цены подбора — StockItem из строк реализаций (последняя Цена за месяц, склад «Главный»).

1С — СТРОГО чтение. $filter по датам/строкам в этой базе запрещён (файловая ИБ),
поэтому ноябрь берём «окном»: бинарный поиск левой границы по $skip при $orderby=Date.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FROM_ISO = os.getenv("IMPORT_FROM", "2024-11-01T00:00:00")
TO_ISO = os.getenv("IMPORT_TO", "2024-12-01T00:00:00")
LABEL = FROM_ISO[:7]  # "2024-11" — метка месяца для кэша и провенанса
OUT_DIR = PROJECT_ROOT / "data" / f"import_{LABEL}"
# Окно 1С по умолчанию = общему окну; переопределяемо (в ka_copy нет данных до 10.2025 —
# ноябрь-2024 лежит в другой базе «КА свернутая», ждёт публикации её OData).
ONEC_FROM = os.getenv("IMPORT_ONEC_FROM", FROM_ISO)
ONEC_TO = os.getenv("IMPORT_ONEC_TO", TO_ISO)
# Переопределение URL базы 1С (например, ka_copy_3 после публикации), не трогая connectors/.env.
# Конфигурация коннектора импортируется лениво, только в extraction-пути: load-only не
# читает connectors/.env и не поднимает значения секретов.
ONEC_BASE = os.getenv("IMPORT_ONEC_BASE", "")


def _connector_config():
    """Загрузить конфигурацию внешних коннекторов только для extraction."""
    from connectors import config

    return config


def _onec_base_url() -> str:
    return os.getenv("IMPORT_ONEC_BASE", "").strip() or _connector_config().ONEC_BASE_URL

# ---------------------------------------------------------------- Bitrix REST

_last_call = 0.0


def bx(method: str, params: dict | None = None) -> dict:
    """Вызов метода Bitrix REST с троттлингом и ретраями на лимиты/5xx."""
    cfg = _connector_config()
    global _last_call
    for attempt in range(6):
        delta = time.monotonic() - _last_call
        if delta < 0.4:
            time.sleep(0.4 - delta)
        _last_call = time.monotonic()
        resp = requests.post(cfg.BITRIX_WEBHOOK.rstrip("/") + "/" + method,
                             json=params or {}, timeout=90)
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        data = resp.json()
        if data.get("error") in ("QUERY_LIMIT_EXCEEDED", "OVERLOAD_LIMIT"):
            time.sleep(2 ** attempt)
            continue
        if "error" in data:
            raise RuntimeError(f"Bitrix {method}: {data['error']} {data.get('error_description')}")
        return data
    raise RuntimeError(f"Bitrix {method}: исчерпаны ретраи")


def bx_list(method: str, params: dict) -> list[dict]:
    """Полный постраничный обход списочного метода."""
    rows: list[dict] = []
    start = 0
    while True:
        data = bx(method, {**params, "start": start})
        rows.extend(data.get("result") or [])
        if data.get("next") is None:
            return rows
        start = data["next"]


# ---------------------------------------------------------------- 1C OData

_onec = requests.Session()


def onec_get(path: str, params: dict | None = None) -> dict:
    cfg = _connector_config()
    if not _onec.auth:
        _onec.auth = (cfg.ONEC_USER, cfg.ONEC_PASSWORD)
        _onec.headers["Accept"] = "application/json"
    url = _onec_base_url().rstrip("/") + "/" + path
    for attempt in range(4):
        resp = _onec.get(url, params={"$format": "json", **(params or {})}, timeout=180)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"1C {path}: исчерпаны ретраи")


def onec_date_at(entity: str, skip: int) -> str | None:
    """Date документа на позиции skip при сортировке по Date (для бинарного поиска)."""
    rows = onec_get(entity, {"$orderby": "Date", "$top": 1, "$skip": skip,
                             "$select": "Date"}).get("value", [])
    return rows[0]["Date"] if rows else None


def onec_window(entity: str, date_from: str, date_to: str) -> list[dict]:
    """Все документы entity с date_from <= Date < date_to ($filter недоступен — окно по $skip)."""
    # верхняя граница числа документов — удвоение skip до пустой страницы
    hi = 1
    while onec_date_at(entity, hi) is not None:
        hi *= 2
    # левая граница окна: первый индекс с Date >= date_from
    lo, r = 0, hi
    while lo < r:
        mid = (lo + r) // 2
        d = onec_date_at(entity, mid)
        if d is None or d >= date_from:
            r = mid
        else:
            lo = mid + 1
    # постраничный проход до выхода за date_to (документы целиком, с табличными частями)
    docs: list[dict] = []
    skip = lo
    while True:
        rows = onec_get(entity, {"$orderby": "Date", "$top": 200, "$skip": skip}).get("value", [])
        if not rows:
            break
        for row in rows:
            if row.get("Date", "") >= date_to:
                return docs
            docs.append(row)
        skip += len(rows)
    return docs


def onec_by_key(catalog: str, ref_key: str, select: str) -> dict | None:
    try:
        return onec_get(f"{catalog}(guid'{ref_key}')", {"$select": select})
    except Exception:
        return None


# ---------------------------------------------------------------- extract


def _resolve_cache_dir(*, require_override: bool = False) -> Path:
    raw = os.getenv("IMPORT_CACHE_DIR", "").strip()
    if not raw:
        if require_override:
            raise RuntimeError(
                "load-only требует IMPORT_CACHE_DIR с существующим локальным кэшем"
            )
        return PROJECT_ROOT / "data" / f"import_{LABEL}"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError("IMPORT_CACHE_DIR должен быть абсолютным путём")
    path = path.resolve()
    if not path.is_dir():
        raise RuntimeError(f"IMPORT_CACHE_DIR не найден: {path}")
    return path


def _load_cache_dir() -> Path:
    """Переключить источник кэша для load/reconcile и вернуть его путь."""
    global OUT_DIR
    OUT_DIR = _resolve_cache_dir(require_override=True)
    return OUT_DIR


def _resolve_report_path(env_name: str) -> Path | None:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{env_name} должен быть абсолютным путём")
    return path


def _isolated_database_path() -> Path:
    db_url = os.getenv("AIOS_DATABASE_URL", "").strip()
    prefix = "sqlite+aiosqlite:///"
    if not db_url.startswith(prefix):
        raise RuntimeError(
            "load-only требует явный AIOS_DATABASE_URL вида sqlite+aiosqlite:///ABSOLUTE_PATH"
        )
    db_path = db_url[len(prefix):].split("?", 1)[0]
    if not db_path or db_path == ":memory:" or not Path(db_path).expanduser().is_absolute():
        raise RuntimeError("load-only требует абсолютный файловый путь SQLite")
    return Path(db_path).expanduser().resolve()


def _require_isolated_load() -> Path:
    """Fail-closed guard для операций, которые пишут только из локального кэша."""
    cache_dir = _load_cache_dir()
    if os.getenv("AIOS_ENVIRONMENT", "").strip().lower() != "dev":
        raise RuntimeError("load-only разрешён только при AIOS_ENVIRONMENT=dev")
    _isolated_database_path()
    return cache_dir


def _same_existing_path(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError:
        return False


def _guard_report_paths(
    cache_dir: Path,
    db_path: Path,
    aggregate_path: Path | None,
    detail_path: Path | None,
) -> None:
    report_paths = [
        ("IMPORT_RECONCILE_REPORT", aggregate_path),
        ("IMPORT_RECONCILE_DETAIL_REPORT", detail_path),
    ]
    report_paths = [(name, path.resolve()) for name, path in report_paths if path is not None]
    if not report_paths:
        return

    cache_root = cache_dir.resolve()
    cache_entries = [cache_root, *cache_root.rglob("*")]
    sqlite_targets = [
        db_path.resolve(),
        *[Path(f"{db_path}{suffix}").resolve() for suffix in ("-wal", "-shm", "-journal")],
    ]
    for name, path in report_paths:
        try:
            path.relative_to(cache_root)
        except ValueError:
            pass
        else:
            raise RuntimeError(f"{name} не должен указывать в IMPORT_CACHE_DIR")
        if any(path == target or _same_existing_path(path, target) for target in cache_entries):
            raise RuntimeError(f"{name} не должен совпадать с файлом кэша")
        if any(path == target or _same_existing_path(path, target) for target in sqlite_targets):
            raise RuntimeError(f"{name} не должен совпадать с SQLite DB или sidecar")

    if len(report_paths) == 2:
        first_name, first_path = report_paths[0]
        second_name, second_path = report_paths[1]
        if first_path == second_path or _same_existing_path(first_path, second_path):
            raise RuntimeError(f"{first_name} и {second_name} должны быть разными файлами")


def _isolated_database():
    """Создать Database без Settings: не читать корневой .env и не тянуть секреты."""
    from types import SimpleNamespace

    from core.services.db import Database

    db = Database(SimpleNamespace(database_url=os.environ["AIOS_DATABASE_URL"]))
    db.init_engine()
    return db

def _dump(name: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"extract: {name} — {len(rows)} записей")


def _load_jsonl(name: str) -> list[dict]:
    path = OUT_DIR / f"{name}.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _nonempty_ids(rows: list[dict], field: str) -> set[str]:
    return {
        str(row[field])
        for row in rows
        if row.get(field) not in (None, "", "0")
    }


def _semantic_value(value):
    """Нормализовать значения для digest без вывода самих исходных данных."""
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _semantic_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_semantic_value(item) for item in value]
    return value


def _semantic_digest(rows: list[dict]) -> str:
    canonical = [_semantic_value(row) for row in rows]
    canonical.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_identity_digest(rows: list[dict]) -> str:
    """Дайджест только импортированных identity, отдельно от значений полей."""
    return _semantic_digest([{"identity": row.get("identity")} for row in rows])


def _semantic_summary(rows: list[dict]) -> dict:
    return {
        "rows": len(rows),
        "digest": _semantic_digest(rows),
        "identity_digest": _semantic_identity_digest(rows),
    }


def _semantic_classification(
    name: str,
    expected_rows: list[dict],
    actual_rows: list[dict],
    alias_audit: dict,
    detail_rows: list[dict] | None = None,
    source_identity_ids: dict[str, str] | None = None,
) -> dict:
    """Сверить identity и поля; любое отличие требует ручной проверки."""
    expected_by_id = {str(row.get("identity")): row for row in expected_rows}
    actual_by_id = {str(row.get("identity")): row for row in actual_rows}
    expected_ids = set(expected_by_id)
    actual_ids = set(actual_by_id)
    missing = expected_ids - actual_ids
    extra = actual_ids - expected_ids
    duplicate_source = len(expected_rows) - len(expected_ids)
    duplicate_destination = len(actual_rows) - len(actual_ids)

    changed_rows: set[str] = set()
    review_counts: dict[str, int] = {}
    source_identity_ids = source_identity_ids or {}
    if detail_rows is not None:
        for identity in sorted(missing):
            detail_rows.append({
                "kind": "missing_identity",
                "dataset": name,
                "source_id": source_identity_ids.get(identity, identity),
                "identity": identity,
            })
        for identity in sorted(extra):
            detail_rows.append({
                "kind": "extra_identity",
                "dataset": name,
                "destination_identity": identity,
                "identity": identity,
            })

    for identity in sorted(expected_ids & actual_ids):
        expected = expected_by_id[identity]
        actual = actual_by_id[identity]
        field_diffs: dict[str, dict[str, object]] = {}
        for field in sorted(set(expected) | set(actual)):
            if field == "identity":
                continue
            if _semantic_value(expected.get(field)) == _semantic_value(actual.get(field)):
                continue
            changed_rows.add(identity)
            # Префикс keeps the aggregate report free of PII-shaped keys while
            # retaining which semantic field requires review.
            review_field = f"changed_{field}"
            review_counts[review_field] = review_counts.get(review_field, 0) + 1
            if detail_rows is not None:
                field_diffs[field] = {
                    "source": _semantic_value(expected.get(field)),
                    "destination": _semantic_value(actual.get(field)),
                }
        if detail_rows is not None and field_diffs:
            detail_rows.append({
                "kind": "semantic_difference",
                "dataset": name,
                "source_id": source_identity_ids.get(identity, identity),
                "identity": identity,
                "changed_fields": sorted(field_diffs),
                "source": {field: field_diffs[field]["source"] for field in sorted(field_diffs)},
                "destination": {
                    field: field_diffs[field]["destination"] for field in sorted(field_diffs)
                },
            })

    if detail_rows is not None:
        source_identity_counts = Counter(str(row.get("identity")) for row in expected_rows)
        destination_identity_counts = Counter(str(row.get("identity")) for row in actual_rows)
        if duplicate_source:
            for identity in sorted(expected_ids):
                if source_identity_counts[identity] > 1:
                    detail_rows.append({
                        "kind": "duplicate_source_identity",
                        "dataset": name,
                        "source_id": source_identity_ids.get(identity, identity),
                        "identity": identity,
                    })
        if duplicate_destination:
            for identity in sorted(actual_ids):
                if destination_identity_counts[identity] > 1:
                    detail_rows.append({
                        "kind": "duplicate_destination_identity",
                        "dataset": name,
                        "destination_identity": identity,
                        "identity": identity,
                    })

    if missing and extra:
        status = "missing_and_extra_identity"
    elif missing:
        status = "missing_identity"
    elif extra:
        status = "extra_identity"
    elif review_counts:
        status = "requires_review"
    else:
        status = "exact"

    return {
        "status": status,
        "allowed_changes": {"rows": 0, "kinds": {}},
        "conflicts": {
            "rows": sum(review_counts.values()),
            "fields": dict(sorted(review_counts.items())),
        },
        "requires_review": {
            "rows": sum(review_counts.values()),
            "fields": dict(sorted(review_counts.items())),
        },
        "missing_identity_rows": len(missing),
        "extra_identity_rows": len(extra),
        "duplicate_source_identities": duplicate_source,
        "duplicate_destination_identities": duplicate_destination,
        "alias_audit_conflict_refs": alias_audit.get("conflict_refs", 0),
    }


def _opaque_identity(*parts: object) -> str:
    """Стабильная ссылка для digest: не раскрывает имя/телефон в отчёте."""
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_stock_semantic_rows(sku_rows: list[dict], sales_rows: list[dict]) -> list[dict]:
    """Построить ожидаемые строки цены тем же правилом, что и load-прослойка."""
    sku_by_ref = {
        str(row["Ref_Key"]): (row.get("Code") or "").strip()
        for row in sku_rows
        if row.get("Ref_Key") and (row.get("Code") or "").strip()
    }
    latest: dict[str, tuple[datetime | None, Decimal]] = {}
    for doc in sales_rows:
        if doc.get("Posted") is False:
            continue
        doc_date = _naive(doc.get("Date"))
        for line in doc.get("Товары") or []:
            code = sku_by_ref.get(str(line.get("Номенклатура_Key") or ""))
            if not code:
                continue
            price = _dec(line.get("ЦенаСоСкидкой") or line.get("Цена"))
            if price <= 0:
                continue
            prev = latest.get(code)
            if prev is None or (
                doc_date is not None and (prev[0] is None or doc_date >= prev[0])
            ):
                latest[code] = (doc_date, price)
    return [
        {"identity": f"{code}|Главный", "sku_code": code, "warehouse": "Главный", "price": price}
        for code, (_, price) in sorted(latest.items())
    ]


def _source_reconciliation(
    *, include_semantic_rows: bool = False, detail_rows: list[dict] | None = None
) -> dict:
    """Собрать безопасную агрегированную сверку кэша без вывода исходных значений."""
    files = {path.stem: _load_jsonl(path.stem) for path in sorted(OUT_DIR.glob("*.jsonl"))}
    users = files.get("bx_users", [])
    companies = files.get("bx_companies", [])
    contacts = files.get("bx_contacts", [])
    deals = files.get("bx_deals", [])
    leads = files.get("bx_leads", [])
    calls = files.get("bx_calls", [])
    requisites = files.get("bx_requisites", [])
    onec_counterparties = files.get("onec_counterparties", [])
    onec_sales = files.get("onec_sales", [])
    onec_sku = files.get("onec_sku", [])

    user_ids = _nonempty_ids(users, "ID")
    company_ids = _nonempty_ids(companies, "ID")
    contact_ids = _nonempty_ids(contacts, "ID")
    deal_company_ids = _nonempty_ids(deals, "COMPANY_ID")
    deal_contact_ids = _nonempty_ids(deals, "CONTACT_ID")
    deal_owner_ids = _nonempty_ids(deals, "ASSIGNED_BY_ID")
    lead_owner_ids = _nonempty_ids(leads, "ASSIGNED_BY_ID")
    call_company_ids = {
        str(row["CRM_ENTITY_ID"])
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "COMPANY"
        and row.get("CRM_ENTITY_ID") not in (None, "", "0")
    }
    call_contact_ids = {
        str(row["CRM_ENTITY_ID"])
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "CONTACT"
        and row.get("CRM_ENTITY_ID") not in (None, "", "0")
    }
    call_owner_ids = _nonempty_ids(calls, "PORTAL_USER_ID")
    requisite_company_ids = _nonempty_ids(requisites, "ENTITY_ID")

    def link_stats(refs: set[str], targets: set[str]) -> dict:
        return {
            "distinct_references": len(refs),
            "distinct_missing": len(refs - targets),
            "rows_missing": 0,
        }

    links = {
        "deals_to_companies": link_stats(deal_company_ids, company_ids),
        "deals_to_contacts": link_stats(deal_contact_ids, contact_ids),
        "deals_to_users": link_stats(deal_owner_ids, user_ids),
        "calls_to_companies": link_stats(call_company_ids, company_ids),
        "calls_to_contacts": link_stats(call_contact_ids, contact_ids),
        "calls_to_users": link_stats(call_owner_ids, user_ids),
        "leads_to_users": link_stats(lead_owner_ids, user_ids),
        "requisites_to_companies": link_stats(requisite_company_ids, company_ids),
    }
    # Keep row-level misses separate from distinct-id misses. Both are useful when a
    # source repeats one broken reference many times, while neither exposes the id.
    links["deals_to_companies"]["rows_missing"] = sum(
        str(row.get("COMPANY_ID")) not in company_ids
        for row in deals
        if row.get("COMPANY_ID") not in (None, "", "0")
    )
    links["deals_to_contacts"]["rows_missing"] = sum(
        str(row.get("CONTACT_ID")) not in contact_ids
        for row in deals
        if row.get("CONTACT_ID") not in (None, "", "0")
    )
    links["deals_to_users"]["rows_missing"] = sum(
        str(row.get("ASSIGNED_BY_ID")) not in user_ids
        for row in deals
        if row.get("ASSIGNED_BY_ID") not in (None, "", "0")
    )
    links["calls_to_companies"]["rows_missing"] = sum(
        str(row.get("CRM_ENTITY_ID")) not in company_ids
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "COMPANY"
        and row.get("CRM_ENTITY_ID") not in (None, "", "0")
    )
    links["calls_to_contacts"]["rows_missing"] = sum(
        str(row.get("CRM_ENTITY_ID")) not in contact_ids
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "CONTACT"
        and row.get("CRM_ENTITY_ID") not in (None, "", "0")
    )
    links["calls_to_users"]["rows_missing"] = sum(
        str(row.get("PORTAL_USER_ID")) not in user_ids
        for row in calls
        if row.get("PORTAL_USER_ID") not in (None, "", "0")
    )
    links["leads_to_users"]["rows_missing"] = sum(
        str(row.get("ASSIGNED_BY_ID")) not in user_ids
        for row in leads
        if row.get("ASSIGNED_BY_ID") not in (None, "", "0")
    )
    links["requisites_to_companies"]["rows_missing"] = sum(
        str(row.get("ENTITY_ID")) not in company_ids
        for row in requisites
        if row.get("ENTITY_ID") not in (None, "", "0")
    )
    if detail_rows is not None:
        def append_missing_links(
            dataset: str,
            relation: str,
            rows: list[dict],
            source_id_field: str,
            source_field: str,
            target_ids: set[str],
            predicate=None,
        ) -> None:
            for row in rows:
                if predicate is not None and not predicate(row):
                    continue
                reference = row.get(source_field)
                if reference in (None, "", "0") or str(reference) in target_ids:
                    continue
                source_id = str(row.get(source_id_field) or row.get("ID") or "")
                detail_rows.append({
                    "kind": "missing_link",
                    "dataset": dataset,
                    "relation": relation,
                    "source_id": source_id,
                    "source_field": source_field,
                    "source_reference_id": str(reference),
                })

        append_missing_links(
            "bitrix_deals", "deals_to_companies", deals, "ID", "COMPANY_ID", company_ids
        )
        append_missing_links(
            "bitrix_deals", "deals_to_contacts", deals, "ID", "CONTACT_ID", contact_ids
        )
        append_missing_links(
            "bitrix_deals", "deals_to_users", deals, "ID", "ASSIGNED_BY_ID", user_ids
        )
        append_missing_links(
            "bitrix_calls", "calls_to_companies", calls, "CALL_ID", "CRM_ENTITY_ID", company_ids,
            lambda row: row.get("CRM_ENTITY_TYPE") == "COMPANY",
        )
        append_missing_links(
            "bitrix_calls", "calls_to_contacts", calls, "CALL_ID", "CRM_ENTITY_ID", contact_ids,
            lambda row: row.get("CRM_ENTITY_TYPE") == "CONTACT",
        )
        append_missing_links(
            "bitrix_calls", "calls_to_users", calls, "CALL_ID", "PORTAL_USER_ID", user_ids,
        )
        append_missing_links(
            "bitrix_leads", "leads_to_users", leads, "ID", "ASSIGNED_BY_ID", user_ids
        )
        append_missing_links(
            "bitrix_requisites", "requisites_to_companies", requisites,
            "ID", "ENTITY_ID", company_ids,
        )
    categories = {}
    for row in deals:
        category = str(row.get("CATEGORY_ID") or "0")
        categories[category] = categories.get(category, 0) + 1
    supported_deals = [
        row for row in deals if str(row.get("CATEGORY_ID") or "0") in ("0", "7")
    ]
    unmapped_supported = 0
    for row in supported_deals:
        category = str(row.get("CATEGORY_ID") or "0")
        stage = str(row.get("STAGE_ID") or "").split(":", 1)[-1]
        mapped_stage, _, _ = _map_deal_stage(stage, category)
        if category == "7":
            mapped = (
                mapped_stage in ("rp_won", "rp_lost", "rp_invoice")
                and (
                    "WON" in stage
                    or stage == "LOSE"
                    or stage in LOST_TITLES
                    or stage in ("NEW", "PREPARATION", "EXECUTING")
                    or "INVOICE" in stage
                )
            )
        else:
            mapped = stage in STAGE_MAP
        if not mapped:
            unmapped_supported += 1

    item_refs = {
        str(item["Номенклатура_Key"])
        for doc in onec_sales
        for item in (doc.get("Товары") or [])
        if item.get("Номенклатура_Key")
    }
    sku_refs = {
        str(row["Ref_Key"]) for row in onec_sku if row.get("Ref_Key")
    }
    sale_counterparty_refs = {
        str(doc["Контрагент_Key"])
        for doc in onec_sales
        if doc.get("Контрагент_Key")
    }
    counterparty_refs = {
        str(row["Ref_Key"])
        for row in onec_counterparties
        if row.get("Ref_Key")
    }
    if detail_rows is not None:
        missing_item_refs = item_refs - sku_refs
        item_source_pairs: set[tuple[str, str]] = set()
        for doc in onec_sales:
            sale_id = str(doc.get("Ref_Key") or "")
            for item in doc.get("Товары") or []:
                item_ref = str(item.get("Номенклатура_Key") or "")
                if item_ref in missing_item_refs:
                    item_source_pairs.add((sale_id, item_ref))
        for sale_id, item_ref in sorted(item_source_pairs):
            detail_rows.append({
                "kind": "missing_link",
                "dataset": "onec_sales",
                "relation": "onec_sales_to_sku",
                "source_id": sale_id,
                "source_field": "Товары[].Номенклатура_Key",
                "source_reference_id": item_ref,
            })
        missing_counterparty_refs = sale_counterparty_refs - counterparty_refs
        counterparty_source_pairs: set[tuple[str, str]] = set()
        for doc in onec_sales:
            sale_id = str(doc.get("Ref_Key") or "")
            counterparty_ref = str(doc.get("Контрагент_Key") or "")
            if counterparty_ref in missing_counterparty_refs:
                counterparty_source_pairs.add((sale_id, counterparty_ref))
        for sale_id, counterparty_ref in sorted(counterparty_source_pairs):
            detail_rows.append({
                "kind": "missing_link",
                "dataset": "onec_sales",
                "relation": "onec_sales_to_counterparty",
                "source_id": sale_id,
                "source_field": "Контрагент_Key",
                "source_reference_id": counterparty_ref,
            })
    dedicated_activity_names = {
        "bx_activities",
        "bx_messages",
        "bx_notes",
    }
    dedicated_file_names = {"bx_files"}
    dedicated_history_names = {"bx_history", "bx_stage_history"}
    call_file_ref_rows = sum(
        bool(row.get("CALL_RECORD_URL") or row.get("RECORD_FILE_ID")) for row in calls
    )
    source = {
        "files": len(files),
        "records": {name: len(rows) for name, rows in sorted(files.items())},
        "period": LABEL,
    }
    stages = {
        "distinct_source_stage_ids": len({str(row.get("STAGE_ID") or "") for row in deals}),
        "supported_deal_rows": len(supported_deals),
        "unmapped_supported_stage_rows": unmapped_supported,
        "skipped_category_rows": sum(
            count for category, count in categories.items() if category not in ("0", "7")
        ),
        "category_counts": dict(sorted(categories.items())),
    }
    products = {
        "bitrix_product_rows_available": "bx_product_rows" in files,
        "onec_sku_rows": len(onec_sku),
        "onec_sale_lines": sum(len(doc.get("Товары") or []) for doc in onec_sales),
        "onec_unique_item_refs": len(item_refs),
        "onec_item_refs_missing_sku": len(item_refs - sku_refs),
        "onec_counterparty_refs_missing": len(sale_counterparty_refs - counterparty_refs),
    }
    posted_rows = sum(row.get("Posted") is True for row in onec_sales)
    unposted_rows = sum(row.get("Posted") is False for row in onec_sales)
    financial = {
        "posted_rows": posted_rows,
        "unposted_rows": unposted_rows,
        "bank_payment_evidence_available": False,
        "import_contract": "pending_receivable_requires_reconciliation",
        "reason": "Posted on a realization document is not a bank payment confirmation",
    }
    users_by_id = {
        str(row.get("ID") or ""): f"{row.get('NAME', '')} {row.get('LAST_NAME', '')}".strip()
        for row in users
    }
    companies_by_id = {str(row.get("ID") or ""): row for row in companies}
    contacts_by_id = {str(row.get("ID") or ""): row for row in contacts}
    unp_by_company: dict[str, str] = {}
    for row in requisites:
        company_id = str(row.get("ENTITY_ID") or "")
        unp = (row.get("RQ_INN") or "").strip()
        if company_id and unp and company_id not in unp_by_company:
            unp_by_company[company_id] = unp

    def source_contact_fields(row: dict) -> tuple[str, str | None, str | None]:
        full_name = f"{row.get('NAME') or ''} {row.get('LAST_NAME') or ''}".strip()[:255]
        full_name = full_name or f"Контакт {row.get('ID') or ''}"
        phone = (_first_value(row.get("PHONE")) or "")[:64] or None
        email = _first_value(row.get("EMAIL")) or None
        return full_name, phone, email

    def company_link(company_id: object) -> str | None:
        value = str(company_id or "")
        return f"company:{value}" if value in company_ids else None

    source_identity_ids: dict[str, dict[str, str]] = {}
    source_company_semantic = [
        {
            "identity": f"company:{company_id}",
            "name": (row.get("TITLE") or f"Компания {company_id}").strip()[:255],
            "unp": unp_by_company.get(company_id),
        }
        for company_id, row in sorted(companies_by_id.items())
    ]
    source_identity_ids["bitrix_companies"] = {
        row["identity"]: row["identity"].removeprefix("company:")
        for row in source_company_semantic
    }
    source_contact_semantic = []
    seen_contact_keys: set[tuple[str, str | None, str | None]] = set()
    for row in contacts:
        full_name, phone, email = source_contact_fields(row)
        key = (full_name, phone, email)
        if key in seen_contact_keys:
            continue
        seen_contact_keys.add(key)
        identity = _opaque_identity("contact", full_name, phone, email)
        source_identity_ids.setdefault("bitrix_contacts", {}).setdefault(
            identity, str(row.get("ID") or "")
        )
        source_contact_semantic.append(
            {
                "identity": identity,
                "full_name": full_name,
                "phone": phone,
                "email": email,
                "counterparty_link": company_link(row.get("COMPANY_ID")),
            }
        )

    source_deal_semantic = []
    for row in supported_deals:
        category = str(row.get("CATEGORY_ID") or "0")
        stage, funnel, lost_comment = _map_deal_stage(str(row.get("STAGE_ID") or ""), category)
        company = companies_by_id.get(str(row.get("COMPANY_ID") or ""))
        contact = contacts_by_id.get(str(row.get("CONTACT_ID") or ""))
        if company:
            counterparty = (company.get("TITLE") or "").strip()
        elif contact:
            counterparty = " ".join(
                part for part in (contact.get("NAME"), contact.get("LAST_NAME")) if part
            ).strip()
        else:
            counterparty = "Не указан"
        created = _naive(row.get("DATE_CREATE")) or datetime.fromisoformat(FROM_ISO)
        closed = _naive(row.get("CLOSEDATE"))
        terminal = stage in ("won", "lost", "rp_won", "rp_lost")
        identity = f"BX-{row.get('ID')}"
        source_identity_ids.setdefault("bitrix_deals", {}).setdefault(
            identity, str(row.get("ID") or "")
        )
        source_deal_semantic.append(
            {
                "identity": identity,
                "title": (row.get("TITLE") or f"BX-{row.get('ID')}")[:255],
                "counterparty": counterparty[:255] or "Не указан",
                "amount": _dec(row.get("OPPORTUNITY")),
                "stage": stage,
                "funnel": funnel,
                "owner": users_by_id.get(str(row.get("ASSIGNED_BY_ID") or ""), "")[:128],
                "deal_date": str(created.date()),
                "closed_date": str(closed.date()) if terminal and closed else None,
                "lost_comment": lost_comment,
            }
        )

    source_lead_semantic = []
    for row in leads:
        marker = f"{LEAD_IMPORT_MARKER}{row.get('ID')}"
        source_identity_ids.setdefault("bitrix_leads", {}).setdefault(
            marker, str(row.get("ID") or "")
        )
        name = f"{row.get('NAME') or ''} {row.get('LAST_NAME') or ''}".strip()
        source_lead_semantic.append(
            {
                "identity": marker,
                "source": LEAD_SOURCE_MAP.get(str(row.get("SOURCE_ID") or ""), "site"),
                "name": (name or (row.get("TITLE") or ""))[:255],
                "company": (row.get("COMPANY_TITLE") or "")[:255],
                "phone": (_first_value(row.get("PHONE")) or "")[:64] or None,
                "email": (_first_value(row.get("EMAIL")) or "")[:128] or None,
                "product": (row.get("TITLE") or "")[:128],
                "message": marker,
                "status": LEAD_STATUS_MAP.get(str(row.get("STATUS_ID") or "NEW"), "rejected"),
                "assigned_to": users_by_id.get(str(row.get("ASSIGNED_BY_ID") or ""), "")[:128],
                "created_at": _naive(row.get("DATE_CREATE")) or datetime.fromisoformat(FROM_ISO),
            }
        )

    source_call_semantic = []
    for row in calls:
        call_id = str(row.get("CALL_ID") or row.get("ID"))[:64]
        source_identity_ids.setdefault("bitrix_calls", {}).setdefault(
            call_id, str(row.get("ID") or call_id)
        )
        started = _naive(row.get("CALL_START_DATE")) or datetime.fromisoformat(FROM_ISO)
        duration = int(row.get("CALL_DURATION") or 0)
        answered = str(row.get("CALL_FAILED_CODE") or "") == "200" and duration > 0
        entity_type = row.get("CRM_ENTITY_TYPE")
        entity_id = str(row.get("CRM_ENTITY_ID") or "")
        contact = contacts_by_id.get(entity_id) if entity_type == "CONTACT" else None
        contact_link = None
        if contact:
            full_name, phone, email = source_contact_fields(contact)
            contact_link = _opaque_identity("contact", full_name, phone, email)
        counterparty = (
            company_link(entity_id)
            if entity_type == "COMPANY"
            else company_link(contact.get("COMPANY_ID")) if contact else None
        )
        source_call_semantic.append(
            {
                "identity": call_id,
                "direction": "out" if str(row.get("CALL_TYPE")) in ("1", "4") else "in",
                "phone_e164": (row.get("PHONE_NUMBER") or "")[:32] or None,
                "owner": users_by_id.get(str(row.get("PORTAL_USER_ID") or ""), "")[:128],
                "counterparty_link": counterparty,
                "contact_link": contact_link,
                "status": "ended" if answered else "missed",
                "recording_url": (row.get("CALL_RECORD_URL") or "")[:255] or None,
                "started_at": started,
                "answered_at": started if answered else None,
                "ended_at": started + timedelta(seconds=duration),
                "duration_sec": duration or None,
            }
        )

    onec_cp_names = {
        str(row.get("Ref_Key")): (row.get("Description") or "").strip()[:255] or "Без имени"
        for row in onec_counterparties
        if row.get("Ref_Key")
    }
    source_payment_semantic = []
    for row in onec_sales:
        if row.get("Posted") is False:
            continue
        entity_ref = f"1c:sale:{row.get('Ref_Key')}"
        source_identity_ids.setdefault("onec_payments", {}).setdefault(
            entity_ref, str(row.get("Ref_Key") or "")
        )
        number = (row.get("Number") or "").strip()
        source_payment_semantic.append(
            {
                "identity": entity_ref,
                "ref": number or entity_ref,
                "amount": _dec(row.get("СуммаДокумента")),
                "status": "pending",
                "kind": "receivable",
                "counterparty_ref": (
                    onec_cp_names.get(str(row.get("Контрагент_Key") or ""), "")[:64] or None
                ),
                "entity_ref": entity_ref,
                "description": f"Реализация {number} от {str(row.get('Date') or '')[:10]}"[:255],
                "paid_at": None,
                "due_date": None,
            }
        )
    source_sku_semantic = [
        {
            "identity": (row.get("Code") or "").strip(),
            "code": (row.get("Code") or "").strip(),
            "title": (row.get("Description") or row.get("Code") or "")[:255],
        }
        for row in onec_sku
        if (row.get("Code") or "").strip()
    ]
    source_identity_ids["onec_sku"] = {
        str(row.get("Code") or "").strip(): str(row.get("Ref_Key") or "")
        for row in onec_sku
        if (row.get("Code") or "").strip()
    }
    source_identity_ids["onec_stock_prices"] = {
        f"{row.get('Code').strip()}|Главный": str(row.get("Ref_Key") or row.get("Code") or "")
        for row in onec_sku
        if (row.get("Code") or "").strip()
    }
    source_semantic_rows = {
        "bitrix_companies": source_company_semantic,
        "bitrix_contacts": source_contact_semantic,
        "bitrix_deals": source_deal_semantic,
        "bitrix_leads": source_lead_semantic,
        "bitrix_calls": source_call_semantic,
        "onec_payments": source_payment_semantic,
        "onec_sku": source_sku_semantic,
        "onec_stock_prices": _expected_stock_semantic_rows(onec_sku, onec_sales),
    }
    semantic = {name: _semantic_summary(rows) for name, rows in source_semantic_rows.items()}
    report = {
        "source": source,
        "links": links,
        "stages": stages,
        "products": products,
        "financial": financial,
        "semantic": semantic,
        "deduplication": {
            "bitrix_contacts": {
                "source_rows": len(contacts),
                "unique_import_keys": len(source_contact_semantic),
                "deduplicated_rows": len(contacts) - len(source_contact_semantic),
                "key": "full_name+phone+email",
            }
        },
        "users": {"source_rows": len(users), "imported_by_load": False},
        "activities": {
            "dedicated_source_available": bool(dedicated_activity_names & files.keys()),
            "call_rows_available": len(calls),
        },
        "files": {
            "dedicated_source_available": bool(dedicated_file_names & files.keys()),
            "call_rows_with_recording_metadata": call_file_ref_rows,
            "binary_files_in_cache": 0,
        },
        "history": {
            "dedicated_source_available": bool(dedicated_history_names & files.keys()),
            "stage_history_rows_available": False,
        },
    }
    # Сырые semantic rows нужны только внутреннему сравнению полей. Не включать их
    # в печатаемый/сохраняемый aggregate report: там могут быть PII из локального кэша.
    if include_semantic_rows:
        report["_semantic_rows"] = source_semantic_rows
        report["_source_identity_ids"] = source_identity_ids
    return report


def _cached(name: str) -> bool:
    path = OUT_DIR / f"{name}.jsonl"
    if path.exists() and path.stat().st_size > 0:
        print(f"extract: {name} — уже в кэше, пропуск")
        return True
    return False


def _chunks(seq: list, n: int = 50):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def extract() -> None:
    global OUT_DIR
    OUT_DIR = _resolve_cache_dir()
    nov = {">=DATE_CREATE": FROM_ISO + "+03:00", "<DATE_CREATE": TO_ISO + "+03:00"}

    if not _cached("bx_deals"):
        _dump("bx_deals", bx_list("crm.deal.list", {"filter": nov, "order": {"ID": "ASC"}, "select": [
            "ID", "TITLE", "STAGE_ID", "CATEGORY_ID", "OPPORTUNITY", "CURRENCY_ID", "COMPANY_ID",
            "CONTACT_ID", "ASSIGNED_BY_ID", "DATE_CREATE", "CLOSEDATE", "SOURCE_ID"]}))
    if not _cached("bx_leads"):
        _dump("bx_leads", bx_list("crm.lead.list", {"filter": nov, "order": {"ID": "ASC"}, "select": [
            "ID", "TITLE", "NAME", "LAST_NAME", "COMPANY_TITLE", "STATUS_ID", "SOURCE_ID",
            "ASSIGNED_BY_ID", "DATE_CREATE", "PHONE", "EMAIL"]}))
    if not _cached("bx_calls"):
        _dump("bx_calls", bx_list("voximplant.statistic.get", {"FILTER": {
            ">=CALL_START_DATE": FROM_ISO + "+03:00", "<CALL_START_DATE": TO_ISO + "+03:00"},
            "SORT": "ID", "ORDER": "ASC"}))
    if not _cached("bx_users"):
        _dump("bx_users", bx_list("user.get", {}))
    if not _cached("bx_sources"):
        _dump("bx_sources", bx("crm.status.list",
                               {"filter": {"ENTITY_ID": "SOURCE"}}).get("result", []))

    deals = _load_jsonl("bx_deals")
    calls = _load_jsonl("bx_calls")
    company_ids = sorted({d["COMPANY_ID"] for d in deals if d.get("COMPANY_ID") not in (None, "0")},
                         key=int)
    contact_ids = {d["CONTACT_ID"] for d in deals if d.get("CONTACT_ID") not in (None, "0")}
    contact_ids |= {c["CRM_ENTITY_ID"] for c in calls
                    if c.get("CRM_ENTITY_TYPE") == "CONTACT" and c.get("CRM_ENTITY_ID")}
    company_ids_from_calls = {c["CRM_ENTITY_ID"] for c in calls
                              if c.get("CRM_ENTITY_TYPE") == "COMPANY" and c.get("CRM_ENTITY_ID")}
    company_ids = sorted(set(company_ids) | {str(x) for x in company_ids_from_calls}, key=int)
    contact_ids = sorted({str(x) for x in contact_ids}, key=int)

    if not _cached("bx_companies"):
        rows = []
        for chunk in _chunks(company_ids):
            rows += bx_list("crm.company.list", {"filter": {"@ID": chunk}, "select": [
                "ID", "TITLE", "PHONE", "EMAIL"]})
        _dump("bx_companies", rows)
    if not _cached("bx_contacts"):
        rows = []
        for chunk in _chunks(contact_ids):
            rows += bx_list("crm.contact.list", {"filter": {"@ID": chunk}, "select": [
                "ID", "NAME", "LAST_NAME", "COMPANY_ID", "PHONE", "EMAIL"]})
        _dump("bx_contacts", rows)
    if not _cached("bx_requisites"):
        rows = []
        for chunk in _chunks(company_ids):
            rows += bx_list("crm.requisite.list", {"filter": {
                "ENTITY_TYPE_ID": "4", "@ENTITY_ID": chunk}, "select": ["ENTITY_ID", "RQ_INN"]})
        _dump("bx_requisites", rows)

    # --- 1С: реализации + ссылочные контрагенты и номенклатура ---
    extract_onec()
    print("extract: готово ->", OUT_DIR)


def extract_onec() -> None:
    """Только 1С (без Bitrix): реализации окна + SKU/контрагенты по ключам.

    Для живой ``ka_copy`` (данные с окт.2025) задайте
    ``IMPORT_FROM``/``IMPORT_ONEC_FROM`` на месяц с продажами, напр. 2025-12.
    """
    global OUT_DIR
    OUT_DIR = _resolve_cache_dir()
    if not _onec_base_url():
        raise RuntimeError("ONEC_BASE_URL / IMPORT_ONEC_BASE не задан — extract-onec невозможен")
    if not _cached("onec_sales"):
        docs = onec_window("Document_РеализацияТоваровУслуг", ONEC_FROM, ONEC_TO)
        _dump("onec_sales", docs)
    docs = _load_jsonl("onec_sales")
    if docs and not _cached("onec_counterparties"):
        refs = sorted({d["Контрагент_Key"] for d in docs if d.get("Контрагент_Key")})
        rows = [r for r in (onec_by_key("Catalog_Контрагенты", k,
                                        "Ref_Key,Description,НаименованиеПолное,ИНН")
                            for k in refs) if r]
        _dump("onec_counterparties", rows)
    if docs and not _cached("onec_sku"):
        refs = sorted({item["Номенклатура_Key"]
                       for d in docs for item in (d.get("Товары") or [])
                       if item.get("Номенклатура_Key")})
        rows = [r for r in (onec_by_key("Catalog_Номенклатура", k, "Ref_Key,Code,Description")
                            for k in refs) if r]
        _dump("onec_sku", rows)
    print("extract-onec: готово ->", OUT_DIR, f"(sales={len(docs)})")


# ---------------------------------------------------------------- load

# Bitrix STAGE_ID (основная воронка, категория 0) -> канон stages.py
STAGE_MAP = {
    "1": "new", "2": "price_req", "UC_J58BGN": "has_price", "NEW": "invoice",
    "UC_OV09QE": "protected", "PREPARATION": "contract", "UC_U2ETYR": "contract",
    "UC_9TE3J7": "contract", "PREPAYMENT_INVOICE": "contract", "UC_RZP5B6": "contract",
    "8": "contract", "9": "contract", "UC_5G5XU7": "contract", "EXECUTING": "contract",
    "UC_LMKLAN": "contract", "FINAL_INVOICE": "contract",
    "WON": "won", "LOSE": "lost",
    "APOLOGY": "lost", "3": "lost", "4": "lost", "5": "lost", "6": "lost", "7": "lost",
}
LOST_TITLES = {
    "APOLOGY": "Купил дешевле", "3": "Купил другое", "4": "Не смогли сделать предложение",
    "5": "Нужен срочно. Нет на складе", "6": "Возврат денег: не привезли вовремя",
    "7": "Другой вариант",
}
LEAD_STATUS_MAP = {"NEW": "new", "5": "qualified", "IN_PROCESS": "qualified",
                   "CONVERTED": "converted"}
LEAD_SOURCE_MAP = {"CALL": "phone", "EMAIL": "email", "WEB": "site", "WEBFORM": "site",
                   "RC_GENERATOR": "site", "STORE": "site", "ONLINE_STORE": "site"}
LEAD_IMPORT_MARKER = "bitrix://lead/"


def _naive(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        return None


def _first_value(multifield) -> str | None:
    if isinstance(multifield, list) and multifield:
        return (multifield[0].get("VALUE") or "").strip() or None
    return None


def _dec(raw, default="0") -> Decimal:
    try:
        return Decimal(str(raw or default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _map_deal_stage(stage_id: str, category: str) -> tuple[str, str, str | None]:
    """-> (stage, funnel, lost_comment). Категория 7 Bitrix — воронка постоянных клиентов."""
    stage_id = stage_id.split(":", 1)[-1]  # Bitrix может отдавать с префиксом категории "C7:WON"
    if category == "7":
        if "WON" in stage_id:
            return "rp_won", "repeat_clients", None
        if stage_id == "LOSE" or stage_id in LOST_TITLES:
            return "rp_lost", "repeat_clients", LOST_TITLES.get(stage_id)
        if "INVOICE" in stage_id or stage_id in ("NEW", "PREPARATION", "EXECUTING"):
            return "rp_invoice", "repeat_clients", None
        return "rp_request", "repeat_clients", None
    stage = STAGE_MAP.get(stage_id, "new")
    return stage, "new_clients", LOST_TITLES.get(stage_id)


async def _load_sales_prices(session, stats: dict) -> None:
    """Цены подбора из строк реализаций 1С (последняя Цена за месяц на SKU)."""
    from datetime import timezone

    from modules.integrations.models import StockItem

    expected = _expected_stock_semantic_rows(_load_jsonl("onec_sku"), _load_jsonl("onec_sales"))
    if not expected:
        return

    warehouse = "Главный"
    existing = {
        (si.sku_code, si.warehouse): si
        for si in (await session.execute(select(StockItem))).scalars()
    }
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in expected:
        code = row["sku_code"]
        price = Decimal(row["price"])
        item = existing.get((code, warehouse))
        if item is None:
            item = StockItem(sku_code=code, warehouse=warehouse)
            session.add(item)
            existing[(code, warehouse)] = item
            stats["stock_price"] += 1
        else:
            stats["stock_price_updated"] += 1
        item.price = price
        item.updated_at = now


async def load() -> None:
    _require_isolated_load()
    from core.domain.models import Contact, Counterparty, CounterpartyAlias, Sku
    from modules.finance.models import Payment
    from modules.leads.models import Lead
    from modules.sales.models import CallLog, Deal

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()  # dev-режим: создаст таблицы
    assert db.session_factory is not None

    users = {u["ID"]: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
             for u in _load_jsonl("bx_users")}
    companies = {c["ID"]: c for c in _load_jsonl("bx_companies")}
    contacts_bx = {c["ID"]: c for c in _load_jsonl("bx_contacts")}
    unp_by_company: dict[str, str] = {}
    for r in _load_jsonl("bx_requisites"):
        inn = (r.get("RQ_INN") or "").strip()
        if inn and r["ENTITY_ID"] not in unp_by_company:
            unp_by_company[str(r["ENTITY_ID"])] = inn

    async with db.session_factory() as s:
        # --- контрагенты: эталон по УНП, привязка внешних id через alias ---
        aliases = {(a.source, a.external_ref): a.counterparty_id
                   for a in (await s.execute(select(CounterpartyAlias))).scalars()}
        cps = (await s.execute(select(Counterparty))).scalars().all()
        by_unp: dict[str, list[Counterparty]] = {}
        by_name: dict[str, list[Counterparty]] = {}
        for row in cps:
            by_name.setdefault((row.name or "").strip(), []).append(row)
            normalized = str(row.unp or "").strip()
            if normalized:
                by_unp.setdefault(normalized, []).append(row)
        stats = {k: 0 for k in ("counterparty", "contact", "deal", "lead", "call",
                                "payment", "sku", "stock_price", "stock_price_updated",
                                "date_fallback", "counterparty_unp_enrichments",
                                "counterparty_unp_conflicts",
                                "counterparty_ambiguous_name_conflicts")}

        def _dt_or_nov1(iso: str | None) -> datetime:
            """Дата или 1 ноября с явным счётчиком фолбэков (не искажать данные молча)."""
            dt = _naive(iso)
            if dt is None:
                stats["date_fallback"] += 1
                return datetime.fromisoformat(FROM_ISO)
            return dt

        async def upsert_cp(source: str, ext: str, name: str, unp: str | None) -> Counterparty:
            name = (name or "").strip()
            incoming_unp = str(unp or "").strip() or None
            key = (source, ext)
            if key in aliases:
                cp = await s.get(Counterparty, aliases[key])
                if cp is None:
                    stats["counterparty_unp_conflicts"] += 1
                    raise RuntimeError(
                        "counterparty alias points to a missing master; transaction rolled back"
                    )
                current_unp = str(cp.unp or "").strip() or None
                if incoming_unp and current_unp and incoming_unp != current_unp:
                    # Проверка до любой записи в master: drift alias не может переписать
                    # подтверждённый УНП. Выход из session context откатит весь импорт.
                    stats["counterparty_unp_conflicts"] += 1
                    raise RuntimeError(
                        "counterparty alias UNP conflict; transaction rolled back"
                    )
                if incoming_unp and not current_unp:
                    owners = by_unp.get(incoming_unp, [])
                    if any(row.id != cp.id for row in owners):
                        stats["counterparty_unp_conflicts"] += 1
                        raise RuntimeError(
                            "counterparty alias UNP conflict; transaction rolled back"
                        )
                    cp.unp = incoming_unp
                    by_unp.setdefault(incoming_unp, []).append(cp)
                    stats["counterparty_unp_enrichments"] += 1
                return cp

            cp = None
            if incoming_unp:
                unp_matches = by_unp.get(incoming_unp, [])
                if len(unp_matches) > 1:
                    stats["counterparty_unp_conflicts"] += 1
                    raise RuntimeError(
                        "duplicate master UNP conflict; transaction rolled back"
                    )
                if unp_matches:
                    cp = unp_matches[0]
                else:
                    # Имя допускает enrichment только одного master без УНП. Если
                    # такой master соседствует с другим УНП, новый UNP получает свой
                    # master и не склеивается по имени.
                    same_name = by_name.get(name, [])
                    empty_unp = [row for row in same_name if not str(row.unp or "").strip()]
                    occupied_other_unp = [
                        row for row in same_name
                        if str(row.unp or "").strip() and str(row.unp).strip() != incoming_unp
                    ]
                    if occupied_other_unp:
                        cp = None
                    elif len(empty_unp) == 1:
                        cp = empty_unp[0]
                    elif len(empty_unp) > 1:
                        stats["counterparty_ambiguous_name_conflicts"] += 1
                        raise RuntimeError(
                            "ambiguous empty-UNP counterparty name; transaction rolled back"
                        )
            else:
                same_name = by_name.get(name, [])
                if len(same_name) > 1:
                    stats["counterparty_ambiguous_name_conflicts"] += 1
                    raise RuntimeError(
                        "ambiguous counterparty name without UNP; transaction rolled back"
                    )
                if same_name:
                    cp = same_name[0]

            if cp is None:
                prov = {"name": {"source": source, "at": LABEL}}
                if incoming_unp:
                    prov["unp"] = {"source": source, "at": LABEL}
                cp = Counterparty(name=name, unp=incoming_unp, provenance=prov)
                s.add(cp)
                await s.flush()
                by_name.setdefault(name, []).append(cp)
                if incoming_unp:
                    by_unp.setdefault(incoming_unp, []).append(cp)
                stats["counterparty"] += 1
            elif incoming_unp and not str(cp.unp or "").strip():
                owners = by_unp.get(incoming_unp, [])
                if any(row.id != cp.id for row in owners):
                    stats["counterparty_unp_conflicts"] += 1
                    raise RuntimeError(
                        "counterparty UNP conflict; transaction rolled back"
                    )
                cp.unp = incoming_unp
                by_unp.setdefault(incoming_unp, []).append(cp)
                stats["counterparty_unp_enrichments"] += 1
            s.add(CounterpartyAlias(counterparty_id=cp.id, source=source, external_ref=ext))
            aliases[key] = cp.id
            return cp

        cp_by_bx_company: dict[str, Counterparty] = {}
        for cid, comp in companies.items():
            name = (comp.get("TITLE") or f"Компания {cid}").strip()[:255]
            cp_by_bx_company[cid] = await upsert_cp(
                "bitrix", f"company:{cid}", name, unp_by_company.get(cid))

        onec_cp_names: dict[str, str] = {}
        for row in _load_jsonl("onec_counterparties"):
            name = (row.get("Description") or "").strip()[:255] or "Без имени"
            unp = (row.get("ИНН") or "").strip() or None
            await upsert_cp("1c", row["Ref_Key"], name, unp)
            onec_cp_names[row["Ref_Key"]] = name

        # --- контакты Bitrix ---
        existing_contacts = {(c.full_name, c.phone, c.email): c.id
                             for c in (await s.execute(select(Contact))).scalars()}
        contact_id_map: dict[str, int] = {}
        cp_by_bx_contact: dict[str, int] = {}
        for cid, c in contacts_bx.items():
            full_name = f"{c.get('NAME') or ''} {c.get('LAST_NAME') or ''}".strip()[:255]
            full_name = full_name or f"Контакт {cid}"
            phone = (_first_value(c.get("PHONE")) or "")[:64] or None
            email = _first_value(c.get("EMAIL")) or None
            comp = cp_by_bx_company.get(str(c.get("COMPANY_ID") or ""))
            key = (full_name, phone, email)
            if key not in existing_contacts:
                row = Contact(counterparty_id=comp.id if comp else None, full_name=full_name,
                              phone=phone, email=email)
                s.add(row)
                await s.flush()
                existing_contacts[key] = row.id
                stats["contact"] += 1
            contact_id_map[cid] = existing_contacts[key]
            if comp:
                cp_by_bx_contact[cid] = comp.id

        # --- сделки Bitrix (категории 0 — новые клиенты, 7 — постоянные) ---
        existing_deals = set((await s.execute(select(Deal.number))).scalars())
        skipped_categories: dict[str, int] = {}
        for d in _load_jsonl("bx_deals"):
            cat = str(d.get("CATEGORY_ID") or "0")
            if cat not in ("0", "7"):
                skipped_categories[cat] = skipped_categories.get(cat, 0) + 1
                continue
            number = f"BX-{d['ID']}"
            if number in existing_deals:
                continue
            stage, funnel, lost_comment = _map_deal_stage(str(d.get("STAGE_ID") or ""), cat)
            comp = cp_by_bx_company.get(str(d.get("COMPANY_ID") or ""))
            contact = contacts_bx.get(str(d.get("CONTACT_ID") or ""))
            cp_name = comp.name if comp else (
                f"{contact.get('NAME') or ''} {contact.get('LAST_NAME') or ''}".strip()
                if contact else "Не указан")
            created = _dt_or_nov1(d.get("DATE_CREATE"))
            closed = _naive(d.get("CLOSEDATE"))
            terminal = stage in ("won", "lost", "rp_won", "rp_lost")
            s.add(Deal(
                number=number, title=(d.get("TITLE") or number)[:255],
                counterparty=cp_name[:255] or "Не указан",
                amount=_dec(d.get("OPPORTUNITY")), stage=stage, funnel=funnel,
                owner=users.get(str(d.get("ASSIGNED_BY_ID") or ""), "")[:128],
                deal_date=str(created.date()),
                closed_date=str(closed.date()) if (terminal and closed) else None,
                created_at=created, stage_changed_at=(closed if terminal and closed else created),
                lost_comment=lost_comment,
            ))
            existing_deals.add(number)
            stats["deal"] += 1

        # --- лиды Bitrix ---
        existing_leads = set(
            (await s.execute(select(Lead.message).where(Lead.message.like(f"{LEAD_IMPORT_MARKER}%")))).scalars()
        )
        for ld in _load_jsonl("bx_leads"):
            ext = f"{LEAD_IMPORT_MARKER}{ld['ID']}"
            if ext in existing_leads:
                continue
            status_id = str(ld.get("STATUS_ID") or "NEW")
            name = f"{ld.get('NAME') or ''} {ld.get('LAST_NAME') or ''}".strip()
            s.add(Lead(
                source=LEAD_SOURCE_MAP.get(str(ld.get("SOURCE_ID") or ""), "site"),
                name=(name or (ld.get("TITLE") or ""))[:255],
                company=(ld.get("COMPANY_TITLE") or "")[:255],
                phone=(_first_value(ld.get("PHONE")) or "")[:64] or None,
                email=(_first_value(ld.get("EMAIL")) or "")[:128] or None,
                product=(ld.get("TITLE") or "")[:128],
                message=ext,
                status=LEAD_STATUS_MAP.get(status_id, "rejected"),
                assigned_to=users.get(str(ld.get("ASSIGNED_BY_ID") or ""), "")[:128],
                created_at=_dt_or_nov1(ld.get("DATE_CREATE")),
            ))
            existing_leads.add(ext)
            stats["lead"] += 1

        # --- звонки Bitrix ---
        existing_calls = set((await s.execute(select(CallLog.call_id))).scalars())
        for c in _load_jsonl("bx_calls"):
            call_id = str(c.get("CALL_ID") or c["ID"])[:64]
            if call_id in existing_calls:
                continue
            started = _dt_or_nov1(c.get("CALL_START_DATE"))
            duration = int(c.get("CALL_DURATION") or 0)
            answered = str(c.get("CALL_FAILED_CODE") or "") == "200" and duration > 0
            ent_type, ent_id = c.get("CRM_ENTITY_TYPE"), str(c.get("CRM_ENTITY_ID") or "")
            s.add(CallLog(
                call_id=call_id,
                direction="out" if str(c.get("CALL_TYPE")) in ("1", "4") else "in",
                phone_e164=(c.get("PHONE_NUMBER") or "")[:32] or None,
                owner=users.get(str(c.get("PORTAL_USER_ID") or ""), "")[:128],
                counterparty_id=(cp_by_bx_company[ent_id].id
                                 if ent_type == "COMPANY" and ent_id in cp_by_bx_company
                                 else cp_by_bx_contact.get(ent_id)
                                 if ent_type == "CONTACT" else None),
                contact_id=contact_id_map.get(ent_id) if ent_type == "CONTACT" else None,
                status="ended" if answered else "missed",
                recording_url=(c.get("CALL_RECORD_URL") or "")[:255] or None,
                started_at=started,
                answered_at=started if answered else None,
                ended_at=started + timedelta(seconds=duration),
                duration_sec=duration or None,
            ))
            existing_calls.add(call_id)
            stats["call"] += 1

        # --- реализации 1С -> finance.payment (выручка по факту отгрузки) ---
        existing_refs = set((await s.execute(select(Payment.entity_ref))).scalars())
        for doc in _load_jsonl("onec_sales"):
            if doc.get("Posted") is False:
                continue
            ent = f"1c:sale:{doc['Ref_Key']}"
            if ent in existing_refs:
                continue
            cp_name = onec_cp_names.get(doc.get("Контрагент_Key") or "", "")
            number = (doc.get("Number") or "").strip()
            s.add(Payment(
                ref=number or ent, amount=_dec(doc.get("СуммаДокумента")),
                # Posted подтверждает проведение реализации, но не банковское поступление.
                status="pending", kind="receivable",
                paid_at=None, due_date=None,
                counterparty_ref=cp_name[:64] or None, entity_ref=ent,
                description=f"Реализация {number} от {str(doc.get('Date') or '')[:10]}"[:255],
            ))
            existing_refs.add(ent)
            stats["payment"] += 1

        # --- номенклатура 1С -> SKU (golden record по коду) ---
        existing_sku = set((await s.execute(select(Sku.code))).scalars())
        for row in _load_jsonl("onec_sku"):
            code = (row.get("Code") or "").strip()
            if not code or code in existing_sku:
                continue
            s.add(Sku(code=code, title=(row.get("Description") or code)[:255],
                      provenance={"title": {"source": "1c", "at": LABEL}}))
            existing_sku.add(code)
            stats["sku"] += 1

        await _load_sales_prices(s, stats)

        await s.commit()

    await db.disconnect()
    if skipped_categories:
        print("load: пропущены сделки не-продажных воронок Bitrix:", skipped_categories)
    print("load: добавлено —", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def load_prices() -> None:
    """Только цены подбора из кэша реализаций (без Bitrix/лидов)."""
    _require_isolated_load()

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    async with db.session_factory() as s:
        stats = {"stock_price": 0, "stock_price_updated": 0}
        await _load_sales_prices(s, stats)
        await s.commit()
    await db.disconnect()
    print("load-prices:", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def load_onec() -> None:
    """Sku + StockItem.price из кэша 1С (без Bitrix). Идемпотентно."""
    _require_isolated_load()
    from core.domain.models import Sku

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    stats = {"sku": 0, "stock_price": 0, "stock_price_updated": 0}
    async with db.session_factory() as s:
        existing_sku = set((await s.execute(select(Sku.code))).scalars())
        for row in _load_jsonl("onec_sku"):
            code = (row.get("Code") or "").strip()
            if not code or code in existing_sku:
                continue
            s.add(Sku(
                code=code,
                title=(row.get("Description") or code)[:255],
                provenance={"title": {"source": "1c", "at": LABEL}},
            ))
            existing_sku.add(code)
            stats["sku"] += 1
        await _load_sales_prices(s, stats)
        await s.commit()
    await db.disconnect()
    print("load-onec:", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def _destination_reconciliation(
    db,
    source_report: dict,
    source_semantic_rows: dict[str, list[dict]] | None = None,
    detail_rows: list[dict] | None = None,
    source_identity_ids: dict[str, dict[str, str]] | None = None,
) -> dict:
    from core.domain.models import Contact, Counterparty, CounterpartyAlias, Sku, User
    from modules.finance.models import Payment, PaymentAllocation
    from modules.integrations.models import StockItem
    from modules.leads.models import Lead
    from modules.sales.models import Activity, CallLog, Deal, DealItem, DealStageEvent, Stage

    async def count(model, *criteria) -> int:
        statement = select(func.count()).select_from(model)
        if criteria:
            statement = statement.where(*criteria)
        value = (await session.execute(statement)).scalar_one()
        return int(value)

    source_records = source_report["source"]["records"]
    expected_deals = source_report["stages"]["supported_deal_rows"]
    source_semantic = source_report["semantic"]
    source_identity_ids = source_identity_ids or {}
    async with db.session_factory() as session:
        counts = {
            "counterparties": await count(Counterparty),
            "counterparty_aliases_bitrix_companies": await count(
                CounterpartyAlias,
                CounterpartyAlias.source == "bitrix",
                CounterpartyAlias.external_ref.like("company:%"),
            ),
            "counterparty_aliases_onec": await count(
                CounterpartyAlias, CounterpartyAlias.source == "1c"
            ),
            "contacts": await count(Contact),
            "deals_bitrix_supported": await count(Deal, Deal.number.like("BX-%")),
            "leads_bitrix": await count(Lead, Lead.message.like(f"{LEAD_IMPORT_MARKER}%")),
            "calls_bitrix": await count(CallLog),
            "payments_onec": await count(Payment, Payment.entity_ref.like("1c:sale:%")),
            "payment_allocations": await count(PaymentAllocation),
            "skus": await count(Sku),
            "stock_items_with_price": await count(StockItem, StockItem.price > 0),
            "users": await count(User),
            "deal_items": await count(DealItem),
            "activities": await count(Activity),
            "stage_events": await count(DealStageEvent),
            "stages": await count(Stage),
        }

        counterparties = (await session.execute(select(Counterparty))).scalars().all()
        counterparties_by_id = {row.id: row for row in counterparties}
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        aliases_by_counterparty: dict[int, list[CounterpartyAlias]] = {}
        for alias in aliases:
            aliases_by_counterparty.setdefault(alias.counterparty_id, []).append(alias)

        # Аудит строится по агрегатам: source external_ref -> destination master -> UNP.
        # Сами external_ref и UNP не попадают в report, чтобы не раскрывать кэш.
        source_alias_entries: list[tuple[tuple[str, str], str | None]] = []
        for row in _load_jsonl("bx_companies"):
            external_id = str(row.get("ID") or "")
            if external_id:
                source_alias_entries.append((
                    ("bitrix", f"company:{external_id}"),
                    None,
                ))
        source_unp_by_company: dict[str, str] = {}
        for row in _load_jsonl("bx_requisites"):
            company_id = str(row.get("ENTITY_ID") or "")
            unp = str(row.get("RQ_INN") or "").strip()
            if company_id and unp and company_id not in source_unp_by_company:
                source_unp_by_company[company_id] = unp
        source_alias_entries = [
            (key, source_unp_by_company.get(key[1].removeprefix("company:")))
            if key[0] == "bitrix" else (key, unp)
            for key, unp in source_alias_entries
        ]
        for row in _load_jsonl("onec_counterparties"):
            external_ref = str(row.get("Ref_Key") or "")
            if external_ref:
                source_alias_entries.append((
                    ("1c", external_ref),
                    str(row.get("ИНН") or "").strip() or None,
                ))
        source_aliases: dict[tuple[str, str], list[str | None]] = {}
        for key, unp in source_alias_entries:
            source_aliases.setdefault(key, []).append(unp)

        destination_alias_rows = [
            alias for alias in aliases
            if alias.source == "1c"
            or (alias.source == "bitrix" and alias.external_ref.startswith("company:"))
        ]
        destination_aliases: dict[tuple[str, str], list[CounterpartyAlias]] = {}
        for alias in destination_alias_rows:
            destination_aliases.setdefault((alias.source, alias.external_ref), []).append(alias)

        source_alias_conflict_keys: set[tuple[str, str]] = set()
        destination_unp_conflict_keys: set[tuple[str, str]] = set()
        destination_multiple_master_keys: set[tuple[str, str]] = set()
        allowed_unp_enrichment = 0
        unresolved_destination_refs = 0
        master_expected_unps: dict[int, set[str]] = {}
        for key, expected_values in source_aliases.items():
            expected_unps = {value for value in expected_values if value}
            if len(expected_unps) > 1:
                source_alias_conflict_keys.add(key)
            expected_unp = next(iter(expected_unps), None)
            actual_rows = destination_aliases.get(key, [])
            actual_ids = {row.counterparty_id for row in actual_rows}
            if len(actual_ids) > 1:
                destination_multiple_master_keys.add(key)
            actual_unps: set[str] = set()
            for alias in actual_rows:
                if expected_unp:
                    master_expected_unps.setdefault(alias.counterparty_id, set()).add(expected_unp)
                master = counterparties_by_id.get(alias.counterparty_id)
                if master is None:
                    unresolved_destination_refs += 1
                    continue
                actual_unp = str(master.unp or "").strip()
                if actual_unp:
                    actual_unps.add(actual_unp)
            if expected_unp:
                # Отсутствующий alias — отдельный missing_refs результат; это не
                # конфликт UNP, пока destination не заявляет неверный master.
                if actual_rows and actual_unps != {expected_unp}:
                    destination_unp_conflict_keys.add(key)
            elif actual_unps:
                allowed_unp_enrichment += 1

        master_sources: dict[int, set[str]] = {}
        master_alias_counts: dict[int, int] = {}
        for alias in destination_alias_rows:
            master_sources.setdefault(alias.counterparty_id, set()).add(alias.source)
            master_alias_counts[alias.counterparty_id] = master_alias_counts.get(alias.counterparty_id, 0) + 1
        by_source_alias_audit = {}
        for source_name in ("bitrix", "1c"):
            source_keys = {key for key in source_aliases if key[0] == source_name}
            destination_keys = {key for key in destination_aliases if key[0] == source_name}
            by_source_alias_audit[source_name] = {
                "source_ref_rows": sum(len(source_aliases[key]) for key in source_keys),
                "destination_alias_rows": sum(len(destination_aliases[key]) for key in destination_keys),
                "source_refs_with_unp": sum(
                    any(value for value in source_aliases[key]) for key in source_keys
                ),
                "destination_refs_with_unp": sum(
                    any(str(counterparties_by_id.get(alias.counterparty_id).unp or "").strip()
                        for alias in destination_aliases[key]
                        if counterparties_by_id.get(alias.counterparty_id) is not None)
                    for key in destination_keys
                ),
                "missing_destination_refs": len(source_keys - destination_keys),
                "extra_destination_refs": len(destination_keys - source_keys),
            }
        alias_audit = {
            "by_source": by_source_alias_audit,
            "source_ref_rows": len(source_alias_entries),
            "destination_alias_rows": len(destination_alias_rows),
            "missing_destination_refs": len(set(source_aliases) - set(destination_aliases)),
            "extra_destination_refs": len(set(destination_aliases) - set(source_aliases)),
            "source_duplicate_refs": sum(max(len(values) - 1, 0) for values in source_aliases.values()),
            "destination_duplicate_refs": sum(max(len(values) - 1, 0) for values in destination_aliases.values()),
            "source_unp_conflict_refs": len(source_alias_conflict_keys),
            "destination_unp_conflict_refs": len(destination_unp_conflict_keys),
            "destination_refs_to_multiple_masters": len(destination_multiple_master_keys),
            "unresolved_destination_refs": unresolved_destination_refs,
            "unp_conflict_refs": len(source_alias_conflict_keys | destination_unp_conflict_keys),
            "conflict_refs": len(
                source_alias_conflict_keys
                | destination_unp_conflict_keys
                | destination_multiple_master_keys
            ),
            "allowed_unp_enrichment_refs": allowed_unp_enrichment,
            "master_rows_with_multiple_source_unps": sum(
                len(unps) > 1 for unps in master_expected_unps.values()
            ),
            "master_rows_with_multiple_aliases": sum(count > 1 for count in master_alias_counts.values()),
            "master_rows_with_bitrix_and_onec_aliases": sum(
                {"bitrix", "1c"}.issubset(sources) for sources in master_sources.values()
            ),
        }

        def bitrix_company_link(counterparty_id: int | None) -> str | None:
            if counterparty_id is None:
                return None
            refs = sorted(
                alias.external_ref
                for alias in aliases_by_counterparty.get(counterparty_id, [])
                if alias.source == "bitrix" and alias.external_ref.startswith("company:")
            )
            return refs[0] if refs else None

        contacts = (await session.execute(select(Contact))).scalars().all()
        contacts_by_id = {row.id: row for row in contacts}

        def contact_semantic(row: Contact) -> dict:
            return {
                "identity": _opaque_identity("contact", row.full_name, row.phone, row.email),
                "full_name": row.full_name,
                "phone": row.phone,
                "email": row.email,
                "counterparty_link": bitrix_company_link(row.counterparty_id),
            }

        destination_semantic_rows = {
            "bitrix_companies": [
                {
                    "identity": alias.external_ref,
                    "name": counterparties_by_id[alias.counterparty_id].name,
                    "unp": counterparties_by_id[alias.counterparty_id].unp,
                }
                for alias in aliases
                if alias.source == "bitrix"
                and alias.external_ref.startswith("company:")
                and alias.counterparty_id in counterparties_by_id
            ],
            "bitrix_contacts": [contact_semantic(row) for row in contacts],
        }

        deals = (
            await session.execute(select(Deal).where(Deal.number.like("BX-%")))
        ).scalars().all()
        counterparty_name_counts: dict[str, int] = {}
        for master in counterparties:
            if master.is_active is False:
                continue
            name = (master.name or "").strip()
            if name:
                counterparty_name_counts[name] = counterparty_name_counts.get(name, 0) + 1
        ambiguous_counterparty_names = {
            name for name, count in counterparty_name_counts.items() if count > 1
        }
        counts["deal_counterparty_ambiguous_names"] = len({
            row.counterparty for row in deals if row.counterparty in ambiguous_counterparty_names
        })
        counts["deals_with_ambiguous_counterparty_name"] = sum(
            row.counterparty in ambiguous_counterparty_names for row in deals
        )
        if detail_rows is not None:
            source_deals_by_identity = {
                str(row.get("identity")): row
                for row in (source_semantic_rows or {}).get("bitrix_deals", [])
            }
            deal_source_ids = source_identity_ids.get("bitrix_deals", {})
            for row in sorted(deals, key=lambda item: str(item.number)):
                if row.counterparty not in ambiguous_counterparty_names:
                    continue
                expected = source_deals_by_identity.get(str(row.number), {})
                detail_rows.append({
                    "kind": "ambiguous_deal_counterparty",
                    "dataset": "bitrix_deals",
                    "source_id": deal_source_ids.get(str(row.number), str(row.number)),
                    "identity": row.number,
                    "destination_id": row.id,
                    "changed_fields": ["counterparty"],
                    "source": {
                        "counterparty": _semantic_value(expected.get("counterparty")),
                    },
                    "destination": {"counterparty": _semantic_value(row.counterparty)},
                    "reason": "distinct active counterparties share this name",
                })
        destination_semantic_rows["bitrix_deals"] = [
            {
                "identity": row.number,
                "title": row.title,
                "counterparty": row.counterparty,
                "amount": row.amount,
                "stage": row.stage,
                "funnel": row.funnel,
                "owner": row.owner,
                "deal_date": row.deal_date,
                "closed_date": row.closed_date,
                "lost_comment": row.lost_comment,
            }
            for row in deals
        ]

        leads = (
            await session.execute(select(Lead).where(Lead.message.like(f"{LEAD_IMPORT_MARKER}%")))
        ).scalars().all()
        destination_semantic_rows["bitrix_leads"] = [
            {
                "identity": row.message,
                "source": row.source,
                "name": row.name,
                "company": row.company,
                "phone": row.phone,
                "email": row.email,
                "product": row.product,
                "message": row.message,
                "status": row.status,
                "assigned_to": row.assigned_to,
                "created_at": row.created_at,
            }
            for row in leads
        ]

        calls = (await session.execute(select(CallLog))).scalars().all()
        destination_semantic_rows["bitrix_calls"] = [
            {
                "identity": row.call_id,
                "direction": row.direction,
                "phone_e164": row.phone_e164,
                "owner": row.owner,
                "counterparty_link": bitrix_company_link(row.counterparty_id),
                "contact_link": (
                    _opaque_identity(
                        "contact",
                        contacts_by_id[row.contact_id].full_name,
                        contacts_by_id[row.contact_id].phone,
                        contacts_by_id[row.contact_id].email,
                    )
                    if row.contact_id in contacts_by_id
                    else None
                ),
                "status": row.status,
                "recording_url": row.recording_url,
                "started_at": row.started_at,
                "answered_at": row.answered_at,
                "ended_at": row.ended_at,
                "duration_sec": row.duration_sec,
            }
            for row in calls
        ]

        payments = (
            await session.execute(select(Payment).where(Payment.entity_ref.like("1c:sale:%")))
        ).scalars().all()
        allocation_payment_ids = set(
            (await session.execute(select(PaymentAllocation.payment_id))).scalars()
        )
        payment_status_counts: dict[str, int] = {}
        legacy_paid_without_allocations = 0
        for row in payments:
            payment_status_counts[row.status] = payment_status_counts.get(row.status, 0) + 1
            if row.status == "paid" and row.id not in allocation_payment_ids:
                legacy_paid_without_allocations += 1
        destination_semantic_rows["onec_payments"] = [
            {
                "identity": row.entity_ref,
                "ref": row.ref,
                "amount": row.amount,
                "status": row.status,
                "kind": row.kind,
                "counterparty_ref": row.counterparty_ref,
                "entity_ref": row.entity_ref,
                "description": row.description,
                "paid_at": row.paid_at,
                "due_date": row.due_date,
            }
            for row in payments
        ]

        skus = (await session.execute(select(Sku))).scalars().all()
        destination_semantic_rows["onec_sku"] = [
            {"identity": row.code, "code": row.code, "title": row.title}
            for row in skus
        ]
        stock_items = (
            await session.execute(select(StockItem).where(StockItem.price > 0))
        ).scalars().all()
        destination_semantic_rows["onec_stock_prices"] = [
            {
                "identity": f"{row.sku_code}|{row.warehouse}",
                "sku_code": row.sku_code,
                "warehouse": row.warehouse,
                "price": row.price,
            }
            for row in stock_items
        ]

    destination_semantic = {
        name: _semantic_summary(rows) for name, rows in destination_semantic_rows.items()
    }
    fidelity = {}
    source_semantic_rows = source_semantic_rows or {}
    for name, expected in source_semantic.items():
        actual = destination_semantic[name]
        fidelity[name] = {
            "expected_rows": expected["rows"],
            "destination_rows": actual["rows"],
            "expected_digest": expected["digest"],
            "destination_digest": actual["digest"],
            "match": expected == actual,
            "classification": _semantic_classification(
                name,
                source_semantic_rows.get(name, []),
                destination_semantic_rows[name],
                alias_audit,
                detail_rows,
                source_identity_ids.get(name),
            ),
        }

    return {
        "counts": counts,
        "financial": {
            "import_contract": source_report["financial"]["import_contract"],
            "pending_receivable_rows": payment_status_counts.get("pending", 0),
            "paid_rows": payment_status_counts.get("paid", 0),
            "payments_with_allocations": sum(
                row.id in allocation_payment_ids for row in payments
            ),
            "legacy_paid_without_allocations": legacy_paid_without_allocations,
        },
        "semantic": destination_semantic,
        "fidelity": fidelity,
        "alias_audit": alias_audit,
        "fidelity_note": (
            "Fidelity compares transformed semantic rows; source broken links remain under "
            "source.links and are not treated as destination fidelity."
        ),
        "load_counts": {
            "bitrix_companies": {
                "source_rows": source_records.get("bx_companies", 0),
                "destination_alias_rows": counts["counterparty_aliases_bitrix_companies"],
            },
            "bitrix_contacts": {
                "source_rows": source_records.get("bx_contacts", 0),
                "expected_import_rows": source_report["deduplication"]["bitrix_contacts"][
                    "unique_import_keys"
                ],
                "destination_rows": counts["contacts"],
                "deduplicated_source_rows": source_report["deduplication"]["bitrix_contacts"][
                    "deduplicated_rows"
                ],
            },
            "bitrix_deals": {
                "source_supported_rows": expected_deals,
                "destination_rows": counts["deals_bitrix_supported"],
            },
            "bitrix_leads": {
                "source_rows": source_records.get("bx_leads", 0),
                "destination_rows": counts["leads_bitrix"],
            },
            "bitrix_calls": {
                "source_rows": source_records.get("bx_calls", 0),
                "destination_rows": counts["calls_bitrix"],
            },
            "onec_sales": {
                "source_rows": source_records.get("onec_sales", 0),
                "destination_rows": counts["payments_onec"],
            },
            "onec_sku": {
                "source_rows": source_records.get("onec_sku", 0),
                "destination_rows": counts["skus"],
            },
        },
    }


async def reconcile() -> None:
    """Сверить локальный кэш с изолированной БД и вывести только агрегаты."""
    aggregate_path = _resolve_report_path("IMPORT_RECONCILE_REPORT")
    detail_path = _resolve_report_path("IMPORT_RECONCILE_DETAIL_REPORT")
    cache_dir = _require_isolated_load()
    _guard_report_paths(
        cache_dir,
        _isolated_database_path(),
        aggregate_path,
        detail_path,
    )
    detail_rows = [] if detail_path is not None else None
    source_report = _source_reconciliation(
        include_semantic_rows=True, detail_rows=detail_rows
    )
    source_semantic_rows = source_report.pop("_semantic_rows")
    source_identity_ids = source_report.pop("_source_identity_ids", {})
    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    try:
        destination_report = await _destination_reconciliation(
            db,
            source_report,
            source_semantic_rows,
            detail_rows,
            source_identity_ids,
        )
    finally:
        await db.disconnect()

    def gap_status(available: bool) -> str:
        return "present_not_imported" if available else "source_unavailable"

    report = {
        "schema": 1,
        "period": LABEL,
        "source": source_report,
        "destination": destination_report,
        "gaps": [
            {
                "area": "users",
                "status": "not_imported",
                "reason": "Bitrix users are used only to resolve owner text",
            },
            {
                "area": "deals",
                "status": "category_rows_skipped",
                "reason": "only Bitrix categories 0 and 7 are supported by this loader",
            },
            {
                "area": "stages",
                "status": "mapped_without_stage_rows",
                "reason": "Bitrix stage ids are mapped into Deal.stage; Stage rows are not created",
            },
            {
                "area": "payments",
                "status": "pending_reconciliation",
                "reason": "Posted 1C realization documents are receivables, not bank confirmations",
            },
            {
                "area": "activities",
                "status": gap_status(source_report["activities"]["dedicated_source_available"]),
                "reason": (
                    "dedicated activity/message/note cache is available but this loader imports "
                    "calls only as CallLog"
                    if source_report["activities"]["dedicated_source_available"]
                    else "no dedicated activity/message/note cache; calls are loaded as CallLog"
                ),
            },
            {
                "area": "files",
                "status": gap_status(source_report["files"]["dedicated_source_available"]),
                "reason": (
                    "file cache is available but this loader does not import binary files"
                    if source_report["files"]["dedicated_source_available"]
                    else "no file cache; call recording metadata is not a downloaded file"
                ),
            },
            {
                "area": "history",
                "status": gap_status(source_report["history"]["dedicated_source_available"]),
                "reason": (
                    "history cache is available but no timeline or stage events are imported"
                    if source_report["history"]["dedicated_source_available"]
                    else "no timeline or stage history cache; no DealStageEvent rows are created"
                ),
            },
            {
                "area": "bitrix_products",
                "status": gap_status(source_report["products"]["bitrix_product_rows_available"]),
                "reason": (
                    "Bitrix product rows are present but this loader imports 1C SKU separately"
                    if source_report["products"]["bitrix_product_rows_available"]
                    else "crm.deal.productrows was not exported; 1C SKU is imported separately"
                ),
            },
        ],
    }
    if destination_report["counts"]["deal_counterparty_ambiguous_names"]:
        report["gaps"].append({
            "area": "deal_counterparty_identity",
            "status": "ambiguous_name_blocker",
            "count": destination_report["counts"]["deal_counterparty_ambiguous_names"],
            "deals": destination_report["counts"]["deals_with_ambiguous_counterparty_name"],
            "reason": (
                "Deal stores counterparty as text; distinct masters with the same name "
                "remain ambiguous until a counterparty_id link is introduced"
            ),
        })
    if aggregate_path is not None:
        aggregate_path.parent.mkdir(parents=True, exist_ok=True)
        aggregate_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if detail_path is not None:
        details = sorted(
            detail_rows or [],
            key=lambda row: (
                str(row.get("dataset", "")),
                str(row.get("kind", "")),
                str(row.get("source_id", "")),
                str(row.get("identity", "")),
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=_semantic_value),
            ),
        )
        private_report = {
            "schema": 1,
            "period": LABEL,
            "aggregate": report,
            "rows": details,
        }
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(
            json.dumps(
                private_report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=_semantic_value,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


async def verify() -> None:
    _require_isolated_load()
    from sqlalchemy import func as sa_func

    from core.domain.models import Contact, Counterparty, Sku
    from modules.finance.models import Payment
    from modules.leads.models import Lead
    from modules.sales.models import CallLog, Deal

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    async with db.session_factory() as s:
        for label, model in (("контрагенты", Counterparty), ("контакты", Contact),
                             ("SKU", Sku), ("сделки", Deal), ("лиды", Lead),
                             ("звонки", CallLog), ("платежи", Payment)):
            n = (await s.execute(select(sa_func.count()).select_from(model))).scalar()
            print(f"verify: {label} — {n}")
        total = (await s.execute(
            select(sa_func.coalesce(sa_func.sum(Payment.amount), 0))
            .where(Payment.kind == "receivable"))).scalar()
        print(f"verify: выручка (receivable, BYN) — {total}")
    await db.disconnect()


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.chdir(PROJECT_ROOT)
    # ``all`` contains extraction: reject an unsafe load configuration before any
    # Bitrix/1C request can be made, while keeping extraction-only CLI available.
    if phase in ("all", "load", "load-onec", "load-prices", "verify", "reconcile"):
        _require_isolated_load()
    if phase in ("extract", "all"):
        extract()
    if phase == "extract-onec":
        extract_onec()
    if phase in ("load", "all"):
        asyncio.run(load())
    if phase == "load-onec":
        asyncio.run(load_onec())
    if phase == "load-prices":
        asyncio.run(load_prices())
    if phase == "reconcile":
        asyncio.run(reconcile())
    if phase in ("verify", "all"):
        asyncio.run(verify())
