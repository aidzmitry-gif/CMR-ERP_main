"""Импорт реальных данных за месяц из Bitrix24 и 1С в ERP (для сквозной проверки).

Период задаётся env (по умолчанию ноябрь 2024):
  IMPORT_FROM=2025-12-01T00:00:00 IMPORT_TO=2026-01-01T00:00:00

Двухфазный ETL с файловым кэшем в data/import_<YYYY-MM>/ (повторный прогон безопасен):
  python scripts/import_month.py extract      # Bitrix REST + 1C OData -> jsonl-кэш
  python scripts/import_month.py extract-onec # только 1С (без Bitrix) — товары/цены
  python scripts/import_month.py extract-onec-purchases # сырые закупочные документы 1С -> кэш, без записи в ERP
  # IMPORT_ONEC_PURCHASE_ENTITY задаётся точным Document_* из метаданных OData выбранной базы 1С.
  python scripts/import_month.py map-onec-purchases # полный пакет черновиков закупок по явной карте справочников
  # IMPORT_ONEC_PURCHASE_MAPPING — абсолютный путь к JSON; импортёр только готовит payload существующей накладной закупки.
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
import re
import stat
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

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


def onec_get(path: str, params: dict | None = None, *, parse_float=None) -> dict:
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
        json_options = {"parse_float": parse_float} if parse_float is not None else {}
        return resp.json(**json_options)
    raise RuntimeError(f"1C {path}: исчерпаны ретраи")


def onec_date_at(entity: str, skip: int, *, parse_float=None) -> str | None:
    """Date документа на позиции skip при сортировке по Date (для бинарного поиска)."""
    params = {"$orderby": "Date", "$top": 1, "$skip": skip, "$select": "Date"}
    rows = (onec_get(entity, params, parse_float=parse_float) if parse_float is not None
            else onec_get(entity, params)).get("value", [])
    return rows[0]["Date"] if rows else None


def onec_window(entity: str, date_from: str, date_to: str, *, parse_float=None) -> list[dict]:
    """Все документы entity с date_from <= Date < date_to ($filter недоступен — окно по $skip)."""
    # верхняя граница числа документов — удвоение skip до пустой страницы
    hi = 1
    while onec_date_at(entity, hi, parse_float=parse_float) is not None:
        hi *= 2
    # левая граница окна: первый индекс с Date >= date_from
    lo, r = 0, hi
    while lo < r:
        mid = (lo + r) // 2
        d = onec_date_at(entity, mid, parse_float=parse_float)
        if d is None or d >= date_from:
            r = mid
        else:
            lo = mid + 1
    # постраничный проход до выхода за date_to (документы целиком, с табличными частями)
    docs: list[dict] = []
    skip = lo
    while True:
        params = {"$orderby": "Date", "$top": 200, "$skip": skip}
        rows = (onec_get(entity, params, parse_float=parse_float) if parse_float is not None
                else onec_get(entity, params)).get("value", [])
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
    _verify_private_cache(cache_dir)
    return cache_dir


@dataclass(frozen=True, slots=True)
class _PrivateCacheSnapshot:
    """Immutable digests captured by the isolated-load gate for one operation."""

    cache_dir: Path
    cache_format: str
    entries: Mapping[str, tuple[int, int, str]]
    comment_binary_bytes: int = 0


def _require_isolated_cache_snapshot() -> _PrivateCacheSnapshot | None:
    """Run the isolated-cache gate and retain its initial per-operation digests."""
    cache_dir = _load_cache_dir()
    if os.getenv("AIOS_ENVIRONMENT", "").strip().lower() != "dev":
        raise RuntimeError("load-only разрешён только при AIOS_ENVIRONMENT=dev")
    _isolated_database_path()
    return _verify_private_cache(cache_dir)


_PRIVATE_CACHE_V1_GROUPS = {
    "bx_deals", "bx_contacts", "bx_leads", "bx_calls", "bx_users",
    "bx_companies", "bx_requisites", "onec_counterparties", "onec_sku",
    "bx_product_rows", "bx_products", "bx_stage_history", "bx_timeline_comments",
}
_PRIVATE_CACHE_V2_GROUPS = _PRIVATE_CACHE_V1_GROUPS | {
    "bx_comment_binary_links", "bx_comment_binary_inventory",
}
_PRIVATE_CACHE_V3_GROUPS = _PRIVATE_CACHE_V2_GROUPS | {
    "bx_call_binary_links", "bx_call_binary_inventory",
}
_PRIVATE_CACHE_V2_FORMAT = "CRM-LIVE-001-private-cache-v2"
_PRIVATE_CACHE_V3_FORMAT = "CRM-LIVE-001-private-cache-v3"
_MAX_PRIVATE_ATTACHMENT_BYTES = 2 * 1024 * 1024 * 1024
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _json_object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _private_cache_format(cache_dir: Path) -> str | None:
    manifest_path = cache_dir / "private-source-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        manifest = json.loads(
            manifest_path.read_bytes(), object_pairs_hook=_json_object_without_duplicate_keys
        )
    except (OSError, TypeError, ValueError, UnicodeError):
        return None
    return manifest.get("format") if isinstance(manifest, dict) else None


def _private_jsonl_rows(cache_dir: Path, name: str) -> list[dict]:
    rows = []
    path = cache_dir / f"{name}.jsonl"
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                raise ValueError("invalid private cache row")
            row = json.loads(line, object_pairs_hook=_json_object_without_duplicate_keys)
            if not isinstance(row, dict):
                raise ValueError("invalid private cache row")
            rows.append(row)
    return rows


def _check_private_binary_tree(folder: Path, expected_names: set[str]) -> None:
    """Recheck directory membership after reading bytes to catch late additions."""
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("invalid private binary directory")
    actual_names: set[str] = set()
    for path in folder.iterdir():
        if (path.is_symlink() or not path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}\.bin", path.name)):
            raise ValueError("invalid private binary file")
        actual_names.add(path.name)
    if actual_names != expected_names:
        raise ValueError("private binary inventory mismatch")


def _verify_private_comment_binary_files(
    cache_dir: Path, manifest: dict,
    cache_snapshot: _PrivateCacheSnapshot | None = None,
) -> None:
    """Verify the exact v2 file tree and its bounded inventory before database access."""
    try:
        inventory_rows = (
            _load_jsonl("bx_comment_binary_inventory", cache_snapshot)
            if cache_snapshot is not None
            else _private_jsonl_rows(cache_dir, "bx_comment_binary_inventory")
        )
        link_rows = (
            _load_jsonl("bx_comment_binary_links", cache_snapshot)
            if cache_snapshot is not None
            else _private_jsonl_rows(cache_dir, "bx_comment_binary_links")
        )
        inventory: dict[str, dict] = {}
        filenames: set[str] = set()
        for row in inventory_rows:
            if set(row) != {"key", "filename", "bytes", "sha256", "content_type", "name"}:
                raise ValueError("invalid binary inventory")
            key = row.get("key")
            if not isinstance(key, str) or not re.fullmatch(r"disk:[1-9][0-9]*", key):
                raise ValueError("invalid binary inventory")
            filename = row.get("filename")
            expected_filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
            size = row.get("bytes")
            digest = row.get("sha256")
            content_type = row.get("content_type")
            name = row.get("name")
            if (
                key in inventory
                or not isinstance(filename, str)
                or filename != expected_filename
                or filename in filenames
                or type(size) is not int
                or not 0 <= size <= _MAX_PRIVATE_ATTACHMENT_BYTES
                or not isinstance(digest, str)
                or not _SHA256_HEX_RE.fullmatch(digest)
                or not isinstance(content_type, str)
                or len(content_type) > 255
                or (name is not None and (not isinstance(name, str) or len(name) > 512))
            ):
                raise ValueError("invalid binary inventory")
            inventory[key] = row
            filenames.add(filename)

        for row in link_rows:
            if set(row) != {
                "source", "entity_type", "entity_id", "source_id", "file_id", "binary_key"
            }:
                raise ValueError("invalid binary link")
            if (
                row.get("source") != "comment"
                or row.get("entity_type") != "deal"
                or not isinstance(row.get("entity_id"), str)
                or not isinstance(row.get("source_id"), str)
                or not isinstance(row.get("file_id"), str)
                or row.get("binary_key") != "disk:" + row["file_id"]
            ):
                raise ValueError("invalid binary link")

        folder = cache_dir / "comment_binary_files"
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("invalid binary files directory")
        actual_names: set[str] = set()
        total_bytes = 0
        fingerprint = hashlib.sha256()
        for path in folder.iterdir():
            if (
                path.is_symlink()
                or not path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}\.bin", path.name)
            ):
                raise ValueError("invalid binary file")
            actual_names.add(path.name)
        if actual_names != filenames:
            raise ValueError("binary inventory mismatch")
        for row in sorted(inventory.values(), key=lambda item: item["filename"]):
            path = folder / row["filename"]
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > row["bytes"]:
                        raise ValueError("binary size mismatch")
                    digest.update(chunk)
            if size != row["bytes"] or digest.hexdigest() != row["sha256"]:
                raise ValueError("binary digest mismatch")
            total_bytes += size
            fingerprint.update(
                f"{row['filename']}:{size}:{digest.hexdigest()}\n".encode("ascii")
            )
        summary = manifest["comment_binary_files"]
        if (
            not isinstance(summary, dict)
            or set(summary) != {"records", "bytes", "sha256"}
            or type(summary.get("records")) is not int
            or summary["records"] != len(inventory)
            or type(summary.get("bytes")) is not int
            or summary["bytes"] != total_bytes
            or summary.get("sha256") != fingerprint.hexdigest()
        ):
            raise ValueError("binary manifest mismatch")
        # The inventory and selected links are exact subsets, not a place for
        # unattached binaries or links to files not covered by the inventory.
        if any(row["binary_key"] not in inventory for row in link_rows):
            raise ValueError("binary link mismatch")
        linked_keys = {row["binary_key"] for row in link_rows}
        if linked_keys != set(inventory):
            raise ValueError("binary inventory mismatch")
        if cache_snapshot is not None:
            _check_private_binary_tree(folder, filenames)
    except (OSError, KeyError, TypeError, ValueError, UnicodeError):
        raise RuntimeError("PRIVATE_CACHE_CHANGED") from None


def _verify_private_call_binary_files(
    cache_dir: Path, manifest: dict, cache_snapshot: _PrivateCacheSnapshot,
) -> int:
    """Verify v3 call links against source rows and the exact local binary tree."""
    try:
        call_rows = _load_jsonl("bx_calls", cache_snapshot)
        source_calls: dict[str, tuple[str, str, str, str, str]] = {}
        calls_requiring_recording: set[str] = set()

        def optional_id(value: object) -> str:
            if value is None or value == "":
                return ""
            candidate = str(value)
            if (not candidate.isascii() or not candidate.isdigit()
                    or int(candidate) < 1):
                raise ValueError("invalid call identity")
            return candidate

        def identity_text(value: object) -> str:
            if value is None or value == "":
                return ""
            if (not isinstance(value, str) or value != value.strip()
                    or len(value) > 64
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError("invalid call identity")
            return value

        for row in call_rows:
            if "CALL_RECORD_URL" in row:
                raise ValueError("source call URL must not be cached")
            source_id = _canonical_positive_id(row.get("ID"))
            if len(source_id) > 20 or source_id in source_calls:
                raise ValueError("invalid source call ID")
            call_id = _canonical_bitrix_call_id(row)
            record_file_id = optional_id(row.get("RECORD_FILE_ID"))
            identity = (
                call_id,
                record_file_id,
                identity_text(row.get("CRM_ENTITY_TYPE")),
                optional_id(row.get("CRM_ENTITY_ID")),
                optional_id(row.get("PORTAL_USER_ID")),
            )
            source_calls[source_id] = identity
            if record_file_id:
                calls_requiring_recording.add(source_id)

        inventory_rows = _load_jsonl("bx_call_binary_inventory", cache_snapshot)
        link_rows = _load_jsonl("bx_call_binary_links", cache_snapshot)
        inventory: dict[str, dict] = {}
        filenames: set[str] = set()
        for row in inventory_rows:
            if set(row) != {"key", "filename", "bytes", "sha256", "content_type"}:
                raise ValueError("invalid call binary inventory")
            key = row.get("key")
            if not isinstance(key, str) or not re.fullmatch(r"call:[1-9][0-9]*", key):
                raise ValueError("invalid call binary inventory")
            filename = row.get("filename")
            expected_filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
            size = row.get("bytes")
            digest = row.get("sha256")
            content_type = row.get("content_type")
            if (
                key in inventory
                or not isinstance(filename, str)
                or filename != expected_filename
                or filename in filenames
                or type(size) is not int
                or not 0 <= size <= _MAX_PRIVATE_ATTACHMENT_BYTES
                or not isinstance(digest, str)
                or not _SHA256_HEX_RE.fullmatch(digest)
                or not isinstance(content_type, str)
                or len(content_type) > 255
            ):
                raise ValueError("invalid call binary inventory")
            inventory[key] = row
            filenames.add(filename)

        linked_call_ids: set[str] = set()
        for row in link_rows:
            if set(row) != {
                "source", "source_id", "call_id", "record_file_id", "entity_type",
                "entity_id", "portal_user_id", "binary_key",
            }:
                raise ValueError("invalid call binary link")
            source_id = row.get("source_id")
            if (row.get("source") != "call" or not isinstance(source_id, str)
                    or not re.fullmatch(r"[1-9][0-9]{0,19}", source_id)
                    or source_id in linked_call_ids):
                raise ValueError("invalid call binary link")
            expected_identity = source_calls.get(source_id)
            expected_key = "call:" + source_id
            actual_identity = (
                row.get("call_id"), row.get("record_file_id"), row.get("entity_type"),
                row.get("entity_id"), row.get("portal_user_id"),
            )
            if (expected_identity is None or actual_identity != expected_identity
                    or row.get("binary_key") != expected_key
                    or expected_key not in inventory):
                raise ValueError("call binary link mismatch")
            linked_call_ids.add(source_id)

        if (not linked_call_ids or not calls_requiring_recording.issubset(linked_call_ids)
                or {row["binary_key"] for row in link_rows} != set(inventory)):
            raise ValueError("call binary inventory mismatch")

        folder = cache_dir / "call_binary_files"
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("invalid call binary files directory")
        actual_names: set[str] = set()
        for path in folder.iterdir():
            if (path.is_symlink() or not path.is_file()
                    or not re.fullmatch(r"[0-9a-f]{64}\.bin", path.name)):
                raise ValueError("invalid call binary file")
            actual_names.add(path.name)
        if actual_names != filenames:
            raise ValueError("call binary inventory mismatch")

        total_bytes = 0
        fingerprint = hashlib.sha256()
        for row in sorted(inventory.values(), key=lambda item: item["filename"]):
            path = folder / row["filename"]
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > row["bytes"] or size > _MAX_PRIVATE_ATTACHMENT_BYTES:
                        raise ValueError("call binary size mismatch")
                    digest.update(chunk)
            if size != row["bytes"] or digest.hexdigest() != row["sha256"]:
                raise ValueError("call binary digest mismatch")
            total_bytes += size
            fingerprint.update(
                f"{row['filename']}:{size}:{digest.hexdigest()}\n".encode("ascii")
            )

        summary = manifest["call_binary_files"]
        if (
            not isinstance(summary, dict)
            or set(summary) != {"records", "bytes", "sha256"}
            or type(summary.get("records")) is not int
            or summary["records"] != len(inventory)
            or type(summary.get("bytes")) is not int
            or summary["bytes"] != total_bytes
            or summary.get("sha256") != fingerprint.hexdigest()
        ):
            raise ValueError("call binary manifest mismatch")
        _check_private_binary_tree(folder, filenames)
        return len(link_rows)
    except (OSError, KeyError, TypeError, ValueError, UnicodeError):
        raise RuntimeError("PRIVATE_CACHE_CHANGED") from None


def _verify_private_cache(cache_dir: Path) -> _PrivateCacheSnapshot | None:
    """Reject incomplete or unsupported private source caches before DB writes."""
    if (cache_dir / "PRIVATE_CACHE_INCOMPLETE").exists():
        raise RuntimeError("PRIVATE_CACHE_INCOMPLETE")
    marker = cache_dir / "PRIVATE_CACHE_FORMAT"
    manifest_path = cache_dir / "private-source-manifest.json"
    if marker.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError("PRIVATE_CACHE_CHANGED")
    if marker.exists() != manifest_path.exists():
        raise RuntimeError("PRIVATE_CACHE_CHANGED")
    if not manifest_path.exists():
        if any(
            path.exists() or path.is_symlink()
            for path in (
                cache_dir / "comment_binary_files",
                cache_dir / "bx_comment_binary_links.jsonl",
                cache_dir / "bx_comment_binary_inventory.jsonl",
                cache_dir / "call_binary_files",
                cache_dir / "bx_call_binary_links.jsonl",
                cache_dir / "bx_call_binary_inventory.jsonl",
            )
        ):
            raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        return None  # Historical isolated test caches have no private source manifest.
    if marker.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError("PRIVATE_CACHE_CHANGED")
    try:
        manifest_body = manifest_path.read_bytes()
        manifest = json.loads(
            manifest_body, object_pairs_hook=_json_object_without_duplicate_keys
        )
        if not isinstance(manifest, dict):
            raise RuntimeError("PRIVATE_CACHE_CHANGED")
        cache_format = manifest.get("format")
        if cache_format not in {
            "CRM-LIVE-001-private-cache-v1", _PRIVATE_CACHE_V2_FORMAT,
            _PRIVATE_CACHE_V3_FORMAT,
        }:
            raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        expected_marker = cache_format + ":" + hashlib.sha256(manifest_body).hexdigest() + "\n"
        if marker.read_text(encoding="ascii") != expected_marker:
            raise RuntimeError("PRIVATE_CACHE_CHANGED")
        entries = manifest["cache"]
        expected_groups = {
            "CRM-LIVE-001-private-cache-v1": _PRIVATE_CACHE_V1_GROUPS,
            _PRIVATE_CACHE_V2_FORMAT: _PRIVATE_CACHE_V2_GROUPS,
            _PRIVATE_CACHE_V3_FORMAT: _PRIVATE_CACHE_V3_GROUPS,
        }[cache_format]
        base_manifest_keys = {
            "format", "cache", "ready_for_load", "blocked_source_groups",
        }
        if cache_format == _PRIVATE_CACHE_V2_FORMAT:
            valid_manifest_keys = {
                frozenset(base_manifest_keys | {"source_manifests", "comment_binary_files"})
            }
        elif cache_format == _PRIVATE_CACHE_V3_FORMAT:
            valid_manifest_keys = {
                frozenset(base_manifest_keys | {
                    "source_manifests", "comment_binary_files", "call_binary_files",
                })
            }
        else:
            valid_manifest_keys = {
                frozenset(base_manifest_keys),
                frozenset(base_manifest_keys | {"source_manifests"}),
            }
        allowed_group_sets = {
            frozenset(expected_groups), frozenset(expected_groups | {"bx_tasks"}),
        }
        if (frozenset(manifest) not in valid_manifest_keys
                or (cache_format != _PRIVATE_CACHE_V3_FORMAT
                    and (manifest["ready_for_load"] is not True
                         or manifest["blocked_source_groups"] != {}))
                or not isinstance(entries, dict)
                or frozenset(entries) not in allowed_group_sets
                or {path.stem for path in cache_dir.glob("*.jsonl")} != set(entries)):
            raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        if (
            cache_format not in {_PRIVATE_CACHE_V2_FORMAT, _PRIVATE_CACHE_V3_FORMAT}
            and ((cache_dir / "comment_binary_files").exists()
                 or (cache_dir / "comment_binary_files").is_symlink()
                 or (cache_dir / "call_binary_files").exists()
                 or (cache_dir / "call_binary_files").is_symlink())
        ):
            raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        if cache_format in {_PRIVATE_CACHE_V2_FORMAT, _PRIVATE_CACHE_V3_FORMAT}:
            expected_paths = (
                {"PRIVATE_CACHE_FORMAT", "private-source-manifest.json",
                 "comment_binary_files"}
                | {f"{name}.jsonl" for name in entries}
            )
            if cache_format == _PRIVATE_CACHE_V3_FORMAT:
                expected_paths.add("call_binary_files")
            source_manifests = manifest["source_manifests"]
            if (
                not isinstance(source_manifests, dict)
                or set(source_manifests) != {"bitrix", "onec", "binary"}
                or any(
                    not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value)
                    for value in source_manifests.values()
                )
                or {path.name for path in cache_dir.iterdir()}
                != expected_paths
            ):
                raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        elif "source_manifests" in manifest:
            source_manifests = manifest["source_manifests"]
            if (
                not isinstance(source_manifests, dict)
                or set(source_manifests) != {"bitrix", "onec"}
                or any(
                    not isinstance(value, str) or not _SHA256_HEX_RE.fullmatch(value)
                    for value in source_manifests.values()
                )
            ):
                raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
        verified_entries: dict[str, tuple[int, int, str]] = {}
        for name, expected in entries.items():
            if not isinstance(expected, dict):
                raise RuntimeError("PRIVATE_CACHE_CHANGED")
            path = cache_dir / f"{name}.jsonl"
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("PRIVATE_CACHE_CHANGED")
            digest = hashlib.sha256()
            size = count = 0
            with path.open("rb") as stream:
                for line in stream:
                    digest.update(line)
                    size += len(line)
                    count += 1
            if (type(expected.get("records")) is not int or count != expected["records"]
                    or type(expected.get("bytes")) is not int or size != expected["bytes"]
                    or not isinstance(expected.get("sha256"), str)
                    or digest.hexdigest() != expected["sha256"]):
                raise RuntimeError("PRIVATE_CACHE_CHANGED")
            verified_entries[name] = (
                expected["records"], expected["bytes"], expected["sha256"]
            )
        cache_snapshot = _PrivateCacheSnapshot(
            cache_dir=cache_dir,
            cache_format=cache_format,
            entries=MappingProxyType(verified_entries),
            comment_binary_bytes=(
                manifest["comment_binary_files"]["bytes"]
                if cache_format == _PRIVATE_CACHE_V2_FORMAT else 0
            ),
        )
        if cache_format in {_PRIVATE_CACHE_V2_FORMAT, _PRIVATE_CACHE_V3_FORMAT}:
            _verify_private_comment_binary_files(
                cache_dir, manifest,
                cache_snapshot if cache_format == _PRIVATE_CACHE_V3_FORMAT else None,
            )
        if cache_format == _PRIVATE_CACHE_V3_FORMAT:
            linked_call_count = _verify_private_call_binary_files(
                cache_dir, manifest, cache_snapshot,
            )
            blocked_groups = manifest.get("blocked_source_groups")
            if (
                manifest.get("ready_for_load") is not False
                or not isinstance(blocked_groups, dict)
                or type(blocked_groups.get("call_recordings")) is not int
                or blocked_groups["call_recordings"] != linked_call_count
                or any(
                    not isinstance(name, str) or not name
                    or type(count) is not int or count < 1
                    for name, count in blocked_groups.items()
                )
            ):
                raise RuntimeError("PRIVATE_CACHE_NOT_LOADABLE")
            root_paths = list(cache_dir.iterdir())
            if ({path.name for path in root_paths} != expected_paths
                    or any(path.is_symlink() for path in root_paths)):
                raise RuntimeError("PRIVATE_CACHE_CHANGED")
            # V3 binaries are now verified, but there is no CallRecording importer yet.
            raise RuntimeError("BITRIX_CALL_RECORDINGS_UNSUPPORTED")
        return cache_snapshot
    except RuntimeError:
        raise
    except (OSError, KeyError, TypeError, ValueError):
        raise RuntimeError("PRIVATE_CACHE_CHANGED") from None


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


def _exact_json(value) -> str:
    """Serialize Decimal as an exact JSON number and reject binary floats."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RuntimeError("1C returned a non-finite decimal")
        return format(value, "f")
    if isinstance(value, float):
        raise RuntimeError("1C purchase response contains a binary float; exact decimal parsing is required")
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _exact_json(item)
            for key, item in value.items()
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_exact_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _dump_onec_purchase_cache(path: Path, rows: list[dict]) -> None:
    """Preserve OData decimal tokens exactly; never rewrite them through float."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(_exact_json(row) + "\n")


def _load_jsonl(
    name: str, cache_snapshot: _PrivateCacheSnapshot | None = None
) -> list[dict]:
    if cache_snapshot is None:
        path = OUT_DIR / f"{name}.jsonl"
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as stream:
            return [json.loads(line, parse_float=Decimal if name == "onec_purchases" else None) for line in stream if line.strip()]

    expected = cache_snapshot.entries.get(name)
    path = cache_snapshot.cache_dir / f"{name}.jsonl"
    if expected is None:
        if path.exists() or path.is_symlink():
            raise RuntimeError("PRIVATE_CACHE_CHANGED")
        return []
    if path.is_symlink():
        raise RuntimeError("PRIVATE_CACHE_CHANGED")

    expected_records, expected_bytes, expected_digest = expected
    digest = hashlib.sha256()
    size = 0
    rows = []
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("PRIVATE_CACHE_CHANGED")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            for line in stream:
                digest.update(line)
                size += len(line)
                if not line.strip():
                    raise RuntimeError("PRIVATE_CACHE_CHANGED")
                row = json.loads(
                    line, object_pairs_hook=_json_object_without_duplicate_keys,
                    parse_float=Decimal if name == "onec_purchases" else None
                )
                if not isinstance(row, dict):
                    raise RuntimeError("PRIVATE_CACHE_CHANGED")
                rows.append(row)
    except RuntimeError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise RuntimeError("PRIVATE_CACHE_CHANGED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if (
        len(rows) != expected_records
        or size != expected_bytes
        or digest.hexdigest() != expected_digest
    ):
        raise RuntimeError("PRIVATE_CACHE_CHANGED")
    return rows


def _nonempty_ids(rows: list[dict], field: str) -> set[str]:
    return {
        str(row[field])
        for row in rows
        if row.get(field) not in (None, "", "0")
    }


def _valid_unp(value: object) -> str | None:
    """Return a Belarusian UNP only when it is an unambiguous nine-digit key."""
    value = str(value or "").strip()
    return value if len(value) == 9 and value.isascii() and value.isdigit() else None


def _company_reference_ids(
    companies: list[dict],
    requisites: list[dict],
    referenced_company_ids: Iterable[object] = (),
) -> set[str]:
    values = [row.get("ID") for row in companies]
    values.extend(row.get("ENTITY_ID") for row in requisites)
    values.extend(referenced_company_ids or ())
    return {
        str(value).strip()
        for value in values
        if value not in (None, "", "0") and str(value).strip() not in ("", "0")
    }


def _deduplicate_source_deals(rows: list[dict]) -> tuple[list[dict], int, int, int]:
    """Keep one exact source row per ID; suppress conflicts and missing identities."""
    first_by_id: dict[str, dict] = {}
    conflicting_ids: set[str] = set()
    identical_duplicates = 0
    missing_ids = 0
    for row in rows:
        source_id = str(row.get("ID") or "").strip()
        if not source_id:
            missing_ids += 1
            continue
        first = first_by_id.get(source_id)
        if first is None:
            first_by_id[source_id] = row
        elif row == first:
            identical_duplicates += 1
        else:
            conflicting_ids.add(source_id)
    unique = [
        row for source_id, row in first_by_id.items()
        if source_id not in conflicting_ids
    ]
    return unique, identical_duplicates, len(conflicting_ids), missing_ids


_BITRIX_DEAL_ITEM_PREFIX = "bitrix:deal-product-row:"
_BITRIX_DEAL_ITEM_SOURCE_RE = re.compile(
    r"^bitrix:deal-product-row:([1-9][0-9]*):([1-9][0-9]*)$"
)
_DEAL_ITEM_MAX_QTY = Decimal("999999999999.99")


def _canonical_positive_id(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("invalid source identity")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError("invalid source identity")
    if not text.isascii() or not text.isdigit() or text.startswith("0"):
        raise ValueError("invalid source identity")
    return text


def _canonical_bitrix_call_id(row: dict) -> str:
    """Keep a source call key intact; use the numeric row ID only when absent."""
    raw = row.get("CALL_ID")
    if raw is None or raw == "":
        try:
            call_id = _canonical_positive_id(row.get("ID"))
        except ValueError:
            raise ValueError("BITRIX_CALL_ID_INVALID") from None
    elif isinstance(raw, str) and raw and raw == raw.strip() and not any(
        ord(char) < 32 or ord(char) == 127 for char in raw
    ):
        call_id = raw
    else:
        raise ValueError("BITRIX_CALL_ID_INVALID")
    if len(call_id) > 64:
        raise ValueError("BITRIX_CALL_ID_INVALID")
    return call_id


def _prepare_bitrix_call_deal_links(
    call_rows: list[dict], deal_rows: list[dict]
) -> dict[str, str | None]:
    """Resolve explicit call primary DEAL links to supported source deal numbers."""
    unique_deals, _, _, _ = _deduplicate_source_deals(deal_rows)
    deals_by_id: dict[str, dict] = {}
    for deal in unique_deals:
        try:
            deal_id = _canonical_positive_id(deal.get("ID"))
        except ValueError:
            continue
        deals_by_id[deal_id] = deal

    expected: dict[str, str | None] = {}
    for row in call_rows:
        if row.get("CALL_RECORD_URL") or row.get("RECORD_FILE_ID"):
            raise ValueError("BITRIX_CALL_RECORDINGS_UNSUPPORTED")
        call_id = _canonical_bitrix_call_id(row)
        if call_id in expected:
            raise ValueError("BITRIX_CALL_ID_INVALID")
        deal_number = None
        if row.get("CRM_ENTITY_TYPE") == "DEAL":
            try:
                deal_id = _canonical_positive_id(row.get("CRM_ENTITY_ID"))
            except ValueError:
                raise ValueError("BITRIX_CALL_DEAL_INVALID") from None
            deal = deals_by_id.get(deal_id)
            if deal is None:
                raise ValueError("BITRIX_CALL_DEAL_INVALID")
            raw_category = deal.get("CATEGORY_ID")
            if isinstance(raw_category, bool):
                raise ValueError("BITRIX_CALL_DEAL_INVALID")
            category = str(raw_category if raw_category not in (None, "") else "0")
            if category not in {"0", "7"}:
                raise ValueError("BITRIX_CALL_DEAL_INVALID")
            deal_number = f"BX-{deal_id}"
        expected[call_id] = deal_number
    return expected


def _onec_deletion_mark(value: object) -> bool:
    """Return whether an OData SKU is deleted; reject values with unknown meaning."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if not normalized or normalized in {"false", "0"}:
            return False
        if normalized in {"true", "1"}:
            return True
    raise ValueError("ONEC_SKU_IDENTITY_INVALID")


def _onec_ref_key_digest(ref_key: str) -> str:
    return hashlib.sha256(ref_key.encode("utf-8")).hexdigest()


def _onec_identity_digest_from_provenance(provenance: object) -> str | None:
    if not isinstance(provenance, dict):
        return None
    identity = provenance.get("onec_identity")
    if not isinstance(identity, dict) or identity.get("source") != "1c":
        return None
    digest = identity.get("ref_key_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return None
    return digest


def _prepare_onec_sku_catalog(
    rows: list[dict], *, strict: bool = True
) -> dict[str, object]:
    """Validate the complete 1C SKU identity catalog without exposing source keys."""
    stats = {
        "source_rows": len(rows),
        "active_rows": 0,
        "deleted_rows": 0,
        "unknown_deletion_mark_rows": 0,
        "invalid_identity_rows": 0,
        "duplicate_active_ref_groups": 0,
        "duplicate_active_code_groups": 0,
    }
    candidates: list[dict[str, object]] = []
    invalid = False
    for row in rows:
        if not isinstance(row, dict):
            stats["unknown_deletion_mark_rows"] += 1
            stats["invalid_identity_rows"] += 1
            invalid = True
            continue
        try:
            deleted = _onec_deletion_mark(row.get("DeletionMark"))
        except ValueError:
            stats["unknown_deletion_mark_rows"] += 1
            invalid = True
            continue
        if deleted:
            stats["deleted_rows"] += 1
            continue
        stats["active_rows"] += 1
        ref_key = row.get("Ref_Key")
        raw_code = row.get("Code")
        code = raw_code.strip() if isinstance(raw_code, str) else ""
        if (
            not isinstance(ref_key, str)
            or not ref_key
            or ref_key != ref_key.strip()
            or not code
        ):
            stats["invalid_identity_rows"] += 1
            invalid = True
            continue
        candidates.append({
            "row": row,
            "ref_key": ref_key,
            "code": code,
            "digest": _onec_ref_key_digest(ref_key),
        })

    ref_counts = Counter(str(item["ref_key"]) for item in candidates)
    code_counts = Counter(str(item["code"]) for item in candidates)
    stats["duplicate_active_ref_groups"] = sum(count > 1 for count in ref_counts.values())
    stats["duplicate_active_code_groups"] = sum(count > 1 for count in code_counts.values())
    if stats["duplicate_active_ref_groups"] or stats["duplicate_active_code_groups"]:
        invalid = True
    active_rows = [
        item for item in candidates
        if ref_counts[str(item["ref_key"])] == 1
        and code_counts[str(item["code"])] == 1
    ]
    if strict and invalid:
        raise ValueError("ONEC_SKU_IDENTITY_INVALID")
    return {
        "active_rows": active_rows,
        "stats": stats,
        "valid": not invalid,
    }


async def _validate_existing_onec_sku_identities(session, catalog: dict[str, object]) -> dict[str, object]:
    """Existing SKU codes may be reused only for the exact recorded 1C identity."""
    from core.domain.models import Sku

    entries = catalog["active_rows"]
    if not entries:
        return {"by_code": {}, "by_digest": {}}
    existing_rows = (await session.execute(select(Sku).with_for_update())).scalars().all()
    by_code = {row.code: row for row in existing_rows}
    by_digest: dict[str, list[Sku]] = {}
    for row in existing_rows:
        digest = _onec_identity_digest_from_provenance(row.provenance)
        if digest:
            by_digest.setdefault(digest, []).append(row)
    for entry in entries:
        code = entry["code"]
        digest = entry["digest"]
        existing = by_code.get(code)
        if existing is not None and (
            not existing.is_active
            or _onec_identity_digest_from_provenance(existing.provenance) != digest
        ):
            raise ValueError("ONEC_SKU_IDENTITY_CONFLICT")
        if any(row.code != code or not row.is_active for row in by_digest.get(digest, [])):
            raise ValueError("ONEC_SKU_IDENTITY_CONFLICT")
    return {"by_code": by_code, "by_digest": by_digest}


def _upsert_onec_sku_rows(session, catalog: dict[str, object], existing: dict, stats: dict) -> None:
    from core.domain.models import Sku

    for entry in catalog["active_rows"]:
        code = entry["code"]
        if code in existing["by_code"]:
            continue
        source_row = entry["row"]
        session.add(Sku(
            code=code,
            title=(source_row.get("Description") or code)[:255],
            provenance={
                "title": {"source": "1c", "at": LABEL},
                "onec_identity": {
                    "source": "1c",
                    "ref_key_sha256": entry["digest"],
                },
            },
        ))
        stats["sku"] = stats.get("sku", 0) + 1


def _deal_item_quantity(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("invalid product quantity")
    try:
        quantity = Decimal(str(value))
        quantized = quantity.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid product quantity") from None
    if (
        not quantity.is_finite()
        or quantity <= 0
        or quantity != quantized
        or quantized > _DEAL_ITEM_MAX_QTY
    ):
        raise ValueError("invalid product quantity")
    return quantized


def _prepare_bitrix_deal_items(
    deal_rows: list[dict],
    product_row_envelopes: list[dict],
    bitrix_products: list[dict],
    onec_sku_rows: list[dict],
    *,
    require_complete: bool = False,
) -> dict[str, object]:
    """Validate source ownership and resolve Bitrix rows through exact 1C keys."""
    invalid = ValueError("BITRIX_PRODUCT_ROWS_INVALID")
    try:
        onec_catalog = _prepare_onec_sku_catalog(onec_sku_rows)
    except ValueError:
        raise invalid from None
    deals_by_id: dict[str, dict] = {}
    expected_deal_ids: set[str] = set()
    ambiguous_deal_ids: set[str] = set()
    for row in deal_rows:
        if not isinstance(row, dict):
            if require_complete:
                raise invalid
            continue
        try:
            deal_id = _canonical_positive_id(row.get("ID"))
        except ValueError:
            if require_complete:
                raise invalid from None
            continue
        if deal_id in deals_by_id:
            if require_complete:
                raise invalid
            ambiguous_deal_ids.add(deal_id)
            continue
        deals_by_id[deal_id] = row
        expected_deal_ids.add(deal_id)

    envelopes_by_deal: dict[str, list[dict]] = {}
    for envelope in product_row_envelopes:
        if not isinstance(envelope, dict) or not isinstance(envelope.get("rows"), list):
            raise invalid
        try:
            deal_id = _canonical_positive_id(envelope.get("deal_id"))
        except ValueError:
            raise invalid from None
        if (
            deal_id in envelopes_by_deal
            or deal_id not in deals_by_id
            or deal_id in ambiguous_deal_ids
        ):
            raise invalid
        envelopes_by_deal[deal_id] = envelope["rows"]

    if require_complete and set(envelopes_by_deal) != expected_deal_ids:
        raise invalid

    deal_items: list[dict] = []
    supported_deal_ids: set[str] = set()
    source_row_ids: set[str] = set()
    for deal_id, rows in envelopes_by_deal.items():
        deal = deals_by_id[deal_id]
        category = str(deal.get("CATEGORY_ID") or "0")
        if rows and category not in ("0", "7"):
            raise invalid
        if category in ("0", "7"):
            supported_deal_ids.add(deal_id)
        for row in rows:
            if not isinstance(row, dict):
                raise invalid
            try:
                row_id = _canonical_positive_id(row.get("ID"))
                product_id = _canonical_positive_id(row.get("PRODUCT_ID"))
            except ValueError:
                raise invalid from None
            if row_id in source_row_ids:
                raise invalid
            source_row_ids.add(row_id)
            if "OWNER_ID" in row:
                try:
                    if _canonical_positive_id(row["OWNER_ID"]) != deal_id:
                        raise invalid
                except ValueError:
                    raise invalid from None
            if "OWNER_TYPE" in row and row["OWNER_TYPE"] != "D":
                raise invalid
            try:
                quantity = _deal_item_quantity(row.get("QUANTITY"))
            except ValueError:
                raise invalid from None
            source_ref = f"{_BITRIX_DEAL_ITEM_PREFIX}{deal_id}:{row_id}"
            if len(source_ref) > 128:
                raise invalid
            deal_items.append({
                "deal_id": deal_id,
                "number": f"BX-{deal_id}",
                "row_id": row_id,
                "product_id": product_id,
                "source_ref": source_ref,
                "quantity": quantity,
            })

    if not deal_items:
        return {
            "deal_ids": supported_deal_ids,
            "scope_deal_ids": set(envelopes_by_deal),
            "items": deal_items,
        }

    products_by_id: dict[str, dict] = {}
    for product in bitrix_products:
        if not isinstance(product, dict):
            raise invalid
        try:
            product_id = _canonical_positive_id(product.get("ID"))
        except ValueError:
            raise invalid from None
        if product_id in products_by_id:
            raise invalid
        products_by_id[product_id] = product

    onec_by_ref = {
        str(entry["ref_key"]): entry for entry in onec_catalog["active_rows"]
    }

    for item in deal_items:
        product = products_by_id.get(item["product_id"])
        if product is None:
            raise invalid
        ref = product.get("XML_ID")
        if not isinstance(ref, str) or not ref or ref != ref.strip():
            raise invalid
        onec_entry = onec_by_ref.get(ref)
        if onec_entry is None:
            raise invalid
        item["sku_code"] = onec_entry["code"]
        item["sku_identity_digest"] = onec_entry["digest"]

    return {
        "deal_ids": supported_deal_ids,
        "scope_deal_ids": set(envelopes_by_deal),
        "items": deal_items,
    }


async def _validate_existing_bitrix_deal_item_rows(
    session, prepared: dict[str, object]
) -> None:
    """Fail before writes when scoped imported lines are stale or semantically changed."""
    from core.domain.models import Sku
    from modules.sales.models import Deal, DealItem

    source_scope_ids = prepared.get("scope_deal_ids", prepared["deal_ids"])
    if not source_scope_ids:
        return
    source_scope_numbers = {f"BX-{deal_id}" for deal_id in source_scope_ids}
    expected_by_ref = {item["source_ref"]: item for item in prepared["items"]}
    imported_rows = (await session.execute(
        select(
            DealItem,
            Deal.number,
            Sku.code,
            Sku.provenance,
            Sku.is_active,
        )
        .join(Deal, Deal.id == DealItem.deal_id)
        .outerjoin(Sku, Sku.id == DealItem.sku_id)
        .where(DealItem.source_ref.like(f"{_BITRIX_DEAL_ITEM_PREFIX}%"))
        .with_for_update()
    )).all()
    for item, owner_number, sku_code, sku_provenance, sku_is_active in imported_rows:
        source_ref = item.source_ref or ""
        match = _BITRIX_DEAL_ITEM_SOURCE_RE.fullmatch(source_ref)
        owner_matches_scope = owner_number in source_scope_numbers
        source_matches_scope = bool(
            match and match.group(1) in source_scope_ids
        )
        if not owner_matches_scope and not source_matches_scope:
            continue
        expected = expected_by_ref.get(source_ref)
        if (
            expected is None
            or owner_number != expected["number"]
            or sku_code != expected["sku_code"]
            or _onec_identity_digest_from_provenance(sku_provenance)
            != expected["sku_identity_digest"]
            or not sku_is_active
            or item.qty != expected["quantity"]
            or item.unit_price is not None
        ):
            raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")


async def _import_bitrix_deal_items(session, prepared: dict[str, object], stats: dict) -> None:
    from core.domain.models import Sku
    from modules.sales.models import Deal, DealItem

    deal_ids = prepared["deal_ids"]
    items = prepared["items"]
    await _validate_existing_bitrix_deal_item_rows(session, prepared)
    if not deal_ids:
        return

    numbers = {f"BX-{deal_id}" for deal_id in deal_ids}
    deals = (
        await session.execute(
            select(Deal).where(Deal.number.in_(numbers)).order_by(Deal.id).with_for_update()
        )
    ).scalars().all()
    deals_by_number: dict[str, Deal] = {}
    for deal in deals:
        if deal.number in deals_by_number:
            raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")
        deals_by_number[deal.number] = deal
    if set(deals_by_number) != numbers:
        raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")

    codes = {item["sku_code"] for item in items}
    sku_rows = (
        await session.execute(select(Sku).where(Sku.code.in_(codes)).with_for_update())
    ).scalars().all() if codes else []
    skus_by_code = {row.code: row for row in sku_rows}
    if set(skus_by_code) != codes:
        raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")

    external_deal_by_id = {deal.id: deal.number.removeprefix("BX-") for deal in deals}
    expected_by_ref: dict[str, dict] = {}
    expected_skus_by_deal: dict[int, set[int]] = {}
    for item in items:
        deal = deals_by_number[item["number"]]
        item["db_deal_id"] = deal.id
        sku = skus_by_code[item["sku_code"]]
        if (
            not sku.is_active
            or _onec_identity_digest_from_provenance(sku.provenance)
            != item["sku_identity_digest"]
        ):
            raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")
        item["sku_id"] = sku.id
        expected_by_ref[item["source_ref"]] = item
        expected_skus_by_deal.setdefault(deal.id, set()).add(item["sku_id"])

    target_deal_ids = {deal.id for deal in deals}
    existing_items = (
        await session.execute(
            select(DealItem).where(DealItem.deal_id.in_(target_deal_ids)).with_for_update()
        )
    ).scalars().all()
    expected_refs = set(expected_by_ref)
    if expected_refs:
        exact_source_items = (
            await session.execute(
                select(DealItem).where(DealItem.source_ref.in_(expected_refs)).with_for_update()
            )
        ).scalars().all()
        existing_by_id = {item.id: item for item in existing_items}
        existing_by_id.update({item.id: item for item in exact_source_items})
        existing_items = list(existing_by_id.values())

    existing_by_ref = {
        item.source_ref: item for item in existing_items if item.source_ref is not None
    }
    for item in existing_items:
        owner_external_id = external_deal_by_id.get(item.deal_id)
        source_ref = item.source_ref or ""
        if source_ref.startswith(_BITRIX_DEAL_ITEM_PREFIX):
            match = _BITRIX_DEAL_ITEM_SOURCE_RE.fullmatch(source_ref)
            if (
                match is None
                or match.group(1) != owner_external_id
                or source_ref not in expected_by_ref
            ):
                raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")
            expected = expected_by_ref[source_ref]
            if (
                item.deal_id != expected["db_deal_id"]
                or item.sku_id != expected["sku_id"]
                or item.qty != expected["quantity"]
                or item.unit_price is not None
            ):
                raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")
        elif item.sku_id in expected_skus_by_deal.get(item.deal_id, set()):
            raise ValueError("BITRIX_PRODUCT_ROWS_INVALID")

    for source_ref, item in expected_by_ref.items():
        if source_ref in existing_by_ref:
            stats["deal_item_existing"] = stats.get("deal_item_existing", 0) + 1
            continue
        session.add(DealItem(
            deal_id=item["db_deal_id"],
            sku_id=item["sku_id"],
            qty=item["quantity"],
            unit_price=None,
            source_ref=source_ref,
        ))
        stats["deal_item"] = stats.get("deal_item", 0) + 1


def _company_1c_evidence(
    companies: list[dict],
    requisites: list[dict],
    onec_counterparties: list[dict],
    *,
    referenced_company_ids: Iterable[object] = (),
) -> tuple[dict[str, dict], dict[str, str]]:
    """Match external company ids to one 1C master by unique UNP or name evidence.

    Names are used only when Bitrix has no UNP evidence and exactly one 1C Ref_Key
    has that normalized name. The result always contains canonical values from 1C.
    """
    unps_by_company: dict[str, set[str]] = {}
    raw_unp_by_company: dict[str, set[str]] = {}
    for row in requisites:
        company_id = str(row.get("ENTITY_ID") or "")
        raw_unp = str(row.get("RQ_INN") or "").strip()
        unp = _valid_unp(row.get("RQ_INN"))
        if company_id and raw_unp:
            raw_unp_by_company.setdefault(company_id, set()).add(raw_unp)
        if company_id and unp:
            unps_by_company.setdefault(company_id, set()).add(unp)

    onec_by_unp: dict[str, dict[str, dict]] = {}
    onec_by_name: dict[str, dict[str, dict]] = {}
    for row in onec_counterparties:
        # A 1C row marked for deletion is not a valid automatic CRM match.
        if str(row.get("DeletionMark") or "").strip().casefold() in {"true", "1"}:
            continue
        ref = str(row.get("Ref_Key") or "")
        unp = _valid_unp(row.get("ИНН"))
        if ref and unp:
            onec_by_unp.setdefault(unp, {}).setdefault(ref, row)
        normalized_name = _normalized_contact_name(row.get("Description"))
        if ref and normalized_name:
            onec_by_name.setdefault(normalized_name, {}).setdefault(ref, row)

    company_names = {
        str(row.get("ID") or ""): str(row.get("TITLE") or "").strip()
        for row in companies
        if row.get("ID") not in (None, "")
    }

    evidence: dict[str, dict] = {}
    issues: dict[str, str] = {}
    company_ids = _company_reference_ids(
        companies, requisites, referenced_company_ids
    )
    for company_id in sorted(company_ids):
        company_unps = unps_by_company.get(company_id, set())
        raw_unps = raw_unp_by_company.get(company_id, set())
        invalid_unps = {value for value in raw_unps if _valid_unp(value) is None}
        if len(company_unps) > 1 or (company_unps and invalid_unps):
            issues[company_id] = "ambiguous_company_unp"
            continue
        if len(company_unps) == 1:
            unp = next(iter(company_unps))
            onec_rows = onec_by_unp.get(unp, {})
            if not onec_rows:
                issues[company_id] = "no_1c_unp_match"
                continue
            if len(onec_rows) != 1:
                issues[company_id] = "ambiguous_1c_unp_match"
                continue
            ref, row = next(iter(onec_rows.items()))
            match_method = "unp"
        elif raw_unps:
            # An invalid or unusable supplied UNP is not silently bypassed by a name.
            issues[company_id] = "invalid_company_unp"
            continue
        else:
            normalized_name = _normalized_contact_name(company_names.get(company_id))
            if not normalized_name:
                issues[company_id] = "missing_company_name"
                continue
            onec_rows = onec_by_name.get(normalized_name, {})
            if not onec_rows:
                issues[company_id] = "no_1c_name_match"
                continue
            if len(onec_rows) != 1:
                issues[company_id] = "ambiguous_1c_name_match"
                continue
            ref, row = next(iter(onec_rows.items()))
            unp = _valid_unp(row.get("ИНН"))
            match_method = "name"
        evidence[company_id] = {
            "unp": unp,
            "ref": ref,
            "name": (row.get("Description") or "").strip()[:255] or "Без имени",
            "match_method": match_method,
        }
        issues[company_id] = "matched"
    return evidence, issues


def _normalized_contact_name(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _normalized_contact_phone(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits or None


def _normalized_contact_email(value: object) -> str | None:
    value = str(value or "").strip().casefold()
    return value or None


async def _resolve_crm_directory_links(
    session,
    deal_rows: list[dict],
    contacts_by_source_id: dict[str, dict],
    company_counterparties: dict[str, object],
    company_match_status: dict[str, str],
    *,
    new_deal_owner_ids: dict[str, int] | None = None,
    create_missing_directory: bool = False,
) -> dict[str, dict]:
    """Resolve source references to per-owner CRM directory rows.

    Creation is opt-in and restricted to new deals with a validated local owner and
    an evidenced 1C counterparty. Reconciliation remains read-only.
    """
    from sqlalchemy.exc import IntegrityError

    from core.domain.models import Counterparty
    from modules.sales.models import CrmClient, CrmClientContact, Deal

    if create_missing_directory:
        master_ids = sorted({
            counterparty.id
            for counterparty in company_counterparties.values()
            if counterparty is not None
        })
        if master_ids:
            # All importer writers for one master serialize before checking or
            # creating owner-scoped rows. Existing unique keys remain the backstop.
            await session.execute(
                select(Counterparty.id)
                .where(Counterparty.id.in_(master_ids))
                .order_by(Counterparty.id)
                .with_for_update()
            )

    numbers = {
        f"BX-{row.get('ID')}" for row in deal_rows
        if row.get("ID") not in (None, "")
        and str(row.get("CATEGORY_ID") or "0") in ("0", "7")
    }
    existing = (await session.execute(select(Deal).where(Deal.number.in_(numbers)))).scalars().all() if numbers else []
    deals_by_number = {row.number: row for row in existing}
    clients = (await session.execute(select(CrmClient))).scalars().all()
    contacts = (await session.execute(select(CrmClientContact))).scalars().all()
    clients_by_owner: dict[int, list] = {}
    contacts_by_client: dict[int, list] = {}
    contacts_by_id = {row.id: row for row in contacts}
    for row in clients:
        clients_by_owner.setdefault(row.owner_id, []).append(row)
    for row in contacts:
        contacts_by_client.setdefault(row.crm_client_id, []).append(row)

    resolved: dict[str, dict] = {}
    for source_deal in deal_rows:
        if str(source_deal.get("CATEGORY_ID") or "0") not in ("0", "7"):
            continue
        source_id = str(source_deal.get("ID") or "")
        number = f"BX-{source_id}"
        deal = deals_by_number.get(number)
        company_id = str(source_deal.get("COMPANY_ID") or "")
        counterparty = company_counterparties.get(company_id)
        owner_id = (
            deal.owner_id
            if deal is not None
            else (new_deal_owner_ids or {}).get(source_id)
        )
        owner_status = "matched" if owner_id is not None else "owner_unmapped"
        client_created = False
        contact_created = False
        if counterparty is None:
            client_status = company_match_status.get(company_id, "missing_company_reference")
            client_status = f"counterparty_{client_status}"
            expected_client_id = None
        elif owner_id is None:
            client_status = "owner_unmapped"
            expected_client_id = None
        else:
            owner_clients = clients_by_owner.get(owner_id, [])
            canonical_unp = _valid_unp(counterparty.unp)
            client_candidates = []
            conflicting_clients = []
            for client in owner_clients:
                client_unp = _valid_unp(client.unp)
                direct_match = client.counterparty_id == counterparty.id
                unp_match = canonical_unp is not None and client_unp == canonical_unp
                if direct_match and client_unp and canonical_unp and client_unp != canonical_unp:
                    conflicting_clients.append(client.id)
                    continue
                if unp_match and client.counterparty_id is not None and client.counterparty_id != counterparty.id:
                    conflicting_clients.append(client.id)
                    continue
                if direct_match or (unp_match and client.counterparty_id is None):
                    client_candidates.append(client)
            if conflicting_clients:
                client_status = "client_identity_conflict"
                expected_client_id = None
            elif len(client_candidates) > 1:
                client_status = "client_ambiguous"
                expected_client_id = None
            elif not client_candidates:
                # Keep the same spelling that a CRM client created directly
                # from this Counterparty uses; name_key is a persisted unique
                # key, so collapsing internal spaces here would break that
                # cross-path collision guard.
                canonical_name = str(counterparty.name or "").strip()[:255]
                canonical_name_key = canonical_name.casefold()
                name_or_unp_conflict = any(
                    client.name_key == canonical_name_key
                    or (
                        canonical_unp is not None
                        and _valid_unp(client.unp) == canonical_unp
                    )
                    for client in owner_clients
                )
                if name_or_unp_conflict:
                    client_status = "client_identity_conflict"
                    expected_client_id = None
                elif not canonical_name:
                    client_status = "client_identity_incomplete"
                    expected_client_id = None
                elif create_missing_directory and deal is None:
                    client_identity = f"{owner_id}:{counterparty.id}"
                    request_key = "bx-import-" + hashlib.sha256(
                        client_identity.encode("utf-8")
                    ).hexdigest()[:32]
                    request_data = {
                        "name": canonical_name,
                        "unp": canonical_unp,
                        "owner_id": owner_id,
                        "counterparty_id": counterparty.id,
                    }
                    client = CrmClient(
                        **request_data,
                        name_key=canonical_name_key,
                        request_key=request_key,
                        request_hash=hashlib.sha256(
                            json.dumps(request_data, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                        created_by="import_month",
                    )
                    try:
                        async with session.begin_nested():
                            session.add(client)
                            await session.flush()
                    except IntegrityError:
                        client_status = "client_identity_conflict"
                        expected_client_id = None
                    else:
                        owner_clients.append(client)
                        clients_by_owner.setdefault(owner_id, owner_clients)
                        expected_client_id = client.id
                        client_status = "matched"
                        client_created = True
                else:
                    client_status = "client_unmatched"
                    expected_client_id = None
            else:
                client_status = "matched"
                expected_client_id = client_candidates[0].id

        expected_contact_id = None
        contact_status = "no_contact_reference"
        existing_contact_pair_status = "none"
        if deal is not None and deal.crm_contact_id is not None:
            existing_contact = contacts_by_id.get(deal.crm_contact_id)
            if existing_contact is None:
                existing_contact_pair_status = "existing_contact_missing"
            elif deal.crm_client_id is None:
                if expected_client_id != existing_contact.crm_client_id:
                    existing_contact_pair_status = "existing_contact_client_mismatch"
            elif deal.crm_client_id != existing_contact.crm_client_id:
                existing_contact_pair_status = "existing_contact_client_mismatch"
        if existing_contact_pair_status != "none":
            contact_status = existing_contact_pair_status

        source_contact_id = str(source_deal.get("CONTACT_ID") or "")
        source_contact = contacts_by_source_id.get(source_contact_id)
        if source_contact_id and expected_client_id is not None:
            if source_contact is None:
                contact_status = "contact_source_missing"
            else:
                source_contact_company_id = str(source_contact.get("COMPANY_ID") or "")
                source_contact_company = company_counterparties.get(source_contact_company_id)
                if source_contact_company_id and (
                    source_contact_company is None
                    or source_contact_company.id != counterparty.id
                ):
                    contact_status = "contact_company_conflict"
                else:
                    raw_full_name = (
                        f"{source_contact.get('NAME') or ''} "
                        f"{source_contact.get('LAST_NAME') or ''}"
                    )
                    full_name = " ".join(raw_full_name.split())[:255]
                    raw_phone = str(_first_value(source_contact.get("PHONE")) or "").strip()
                    phone = re.sub(r"[\s()\-]", "", raw_phone) or None
                    raw_email = str(_first_value(source_contact.get("EMAIL")) or "").strip()
                    email = raw_email.casefold() or None
                    if not full_name or not (phone or email):
                        contact_status = "contact_identity_incomplete"
                    elif (
                        phone and not re.fullmatch(r"\+?[0-9]{3,20}", phone)
                    ) or (
                        email and (
                            len(email) > 255
                            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
                        )
                    ):
                        contact_status = "contact_identity_invalid"
                    else:
                        if create_missing_directory and deal is None:
                            await session.execute(
                                select(CrmClient.id)
                                .where(CrmClient.id == expected_client_id)
                                .with_for_update()
                            )
                            contacts_by_client[expected_client_id] = (
                                await session.execute(
                                    select(CrmClientContact).where(
                                        CrmClientContact.crm_client_id == expected_client_id
                                    )
                                )
                            ).scalars().all()
                        candidates = []
                        partial_candidates = []
                        normalized_source_name = _normalized_contact_name(full_name)
                        for directory_contact in contacts_by_client.get(expected_client_id, []):
                            if _normalized_contact_name(directory_contact.full_name) != normalized_source_name:
                                continue
                            directory_phone = _normalized_contact_phone(directory_contact.phone)
                            directory_email = _normalized_contact_email(directory_contact.email)
                            source_phone = _normalized_contact_phone(phone)
                            phone_match = bool(source_phone and directory_phone == source_phone)
                            email_match = bool(email and directory_email == email)
                            if not (phone_match or email_match):
                                continue
                            all_supplied_channels_match = (
                                (not source_phone or directory_phone == source_phone)
                                and (not email or directory_email == email)
                            )
                            if all_supplied_channels_match:
                                candidates.append(directory_contact)
                            else:
                                partial_candidates.append(directory_contact)
                        if len(candidates) > 1:
                            contact_status = "contact_ambiguous"
                        elif partial_candidates:
                            contact_status = "contact_identity_conflict"
                        elif not candidates:
                            if create_missing_directory and deal is None:
                                identity = {
                                    "full_name": full_name.casefold(),
                                    "phone": phone.casefold() if phone else None,
                                    "email": email,
                                }
                                contact_key = hashlib.sha256(
                                    json.dumps(identity, sort_keys=True).encode("utf-8")
                                ).hexdigest()
                                contact_data = {
                                    "full_name": full_name,
                                    "phone": phone,
                                    "email": email,
                                    "is_primary": False,
                                }
                                request_key = "bx-import-" + hashlib.sha256(
                                    f"{expected_client_id}:{contact_key}".encode("utf-8")
                                ).hexdigest()[:32]
                                directory_contact = CrmClientContact(
                                    crm_client_id=expected_client_id,
                                    **contact_data,
                                    contact_key=contact_key,
                                    request_key=request_key,
                                    request_hash=hashlib.sha256(
                                        json.dumps(
                                            contact_data, sort_keys=True
                                        ).encode("utf-8")
                                    ).hexdigest(),
                                )
                                try:
                                    async with session.begin_nested():
                                        session.add(directory_contact)
                                        await session.flush()
                                except IntegrityError:
                                    existing_contact = await session.scalar(
                                        select(CrmClientContact).where(
                                            CrmClientContact.crm_client_id == expected_client_id,
                                            CrmClientContact.contact_key == contact_key,
                                        )
                                    )
                                    if existing_contact is None:
                                        contact_status = "contact_identity_conflict"
                                    else:
                                        expected_contact_id = existing_contact.id
                                        contact_status = "matched"
                                        contacts_by_client.setdefault(
                                            expected_client_id, []
                                        ).append(existing_contact)
                                else:
                                    expected_contact_id = directory_contact.id
                                    contact_status = "matched"
                                    contact_created = True
                                    contacts_by_client.setdefault(
                                        expected_client_id, []
                                    ).append(directory_contact)
                            else:
                                contact_status = "contact_unmatched"
                        else:
                            contact_status = "matched"
                            expected_contact_id = candidates[0].id
        elif source_contact_id:
            contact_status = "client_unresolved"

        if existing_contact_pair_status != "none":
            contact_status = existing_contact_pair_status
        resolved[number] = {
            "source_id": source_id,
            "deal": deal,
            "expected_owner_id": owner_id,
            "owner_status": owner_status,
            "expected_client_id": expected_client_id,
            "expected_contact_id": expected_contact_id,
            "client_status": client_status,
            "contact_status": contact_status,
            "client_created": client_created,
            "contact_created": contact_created,
            "existing_contact_pair_status": existing_contact_pair_status,
        }
    return resolved


def _crm_directory_link_summary(resolved: dict[str, dict]) -> dict:
    """Aggregate link outcomes without exposing customer/contact values."""
    owner_statuses: Counter = Counter()
    client_statuses: Counter = Counter()
    contact_statuses: Counter = Counter()
    client_linked = contact_linked = client_conflicts = contact_conflicts = pair_conflicts = 0
    pair_statuses: Counter = Counter()
    for row in resolved.values():
        owner_statuses[row["owner_status"]] += 1
        client_statuses[row["client_status"]] += 1
        contact_statuses[row["contact_status"]] += 1
        pair_status = row.get("existing_contact_pair_status", "none")
        if pair_status != "none":
            pair_conflicts += 1
            pair_statuses[pair_status] += 1
        deal = row["deal"]
        if deal is None:
            continue
        expected_client_id = row["expected_client_id"]
        expected_contact_id = row["expected_contact_id"]
        if expected_client_id is not None:
            if deal.crm_client_id == expected_client_id:
                client_linked += 1
            elif deal.crm_client_id is None:
                client_statuses["client_link_missing"] += 1
            else:
                client_conflicts += 1
        if expected_contact_id is not None:
            # A contact is only a valid deal link when its owning client also
            # matches; this is the same pair constraint enforced by CRM lookup.
            if deal.crm_client_id != expected_client_id:
                if deal.crm_contact_id is None:
                    contact_statuses["contact_client_link_missing"] += 1
                else:
                    contact_conflicts += 1
            elif deal.crm_contact_id == expected_contact_id:
                contact_linked += 1
            elif deal.crm_contact_id is None:
                contact_statuses["contact_link_missing"] += 1
            else:
                contact_conflicts += 1
    return {
        "source_deals": len(resolved),
        "owner_outcomes": dict(sorted(owner_statuses.items())),
        "client_links_verified": client_linked,
        "contact_links_verified": contact_linked,
        "existing_client_link_conflicts": client_conflicts,
        "existing_contact_link_conflicts": contact_conflicts,
        "existing_contact_pair_conflicts": pair_conflicts,
        "existing_contact_pair_outcomes": dict(sorted(pair_statuses.items())),
        "client_outcomes": dict(sorted(client_statuses.items())),
        "contact_outcomes": dict(sorted(contact_statuses.items())),
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
    elif duplicate_source:
        review_counts["duplicate_source_identity"] = duplicate_source
        status = "requires_review"
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


def _expected_stock_semantic_rows(
    sku_rows: list[dict], sales_rows: list[dict], *, strict_catalog: bool = True
) -> list[dict]:
    """Построить ожидаемые строки цены тем же правилом, что и load-прослойка."""
    catalog = _prepare_onec_sku_catalog(sku_rows, strict=strict_catalog)
    sku_by_ref = {
        str(entry["ref_key"]): entry["code"]
        for entry in catalog["active_rows"]
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
    *, include_semantic_rows: bool = False, detail_rows: list[dict] | None = None,
    cache_snapshot: _PrivateCacheSnapshot | None = None,
) -> dict:
    """Собрать безопасную агрегированную сверку кэша без вывода исходных значений."""
    cache_dir = cache_snapshot.cache_dir if cache_snapshot is not None else OUT_DIR
    source_names = (
        cache_snapshot.entries
        if cache_snapshot is not None
        else (path.stem for path in sorted(cache_dir.glob("*.jsonl")))
    )
    files = {name: _load_jsonl(name, cache_snapshot) for name in source_names}
    users = files.get("bx_users", [])
    companies = files.get("bx_companies", [])
    contacts = files.get("bx_contacts", [])
    deals = files.get("bx_deals", [])
    leads = files.get("bx_leads", [])
    calls = files.get("bx_calls", [])
    task_rows = files.get("bx_tasks", [])
    task_source_available = "bx_tasks" in files
    prepared_bitrix_tasks = None
    task_source_invalid = False
    if include_semantic_rows and task_source_available:
        try:
            prepared_bitrix_tasks = _prepare_bitrix_tasks(task_rows, deals)
        except ValueError:
            prepared_bitrix_tasks = None
            task_source_invalid = True
    call_deal_source_available = "bx_calls" in files
    call_deal_source_invalid = False
    call_deal_expected_links = None
    if call_deal_source_available:
        try:
            call_deal_expected_links = _prepare_bitrix_call_deal_links(calls, deals)
        except ValueError:
            call_deal_source_invalid = True
    requisites = files.get("bx_requisites", [])
    onec_counterparties = files.get("onec_counterparties", [])
    onec_sales = files.get("onec_sales", [])
    onec_sku = files.get("onec_sku", [])
    onec_sku_catalog = _prepare_onec_sku_catalog(onec_sku, strict=False)
    active_onec_sku = onec_sku_catalog["active_rows"]
    product_row_envelopes = files.get("bx_product_rows", [])
    prepared_product_rows = None
    product_source_invalid = False
    if include_semantic_rows and (
        "bx_product_rows" in files
        or cache_snapshot is not None
    ):
        try:
            prepared_product_rows = _prepare_bitrix_deal_items(
                deals,
                product_row_envelopes,
                files.get("bx_products", []),
                onec_sku,
                require_complete=(
                    "bx_product_rows" in files
                    or cache_snapshot is not None
                ),
            )
        except ValueError:
            # Keep reconciliation available for aggregate SKU-catalog blockers.
            prepared_product_rows = None
            product_source_invalid = True
    stage_history_available = "bx_stage_history" in files
    stage_history_rows = files.get("bx_stage_history", [])
    prepared_stage_history = None
    stage_history_source_invalid = False
    if include_semantic_rows and stage_history_available:
        try:
            prepared_stage_history = _prepare_bitrix_stage_history(
                deals, stage_history_rows
            )
        except ValueError:
            prepared_stage_history = None
            stage_history_source_invalid = True
    timeline_comment_source_available = "bx_timeline_comments" in files
    timeline_comment_rows = files.get("bx_timeline_comments", [])
    private_cache_format = (
        cache_snapshot.cache_format
        if cache_snapshot is not None else _private_cache_format(cache_dir)
    )
    binary_cache_v2 = private_cache_format == _PRIVATE_CACHE_V2_FORMAT
    prepared_timeline_comments = None
    timeline_comment_source_invalid = False
    if include_semantic_rows and timeline_comment_source_available:
        try:
            prepared_timeline_comments = _prepare_bitrix_timeline_comments(
                deals, leads, timeline_comment_rows, users,
                allow_files=binary_cache_v2,
            )
        except ValueError:
            prepared_timeline_comments = None
            timeline_comment_source_invalid = True
    timeline_attachment_source_invalid = False
    prepared_timeline_attachments = None
    if include_semantic_rows and timeline_comment_source_available:
        if prepared_timeline_comments is None:
            timeline_attachment_source_invalid = binary_cache_v2 or any(
                isinstance(row, dict) and bool(row.get("FILES"))
                for row in timeline_comment_rows
            )
        else:
            try:
                prepared_timeline_attachments = _prepare_bitrix_timeline_attachments(
                    prepared_timeline_comments,
                    timeline_comment_rows,
                    files.get("bx_comment_binary_links", []) if binary_cache_v2 else [],
                    files.get("bx_comment_binary_inventory", []) if binary_cache_v2 else [],
                    cache_dir,
                )
            except ValueError:
                prepared_timeline_attachments = None
                timeline_attachment_source_invalid = True
    bitrix_product_row_count = sum(
        len(envelope.get("rows", []))
        for envelope in product_row_envelopes
        if isinstance(envelope, dict) and isinstance(envelope.get("rows", []), list)
    )

    user_ids = _nonempty_ids(users, "ID")
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
    call_deal_ids = {
        str(row.get("CRM_ENTITY_ID")).strip()
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "DEAL"
        and row.get("CRM_ENTITY_ID") not in (None, "")
    }
    supported_deal_ids = {
        str(row.get("ID") or "").strip()
        for row in deals
        if str(row.get("CATEGORY_ID") or "0") in {"0", "7"}
        and str(row.get("ID") or "").strip()
    }
    call_owner_ids = _nonempty_ids(calls, "PORTAL_USER_ID")
    requisite_company_ids = _nonempty_ids(requisites, "ENTITY_ID")
    company_evidence, company_match_status = _company_1c_evidence(
        companies,
        requisites,
        onec_counterparties,
        referenced_company_ids=(
            deal_company_ids
            | call_company_ids
            | _nonempty_ids(contacts, "COMPANY_ID")
        ),
    )
    # Company links target only an evidenced 1C master; Bitrix stores only minimal
    # ID/TITLE match evidence and is never treated as the counterparty directory.
    company_ids = set(company_evidence)

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
        "calls_to_deals": link_stats(call_deal_ids, supported_deal_ids),
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
    links["calls_to_deals"]["rows_missing"] = sum(
        str(row.get("CRM_ENTITY_ID") or "").strip() not in supported_deal_ids
        for row in calls
        if row.get("CRM_ENTITY_TYPE") == "DEAL"
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
    dedicated_history_names = {"bx_history", "bx_timeline_comments"}
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
        "bitrix_product_rows": bitrix_product_row_count,
        "bitrix_product_catalog_rows": len(files.get("bx_products", [])),
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
    contacts_by_id = {str(row.get("ID") or ""): row for row in contacts}
    def source_contact_fields(row: dict) -> tuple[str, str | None, str | None]:
        full_name = f"{row.get('NAME') or ''} {row.get('LAST_NAME') or ''}".strip()[:255]
        full_name = full_name or f"Контакт {row.get('ID') or ''}"
        phone = (_first_value(row.get("PHONE")) or "")[:64] or None
        email = _first_value(row.get("EMAIL")) or None
        return full_name, phone, email

    def company_link(company_id: object) -> str | None:
        value = str(company_id or "")
        return f"company:{value}" if value in company_evidence else None

    source_identity_ids: dict[str, dict[str, str]] = {}
    source_company_semantic = [
        {
            "identity": f"company:{company_id}",
            "name": evidence["name"],
            "unp": evidence["unp"],
        }
        for company_id, evidence in sorted(company_evidence.items())
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
        company = company_evidence.get(str(row.get("COMPANY_ID") or ""))
        counterparty = company["name"] if company else "Не указан"
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
    source_call_deal_links = call_deal_expected_links or {}
    source_deal_company_links = {
        f"BX-{row['ID']}": company_link(row.get("COMPANY_ID"))
        for row in supported_deals
    }
    for row in calls:
        try:
            call_id = _canonical_bitrix_call_id(row)
        except ValueError:
            continue
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
        if entity_type == "DEAL" and source_call_deal_links.get(call_id):
            counterparty = source_deal_company_links.get(source_call_deal_links[call_id])
        source_call_semantic.append(
            {
                "identity": call_id,
                "direction": "out" if str(row.get("CALL_TYPE")) in ("1", "4") else "in",
                "phone_e164": (row.get("PHONE_NUMBER") or "")[:32] or None,
                "owner": users_by_id.get(str(row.get("PORTAL_USER_ID") or ""), "")[:128],
                "counterparty_link": counterparty,
                "contact_link": contact_link,
                "deal_link": (
                    _opaque_identity("deal_link", source_call_deal_links[call_id])
                    if source_call_deal_links.get(call_id) else None
                ),
                "status": "ended" if answered else "missed",
                "recording_url": (row.get("CALL_RECORD_URL") or "")[:255] or None,
                "started_at": started,
                "answered_at": started if answered else None,
                "ended_at": started + timedelta(seconds=duration),
                "duration_sec": duration or None,
            }
        )

    source_task_semantic = (
        prepared_bitrix_tasks["source_semantic_rows"]
        if prepared_bitrix_tasks is not None else []
    )
    for row in source_task_semantic:
        source_identity_ids.setdefault("bitrix_tasks", {}).setdefault(
            row["identity"], row["identity"].removeprefix(_BITRIX_TASK_PREFIX)
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
            "identity": entry["digest"],
            "code": entry["code"],
            "title": str(entry["row"].get("Description") or entry["code"])[:255],
            "active": True,
        }
        for entry in active_onec_sku
    ]
    source_identity_ids["onec_sku"] = {
        entry["digest"]: entry["digest"]
        for entry in active_onec_sku
    }
    source_identity_ids["onec_stock_prices"] = {
        f"{entry['code']}|Главный": entry["digest"]
        for entry in active_onec_sku
    }
    source_semantic_rows = {
        "bitrix_companies": source_company_semantic,
        "bitrix_contacts": source_contact_semantic,
        "bitrix_deals": source_deal_semantic,
        "bitrix_leads": source_lead_semantic,
        "bitrix_calls": source_call_semantic,
        "onec_payments": source_payment_semantic,
        "onec_sku": source_sku_semantic,
        "onec_stock_prices": _expected_stock_semantic_rows(
            onec_sku, onec_sales, strict_catalog=False
        ),
    }
    if task_source_available:
        source_semantic_rows["bitrix_tasks"] = source_task_semantic
    semantic = {name: _semantic_summary(rows) for name, rows in source_semantic_rows.items()}
    unique_deal_rows, identical_deal_duplicates, conflicting_deal_ids, missing_deal_ids = (
        _deduplicate_source_deals(deals)
    )
    report = {
        "source": source,
        "links": links,
        "company_1c_mapping": {
            "company_references": len(company_match_status),
            "matched_by_unique_unp": sum(
                row["match_method"] == "unp" for row in company_evidence.values()
            ),
            "matched_by_unique_name": sum(
                row["match_method"] == "name" for row in company_evidence.values()
            ),
            "unresolved": len(company_match_status) - len(company_evidence),
            "outcomes": dict(sorted(Counter(company_match_status.values()).items())),
        },
        "stages": stages,
        "products": products,
        "financial": financial,
        "semantic": semantic,
        "sku_identity_catalog": {
            **onec_sku_catalog["stats"],
            "valid": onec_sku_catalog["valid"],
        },
        "deduplication": {
            "bitrix_deals": {
                "source_rows": len(deals),
                "unique_source_rows": len(unique_deal_rows),
                "identical_duplicate_rows": identical_deal_duplicates,
                "conflicting_source_ids": conflicting_deal_ids,
                "missing_source_id_rows": missing_deal_ids,
                "key": "ID",
            },
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
        "call_deal_links": {
            "source_available": call_deal_source_available,
            "source_rows": len(calls),
            "deal_target_rows": sum(
                row.get("CRM_ENTITY_TYPE") == "DEAL" for row in calls
            ),
            "invalid_source": call_deal_source_invalid,
        },
        "tasks": {
            "source_available": task_source_available,
            "source_rows": len(task_rows),
            "invalid_source": task_source_invalid,
        },
        "files": {
            "dedicated_source_available": bool(dedicated_file_names & files.keys()),
            "call_rows_with_recording_metadata": call_file_ref_rows,
            "binary_files_in_cache": 0,
        },
        "history": {
            "dedicated_source_available": bool(dedicated_history_names & files.keys()),
            "stage_history_rows_available": stage_history_available,
            "stage_history_source_rows": len(stage_history_rows),
        },
        "timeline_comments": {
            "source_available": timeline_comment_source_available,
            "source_rows": len(timeline_comment_rows),
        },
        "timeline_attachments": {
            "source_available": timeline_comment_source_available,
            "binary_cache_v2": binary_cache_v2,
            "source_rows": len(files.get("bx_comment_binary_links", [])),
            "inventory_rows": len(files.get("bx_comment_binary_inventory", [])),
            "source_bytes": (
                cache_snapshot.comment_binary_bytes
                if binary_cache_v2 and cache_snapshot is not None
                else 0
            ),
        },
    }
    # Сырые semantic rows нужны только внутреннему сравнению полей. Не включать их
    # в печатаемый/сохраняемый aggregate report: там могут быть PII из локального кэша.
    if include_semantic_rows:
        report["_semantic_rows"] = source_semantic_rows
        report["_source_identity_ids"] = source_identity_ids
        report["_onec_sku_identity_expected"] = {
            entry["digest"]: {
                "code": entry["code"],
                "title": str(entry["row"].get("Description") or entry["code"])[:255],
            }
            for entry in active_onec_sku
        }
        report["_bitrix_product_source_invalid"] = product_source_invalid
        report["_bitrix_product_expected_semantics"] = (
            {
                row["source_ref"]: (
                    row["number"],
                    row["sku_code"],
                    row["quantity"],
                    None,
                )
                for row in prepared_product_rows["items"]
            }
            if prepared_product_rows is not None else None
        )
        report["_bitrix_product_scope_deal_ids"] = (
            prepared_product_rows["scope_deal_ids"]
            if prepared_product_rows is not None else None
        )
        report["_bitrix_stage_history_source_invalid"] = stage_history_source_invalid
        report["_bitrix_stage_history_expected_semantics"] = (
            prepared_stage_history["expected_semantics"]
            if prepared_stage_history is not None else None
        )
        report["_bitrix_stage_history_scope_deal_ids"] = (
            prepared_stage_history["scope_deal_ids"]
            if prepared_stage_history is not None else None
        )
        report["_bitrix_timeline_comment_source_invalid"] = (
            timeline_comment_source_invalid
        )
        report["_bitrix_timeline_comment_expected_semantics"] = (
            prepared_timeline_comments["expected_semantics"]
            if prepared_timeline_comments is not None else None
        )
        report["_bitrix_timeline_comment_scope_owners"] = (
            prepared_timeline_comments["scope_owners"]
            if prepared_timeline_comments is not None else None
        )
        report["_bitrix_timeline_attachment_source_invalid"] = (
            timeline_attachment_source_invalid
        )
        report["_bitrix_timeline_attachment_expected_semantics"] = (
            prepared_timeline_attachments["expected_semantics"]
            if prepared_timeline_attachments is not None else None
        )
        report["_bitrix_call_deal_source_invalid"] = call_deal_source_invalid
        report["_bitrix_call_expected_deal_links"] = call_deal_expected_links
        report["_bitrix_task_source_invalid"] = task_source_invalid
        report["_bitrix_task_expected_semantics"] = (
            prepared_bitrix_tasks["expected_semantics"]
            if prepared_bitrix_tasks is not None else None
        )
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
    if not _cached("bx_companies"):
        rows = []
        for chunk in _chunks(company_ids):
            rows += bx_list("crm.company.list", {"filter": {"@ID": chunk}, "select": [
                "ID", "TITLE"]})
        _dump("bx_companies", rows)

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


def extract_onec_purchases() -> None:
    """Сохранить только сырой месячный набор закупочных документов 1С в локальный кэш."""
    global OUT_DIR
    OUT_DIR = _resolve_cache_dir()
    entity = os.getenv("IMPORT_ONEC_PURCHASE_ENTITY", "").strip()
    prefix = "Document_"
    suffix = entity[len(prefix):] if entity.startswith(prefix) else ""
    if not suffix or len(entity) > 180 or any(not (char.isalnum() or char == "_") for char in suffix):
        raise RuntimeError(
            "Задайте IMPORT_ONEC_PURCHASE_ENTITY явным OData-типом Document_* из метаданных 1С"
        )
    if ONEC_FROM >= ONEC_TO:
        raise RuntimeError("IMPORT_ONEC_FROM должен быть раньше IMPORT_ONEC_TO")

    cache_path = OUT_DIR / "onec_purchases.jsonl"
    metadata_path = OUT_DIR / "onec_purchases.meta.json"
    if cache_path.exists() or metadata_path.exists():
        if not cache_path.is_file() or not metadata_path.is_file():
            raise RuntimeError("Неполный кэш закупочных документов 1С; сохраните его и разберите вручную")
        try:
            payload = cache_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Не удалось проверить кэш закупочных документов 1С") from exc
        row_count = sum(1 for line in payload.splitlines() if line.strip())
        expected = {
            "schema_version": "onec-purchase-cache-v1",
            "source_system": "onec",
            "entity": entity,
            "date_from": ONEC_FROM,
            "date_to": ONEC_TO,
            "record_count": row_count,
            "source_sha256": hashlib.sha256(payload).hexdigest(),
        }
        if metadata != expected:
            raise RuntimeError(
                "Кэш закупочных документов 1С не совпадает с типом, периодом или контрольной суммой; "
                "сохраните исходный кэш и разберите его вручную"
            )
        print(f"extract-onec-purchases: кэш проверен ({entity}, документов={row_count})")
        return

    if not _onec_base_url():
        raise RuntimeError("ONEC_BASE_URL / IMPORT_ONEC_BASE не задан — извлечение 1С невозможно")
    docs = onec_window(entity, ONEC_FROM, ONEC_TO, parse_float=Decimal)
    seen_refs: set[str] = set()
    for index, row in enumerate(docs, start=1):
        if not isinstance(row, dict):
            raise RuntimeError(f"Документ 1С #{index} имеет неверный формат")
        ref_key = row.get("Ref_Key")
        if not isinstance(ref_key, str) or not ref_key.strip() or ref_key != ref_key.strip():
            raise RuntimeError(f"Документ 1С #{index} не содержит устойчивый Ref_Key")
        if ref_key in seen_refs:
            raise RuntimeError(f"В выборке 1С повторяется Ref_Key документа #{index}")
        seen_refs.add(ref_key)
        document_date = row.get("Date")
        if not isinstance(document_date, str) or not (ONEC_FROM <= document_date < ONEC_TO):
            raise RuntimeError(f"Дата документа 1С #{index} вне заданного периода или отсутствует")

    _dump_onec_purchase_cache(cache_path, docs)
    payload = cache_path.read_bytes()
    metadata = {
        "schema_version": "onec-purchase-cache-v1",
        "source_system": "onec",
        "entity": entity,
        "date_from": ONEC_FROM,
        "date_to": ONEC_TO,
        "record_count": len(docs),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"extract-onec-purchases: кэш создан ({entity}, документов={len(docs)})")


def map_onec_purchases() -> None:
    """Build API-compatible procurement draft payloads; do not write to ERP."""
    from modules.accounting.onec_purchase_import import (
        PurchaseImportError,
        UnmappedPurchaseDocuments,
        prepare_month_plan,
        write_month_plan,
        write_unmapped_report,
    )

    cache_dir = _resolve_cache_dir(require_override=True)
    raw_mapping_path = os.getenv("IMPORT_ONEC_PURCHASE_MAPPING", "").strip()
    if not raw_mapping_path:
        raise RuntimeError("map-onec-purchases требует IMPORT_ONEC_PURCHASE_MAPPING")
    mapping_path = Path(raw_mapping_path).expanduser()
    if not mapping_path.is_absolute():
        raise RuntimeError("IMPORT_ONEC_PURCHASE_MAPPING должен быть абсолютным путём")
    mapping_path = mapping_path.resolve()
    try:
        drafts, metadata = prepare_month_plan(cache_dir, mapping_path)
    except UnmappedPurchaseDocuments as exc:
        report = write_unmapped_report(cache_dir, exc.issues)
        raise RuntimeError(
            f"Весь месячный пакет остановлен: несопоставлено строк/документов={len(exc.issues)}; "
            f"отчёт={report.name}; черновой пакет не создан"
        ) from exc
    except PurchaseImportError as exc:
        raise RuntimeError(f"map-onec-purchases: {exc}") from exc
    data_path, meta_path = write_month_plan(cache_dir, drafts, metadata)
    print(
        "map-onec-purchases: пакет проверен "
        f"(документов={metadata['source_record_count']}, черновиков={len(drafts)}, "
        f"payload={data_path.name}, metadata={meta_path.name}, previewed=false, posted=false)"
    )


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


_BITRIX_STAGE_EVENT_PREFIX = "bitrix:deal-stage:"
_BITRIX_STAGE_EVENT_SOURCE_RE = re.compile(
    r"^bitrix:deal-stage:([1-9][0-9]*):([1-9][0-9]*)$"
)
_BITRIX_TIMELINE_COMMENT_PREFIX = "bitrix:timeline-comment:"
_BITRIX_TIMELINE_COMMENT_SOURCE_RE = re.compile(
    r"^bitrix:timeline-comment:(deal|lead):([1-9][0-9]*)$"
)
_BITRIX_TIMELINE_ATTACHMENT_PREFIX = "bitrix:timeline-file:"
_BITRIX_TIMELINE_ATTACHMENT_SOURCE_RE = re.compile(
    r"^bitrix:timeline-file:deal:([1-9][0-9]*):([1-9][0-9]*):([1-9][0-9]*)$"
)
_BITRIX_CATEGORY_SEVEN_STAGES = frozenset(
    {"WON", "LOSE", "INVOICE", "NEW", "PREPARATION", "EXECUTING"}
    | set(LOST_TITLES)
)


def _bitrix_stage_datetime(value: object) -> datetime | None:
    """Parse stage-history time and normalize aware values to UTC-naive storage."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, ValueError):
        return None


_BITRIX_TASK_PREFIX = "bitrix:task:"
_BITRIX_TASK_SOURCE_RE = re.compile(r"^bitrix:task:([1-9][0-9]*)$")
_BITRIX_TASK_STATUS_MAP = {
    "2": "open",
    "3": "in_progress",
    "4": "awaiting_control",
    "5": "done",
    "6": "postponed",
    "7": "declined",
}
_BITRIX_TASK_BINDING_RE = re.compile(r"^([A-Za-z0-9]{1,32})_([1-9][0-9]*)$")


def _prepare_bitrix_tasks(
    task_rows: list[dict], deal_rows: list[dict]
) -> dict[str, object]:
    """Validate task identity and source links before opening the destination DB."""
    invalid = ValueError("BITRIX_TASK_INVALID")
    unique_deals, _, _, _ = _deduplicate_source_deals(deal_rows)
    supported_deal_numbers: dict[str, str] = {}
    for deal in unique_deals:
        try:
            deal_id = _canonical_positive_id(deal.get("ID"))
        except ValueError:
            continue
        category = deal.get("CATEGORY_ID")
        if isinstance(category, bool):
            continue
        category = str(category if category not in (None, "") else "0")
        if category in {"0", "7"}:
            supported_deal_numbers[deal_id] = f"BX-{deal_id}"

    def task_id_of(row: dict) -> str:
        values = [row[key] for key in ("id", "ID") if key in row]
        if not values:
            raise invalid
        try:
            canonical = [_canonical_positive_id(value) for value in values]
        except ValueError:
            raise invalid from None
        if len(set(canonical)) != 1:
            raise invalid
        return canonical[0]

    def empty_source_value(value: object) -> bool:
        return value is None or value == "" or value == []

    seen_task_ids: set[str] = set()
    prepared: list[dict] = []
    expected_semantics: dict[str, tuple] = {}
    source_semantic_rows: list[dict] = []
    for row in task_rows:
        if not isinstance(row, dict):
            raise invalid
        task_id = task_id_of(row)
        if task_id in seen_task_ids:
            raise invalid
        seen_task_ids.add(task_id)
        source_ref = f"{_BITRIX_TASK_PREFIX}{task_id}"
        if len(source_ref) > 128:
            raise invalid

        title = row.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 255:
            raise invalid
        description = row.get("description")
        if description is not None and not isinstance(description, str):
            raise invalid
        description_in_bbcode = row.get("descriptionInBbcode")
        if description_in_bbcode is not None:
            if description_in_bbcode == "Y":
                description_in_bbcode = True
            elif description_in_bbcode == "N":
                description_in_bbcode = False
            else:
                raise invalid

        raw_responsible = row.get("responsibleId")
        if raw_responsible in (None, ""):
            source_responsible_id = None
        else:
            try:
                source_responsible_id = _canonical_positive_id(raw_responsible)
            except ValueError:
                raise invalid from None
            if len(source_responsible_id) > 64:
                raise invalid

        raw_status = row.get("status")
        if isinstance(raw_status, bool):
            raise invalid
        if type(raw_status) is int:
            source_status_code = str(raw_status)
        elif isinstance(raw_status, str) and raw_status in _BITRIX_TASK_STATUS_MAP:
            source_status_code = raw_status
        else:
            raise invalid
        status = _BITRIX_TASK_STATUS_MAP.get(source_status_code)
        if status is None:
            raise invalid

        raw_deadline = row.get("deadline")
        if raw_deadline in (None, ""):
            due_at = None
        else:
            due_at = _bitrix_stage_datetime(raw_deadline)
            if due_at is None:
                raise invalid

        for field in (
            "ufTaskWebdavFiles", "UF_TASK_WEBDAV_FILES", "ufMailMessage",
            "UF_MAIL_MESSAGE",
        ):
            if field not in row:
                continue
            value = row[field]
            if not empty_source_value(value):
                raise invalid

        binding_fields = [
            field for field in ("ufCrmTask", "UF_CRM_TASK") if field in row
        ]
        if len(binding_fields) == 2:
            lower_bindings, upper_bindings = (
                row["ufCrmTask"], row["UF_CRM_TASK"]
            )
            if type(lower_bindings) is not type(upper_bindings) or (
                lower_bindings != upper_bindings
            ):
                raise invalid
        raw_bindings = row[binding_fields[0]] if binding_fields else []
        if raw_bindings is None:
            raw_bindings = []
        if not isinstance(raw_bindings, list):
            raise invalid
        prepared_links: list[dict] = []
        resolved_deal_numbers: set[str] = set()
        for ordinal, raw_binding in enumerate(raw_bindings):
            if not isinstance(raw_binding, str):
                raise invalid
            match = _BITRIX_TASK_BINDING_RE.fullmatch(raw_binding)
            if match is None:
                raise invalid
            entity_type, source_id = match.groups()
            if len(source_id) > 64:
                raise invalid
            deal_number = None
            if entity_type == "D":
                deal_number = supported_deal_numbers.get(source_id)
                if deal_number is None:
                    raise invalid
                resolved_deal_numbers.add(deal_number)
            prepared_links.append({
                "ordinal": ordinal,
                "raw_binding": raw_binding,
                "entity_type": entity_type,
                "source_id": source_id,
                "deal_number": deal_number,
            })

        task_deal_number = (
            next(iter(resolved_deal_numbers)) if len(resolved_deal_numbers) == 1 else None
        )
        semantics = (
            title,
            description,
            description_in_bbcode,
            source_responsible_id,
            source_status_code,
            status,
            due_at,
            None,
            task_deal_number,
            tuple(
                (
                    link["ordinal"], link["raw_binding"], link["entity_type"],
                    link["source_id"], link["deal_number"],
                )
                for link in prepared_links
            ),
        )
        prepared_task = {
            "source_ref": source_ref,
            "title": title,
            "description": description,
            "description_in_bbcode": description_in_bbcode,
            "source_responsible_id": source_responsible_id,
            "source_status_code": source_status_code,
            "status": status,
            "due_at": due_at,
            "assignee_id": None,
            "deal_number": task_deal_number,
            "links": prepared_links,
            "semantics": semantics,
        }
        prepared.append(prepared_task)
        expected_semantics[source_ref] = semantics
        source_semantic_rows.append({
            "identity": source_ref,
            "title": title,
            "description": description,
            "description_in_bbcode": description_in_bbcode,
            "source_responsible_id": source_responsible_id,
            "source_status_code": source_status_code,
            "status": status,
            "due_at": due_at,
            "assignee_id": None,
            "deal_number": task_deal_number,
            "links": [
                (
                    link["ordinal"], link["raw_binding"], link["entity_type"],
                    link["source_id"], link["deal_number"],
                )
                for link in prepared_links
            ],
        })

    return {
        "tasks": prepared,
        "expected_semantics": expected_semantics,
        "source_semantic_rows": source_semantic_rows,
    }


async def _validate_existing_bitrix_tasks(s, prepared: dict[str, object]) -> None:
    """Reject stale, orphaned, or semantically changed imported task rows."""
    from modules.sales.models import Deal, DealTask, DealTaskCrmLink

    expected = prepared["expected_semantics"]
    existing = (await s.execute(
        select(DealTask)
        .where(DealTask.source_ref.like(f"{_BITRIX_TASK_PREFIX}%"))
        .with_for_update()
    )).scalars().all()
    seen_refs: set[str] = set()
    for task in existing:
        source_ref = task.source_ref or ""
        if _BITRIX_TASK_SOURCE_RE.fullmatch(source_ref) is None:
            raise ValueError("BITRIX_TASK_CONFLICT")
        if source_ref in seen_refs or source_ref not in expected:
            raise ValueError("BITRIX_TASK_CONFLICT")
        seen_refs.add(source_ref)
        task_deal_number = None
        if task.deal_id is not None:
            task_deal_number = await s.scalar(
                select(Deal.number).where(Deal.id == task.deal_id)
            )
            if task_deal_number is None:
                task_deal_number = "__orphan__"
        link_rows = (await s.execute(
            select(
                DealTaskCrmLink.ordinal,
                DealTaskCrmLink.raw_binding,
                DealTaskCrmLink.entity_type,
                DealTaskCrmLink.source_id,
                DealTaskCrmLink.deal_id,
                Deal.number,
            )
            .outerjoin(Deal, Deal.id == DealTaskCrmLink.deal_id)
            .where(DealTaskCrmLink.task_id == task.id)
            .order_by(DealTaskCrmLink.ordinal, DealTaskCrmLink.id)
            .with_for_update()
        )).all()
        link_semantics = []
        for ordinal, raw_binding, entity_type, source_id, deal_id, deal_number in link_rows:
            if deal_id is not None and deal_number is None:
                deal_number = "__orphan__"
            link_semantics.append(
                (ordinal, raw_binding, entity_type, source_id, deal_number)
            )
        actual = (
            task.title,
            task.description,
            task.description_in_bbcode,
            task.source_responsible_id,
            task.source_status_code,
            task.status,
            task.due_at,
            task.assignee_id,
            task_deal_number,
            tuple(link_semantics),
        )
        if actual != expected[source_ref]:
            raise ValueError("BITRIX_TASK_CONFLICT")


async def _import_bitrix_tasks(
    s,
    prepared: dict[str, object],
    deal_by_number: dict[str, object],
    stats: dict[str, int],
) -> None:
    """Insert source-keyed tasks and their ordered CRM bindings idempotently."""
    from modules.sales.models import DealTask, DealTaskCrmLink

    tasks = prepared["tasks"]
    source_refs = [task["source_ref"] for task in tasks]
    existing_refs = set()
    if source_refs:
        existing_refs = set((await s.execute(
            select(DealTask.source_ref).where(DealTask.source_ref.in_(source_refs))
        )).scalars())
    for source_task in tasks:
        source_ref = source_task["source_ref"]
        if source_ref in existing_refs:
            stats["task_existing"] += 1
            continue
        task_deal = deal_by_number.get(source_task["deal_number"])
        if source_task["deal_number"] is not None and task_deal is None:
            raise ValueError("BITRIX_TASK_DEAL_UNRESOLVED")
        task = DealTask(
            source_ref=source_ref,
            deal_id=task_deal.id if task_deal is not None else None,
            title=source_task["title"],
            kind="other",
            description=source_task["description"],
            description_in_bbcode=source_task["description_in_bbcode"],
            source_responsible_id=source_task["source_responsible_id"],
            source_status_code=source_task["source_status_code"],
            assignee_id=None,
            due_at=source_task["due_at"],
            status=source_task["status"],
        )
        s.add(task)
        await s.flush()
        for link in source_task["links"]:
            linked_deal = deal_by_number.get(link["deal_number"])
            if link["deal_number"] is not None and linked_deal is None:
                raise ValueError("BITRIX_TASK_DEAL_UNRESOLVED")
            s.add(DealTaskCrmLink(
                task_id=task.id,
                ordinal=link["ordinal"],
                raw_binding=link["raw_binding"],
                entity_type=link["entity_type"],
                source_id=link["source_id"],
                deal_id=linked_deal.id if linked_deal is not None else None,
            ))
            stats["task_link"] += 1
        stats["task"] += 1


def _prepare_bitrix_stage_history(
    deal_rows: list[dict], history_rows: list[dict]
) -> dict[str, object]:
    """Validate and normalize explicit Bitrix deal-stage history without writing."""
    invalid = ValueError("BITRIX_STAGE_HISTORY_INVALID")
    deals_by_id: dict[str, dict] = {}
    scope_deal_ids: set[str] = set()
    for deal in deal_rows:
        if not isinstance(deal, dict):
            raise invalid
        try:
            deal_id = _canonical_positive_id(deal.get("ID"))
        except ValueError:
            raise invalid from None
        prior = deals_by_id.get(deal_id)
        if prior is not None and prior != deal:
            raise invalid
        deals_by_id[deal_id] = deal
        scope_deal_ids.add(deal_id)

    seen_row_ids: set[str] = set()
    prepared_events: list[dict] = []
    for row in history_rows:
        if not isinstance(row, dict):
            raise invalid
        try:
            row_id = _canonical_positive_id(row.get("ID"))
            deal_id = _canonical_positive_id(row.get("OWNER_ID"))
        except ValueError:
            raise invalid from None
        if row_id in seen_row_ids:
            raise invalid
        seen_row_ids.add(row_id)
        deal = deals_by_id.get(deal_id)
        if deal is None:
            raise invalid

        raw_category = row.get("CATEGORY_ID")
        if isinstance(raw_category, bool):
            raise invalid
        if type(raw_category) is int:
            category = str(raw_category)
        elif isinstance(raw_category, str) and raw_category in {"0", "7"}:
            category = raw_category
        else:
            raise invalid
        if category not in {"0", "7"}:
            raise invalid

        raw_type = row.get("TYPE_ID")
        if isinstance(raw_type, bool):
            raise invalid
        if type(raw_type) is int and raw_type in {1, 2, 3, 5}:
            type_id = raw_type
        elif isinstance(raw_type, str) and raw_type in {"1", "2", "3", "5"}:
            type_id = int(raw_type)
        else:
            raise invalid

        semantic_id = row.get("STAGE_SEMANTIC_ID")
        if not isinstance(semantic_id, str) or semantic_id not in {"P", "S", "F"}:
            raise invalid

        raw_stage = row.get("STAGE_ID")
        if (
            not isinstance(raw_stage, str)
            or not raw_stage
            or raw_stage != raw_stage.strip()
            or len(raw_stage) > 128
        ):
            raise invalid
        if ":" in raw_stage:
            prefix = re.fullmatch(r"C([0-9]+):([^:]+)", raw_stage)
            if prefix is None or prefix.group(1) != category:
                raise invalid
            stage_suffix = prefix.group(2)
        else:
            stage_suffix = raw_stage
        if not stage_suffix or stage_suffix != stage_suffix.strip():
            raise invalid
        if category == "0":
            if stage_suffix not in STAGE_MAP:
                raise invalid
        elif stage_suffix not in _BITRIX_CATEGORY_SEVEN_STAGES:
            raise invalid
        to_stage, _, _ = _map_deal_stage(raw_stage, category)

        changed_at = _bitrix_stage_datetime(row.get("CREATED_TIME"))
        if changed_at is None:
            raise invalid
        source_ref = f"{_BITRIX_STAGE_EVENT_PREFIX}{deal_id}:{row_id}"
        if len(source_ref) > 128:
            raise invalid
        prepared_events.append({
            "deal_id": deal_id,
            "number": f"BX-{deal_id}",
            "row_id": row_id,
            "source_ref": source_ref,
            "source_stage_id": raw_stage,
            "source_category_id": category,
            "source_type_id": type_id,
            "source_semantic_id": semantic_id,
            "to_stage": to_stage,
            "changed_at": changed_at,
            "changed_by": "",
        })

    previous_stage: dict[str, str] = {}
    chronological_events = sorted(
        prepared_events,
        key=lambda item: (item["deal_id"], item["changed_at"], int(item["row_id"])),
    )
    for event in chronological_events:
        event["from_stage"] = previous_stage.get(event["deal_id"])
        previous_stage[event["deal_id"]] = event["to_stage"]
    prepared_events = chronological_events

    expected_semantics = {
        event["source_ref"]: (
            event["number"],
            event["source_stage_id"],
            event["source_category_id"],
            event["source_type_id"],
            event["source_semantic_id"],
            event["from_stage"],
            event["to_stage"],
            event["changed_at"],
            event["changed_by"],
        )
        for event in prepared_events
    }
    return {
        "events": prepared_events,
        "scope_deal_ids": scope_deal_ids,
        "expected_semantics": expected_semantics,
    }


def _bitrix_stage_event_semantics(event, deal_number: str) -> tuple:
    return (
        deal_number,
        event.source_stage_id,
        event.source_category_id,
        event.source_type_id,
        event.source_semantic_id,
        event.from_stage,
        event.to_stage,
        event.changed_at,
        event.changed_by or "",
    )


async def _validate_existing_bitrix_stage_events(session, prepared: dict[str, object]) -> None:
    """Reject stale or manually changed imported events before any load writes."""
    from modules.sales.models import Deal, DealStageEvent

    scope_ids = prepared["scope_deal_ids"]
    expected = prepared["expected_semantics"]
    if not scope_ids and not expected:
        return
    scope_numbers = {f"BX-{deal_id}" for deal_id in scope_ids}
    rows = (await session.execute(
        select(DealStageEvent, Deal.number)
        .join(Deal, Deal.id == DealStageEvent.deal_id)
        .where(DealStageEvent.source_ref.like(f"{_BITRIX_STAGE_EVENT_PREFIX}%"))
        .with_for_update()
    )).all()
    for event, deal_number in rows:
        source_ref = event.source_ref or ""
        match = _BITRIX_STAGE_EVENT_SOURCE_RE.fullmatch(source_ref)
        if (
            deal_number not in scope_numbers
            and source_ref not in expected
            and not (match and match.group(1) in scope_ids)
        ):
            continue
        expected_semantic = expected.get(source_ref)
        if (
            expected_semantic is None
            or _bitrix_stage_event_semantics(event, deal_number) != expected_semantic
        ):
            raise ValueError("BITRIX_STAGE_HISTORY_INVALID")


async def _import_bitrix_stage_history(
    session, prepared: dict[str, object], stats: dict
) -> None:
    from modules.sales.models import Deal, DealStageEvent

    events = prepared["events"]
    if not events:
        return
    numbers = {event["number"] for event in events}
    deals = (await session.execute(
        select(Deal).where(Deal.number.in_(numbers)).order_by(Deal.id).with_for_update()
    )).scalars().all()
    deals_by_number = {deal.number: deal for deal in deals}
    if len(deals_by_number) != len(numbers):
        raise ValueError("BITRIX_STAGE_HISTORY_INVALID")
    refs = [event["source_ref"] for event in events]
    existing_refs = set((await session.execute(
        select(DealStageEvent.source_ref).where(DealStageEvent.source_ref.in_(refs))
    )).scalars())
    for event in events:
        if event["source_ref"] in existing_refs:
            stats["stage_event_existing"] += 1
            continue
        session.add(DealStageEvent(
            deal_id=deals_by_number[event["number"]].id,
            source_ref=event["source_ref"],
            source_stage_id=event["source_stage_id"],
            source_category_id=event["source_category_id"],
            source_type_id=event["source_type_id"],
            source_semantic_id=event["source_semantic_id"],
            from_stage=event["from_stage"],
            to_stage=event["to_stage"],
            changed_by=event["changed_by"],
            changed_at=event["changed_at"],
        ))
        stats["stage_event"] += 1


def _prepare_bitrix_timeline_comments(
    deal_rows: list[dict],
    lead_rows: list[dict],
    comment_rows: list[dict],
    user_rows: list[dict],
    *,
    allow_files: bool = False,
) -> dict[str, object]:
    """Validate source comments and exact imported-owner identities before writes."""
    invalid = ValueError("BITRIX_TIMELINE_COMMENTS_INVALID")

    def source_owners(rows: list[dict], entity_type: str) -> dict[str, dict]:
        owners: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise invalid
            try:
                owner_id = _canonical_positive_id(row.get("ID"))
            except ValueError:
                raise invalid from None
            previous = owners.get(owner_id)
            if previous is not None and previous != row:
                raise invalid
            owners[owner_id] = row
        return owners

    all_deal_owners = source_owners(deal_rows, "deal")
    supported_deal_owners = {
        owner_id: row
        for owner_id, row in all_deal_owners.items()
        if not isinstance(row.get("CATEGORY_ID"), bool)
        and str(row.get("CATEGORY_ID") or "0") in {"0", "7"}
    }
    lead_owners = source_owners(lead_rows, "lead")
    user_displays: dict[str, set[str]] = {}
    for user in user_rows:
        if not isinstance(user, dict):
            continue
        try:
            user_id = _canonical_positive_id(user.get("ID"))
        except ValueError:
            continue
        display = f"{user.get('NAME') or ''} {user.get('LAST_NAME') or ''}".strip()[:128]
        user_displays.setdefault(user_id, set()).add(display)

    prepared_comments: list[dict] = []
    expected_semantics: dict[str, tuple] = {}
    seen_identity: set[tuple[str, str]] = set()
    for row in comment_rows:
        if not isinstance(row, dict):
            raise invalid
        entity_type = row.get("ENTITY_TYPE")
        if not isinstance(entity_type, str) or entity_type not in {"deal", "lead"}:
            raise invalid
        try:
            row_id = _canonical_positive_id(row.get("ID"))
            owner_id = _canonical_positive_id(row.get("ENTITY_ID"))
        except ValueError:
            raise invalid from None
        identity = (entity_type, row_id)
        if identity in seen_identity:
            raise invalid
        seen_identity.add(identity)
        owner_rows = supported_deal_owners if entity_type == "deal" else lead_owners
        if owner_id not in owner_rows:
            raise invalid

        files = row.get("FILES")
        if not isinstance(files, dict) or (files and not allow_files):
            raise invalid
        for file_id, file_row in files.items():
            try:
                canonical_file_id = _canonical_positive_id(file_id)
                nested_file_id = _canonical_positive_id(
                    file_row.get("id") if isinstance(file_row, dict) else None
                )
            except ValueError:
                raise invalid from None
            if canonical_file_id != nested_file_id:
                raise invalid
        body = row.get("COMMENT")
        if not isinstance(body, str):
            raise invalid
        created_at = _bitrix_stage_datetime(row.get("CREATED"))
        if created_at is None:
            raise invalid

        raw_author_id = row.get("AUTHOR_ID")
        if isinstance(raw_author_id, bool):
            raise invalid
        if raw_author_id is None or raw_author_id == "":
            author_source_id = None
        elif (type(raw_author_id) is int and raw_author_id == 0) or raw_author_id == "0":
            author_source_id = "0"
        else:
            try:
                author_source_id = _canonical_positive_id(raw_author_id)
            except ValueError:
                raise invalid from None
        displays = user_displays.get(author_source_id or "", set())
        if len(displays) > 1:
            raise invalid
        author_display = next(iter(displays), "")

        owner_identity = f"{entity_type}:{owner_id}"
        source_ref = f"{_BITRIX_TIMELINE_COMMENT_PREFIX}{entity_type}:{row_id}"
        if len(source_ref) > 128 or len(owner_id) > 64 or (
            author_source_id is not None and len(author_source_id) > 64
        ):
            raise invalid
        prepared = {
            "entity_type": entity_type,
            "row_id": row_id,
            "owner_id": owner_id,
            "owner_identity": owner_identity,
            "source_ref": source_ref,
            "author_source_id": author_source_id,
            "author_display": author_display,
            "body": body,
            "created_at": created_at,
        }
        prepared_comments.append(prepared)
        expected_semantics[source_ref] = (
            entity_type,
            owner_id,
            owner_identity,
            author_source_id,
            author_display,
            body,
            created_at,
        )

    prepared_comments.sort(
        key=lambda item: (
            item["created_at"], item["entity_type"], int(item["row_id"])
        )
    )
    # Audit every source owner, including currently unsupported deal categories,
    # so an imported comment cannot disappear from scope when its deal changes funnel.
    scope_owners = {
        ("deal", owner_id) for owner_id in all_deal_owners
    } | {("lead", owner_id) for owner_id in lead_owners}
    return {
        "comments": prepared_comments,
        "scope_owners": scope_owners,
        "expected_semantics": expected_semantics,
    }


def _prepare_bitrix_timeline_attachments(
    prepared_comments: dict[str, object],
    comment_rows: list[dict],
    link_rows: list[dict],
    inventory_rows: list[dict],
    cache_dir: Path,
) -> dict[str, object]:
    """Match every deal comment FILES id to one sealed binary and stable identity."""
    invalid = ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
    comment_by_identity = {
        (item["entity_type"], item["owner_id"], item["row_id"]): item
        for item in prepared_comments["comments"]
    }
    raw_comments: dict[tuple[str, str, str], dict] = {}
    for row in comment_rows:
        if not isinstance(row, dict):
            raise invalid
        try:
            key = (
                row.get("ENTITY_TYPE"),
                _canonical_positive_id(row.get("ENTITY_ID")),
                _canonical_positive_id(row.get("ID")),
            )
        except ValueError:
            raise invalid from None
        if key in raw_comments:
            raise invalid
        raw_comments[key] = row

    expected_links: dict[tuple[str, str, str, str], dict] = {}
    for identity, comment in comment_by_identity.items():
        raw = raw_comments.get(identity)
        if raw is None:
            raise invalid
        files = raw.get("FILES")
        if not isinstance(files, dict):
            raise invalid
        if comment["entity_type"] == "lead" and files:
            raise invalid
        for raw_file_id, file_row in files.items():
            try:
                file_id = _canonical_positive_id(raw_file_id)
                nested_file_id = _canonical_positive_id(
                    file_row.get("id") if isinstance(file_row, dict) else None
                )
            except ValueError:
                raise invalid from None
            if file_id != nested_file_id or comment["entity_type"] != "deal":
                raise invalid
            link_identity = ("deal", comment["owner_id"], comment["row_id"], file_id)
            if link_identity in expected_links:
                raise invalid
            expected_links[link_identity] = comment

    actual_links: dict[tuple[str, str, str, str], str] = {}
    for row in link_rows:
        if not isinstance(row, dict) or set(row) != {
            "source", "entity_type", "entity_id", "source_id", "file_id", "binary_key"
        }:
            raise invalid
        try:
            identity = (
                row.get("entity_type"),
                _canonical_positive_id(row.get("entity_id")),
                _canonical_positive_id(row.get("source_id")),
                _canonical_positive_id(row.get("file_id")),
            )
        except ValueError:
            raise invalid from None
        if (
            row.get("source") != "comment"
            or identity[0] != "deal"
            or row.get("binary_key") != f"disk:{identity[3]}"
            or identity in actual_links
        ):
            raise invalid
        actual_links[identity] = row["binary_key"]
    if set(actual_links) != set(expected_links):
        raise invalid

    inventory: dict[str, dict] = {}
    for row in inventory_rows:
        if not isinstance(row, dict):
            raise invalid
        key = row.get("key")
        if not isinstance(key, str) or key in inventory:
            raise invalid
        inventory[key] = row
    if set(inventory) != set(actual_links.values()):
        raise invalid

    attachments: list[dict] = []
    expected_semantics: dict[str, tuple] = {}
    for identity in sorted(expected_links, key=lambda item: tuple(map(int, item[1:]))):
        entity_type, owner_id, comment_id, file_id = identity
        binary_key = actual_links[identity]
        item = inventory.get(binary_key)
        if item is None:
            raise invalid
        filename = item.get("name") or "attachment"
        if not isinstance(filename, str) or len(filename) > 512:
            raise invalid
        content_type = item.get("content_type")
        size = item.get("bytes")
        digest = item.get("sha256")
        cache_filename = item.get("filename")
        if (
            not isinstance(content_type, str)
            or len(content_type) > 255
            or type(size) is not int
            or not 0 <= size <= _MAX_PRIVATE_ATTACHMENT_BYTES
            or not isinstance(digest, str)
            or not _SHA256_HEX_RE.fullmatch(digest)
            or cache_filename != hashlib.sha256(binary_key.encode("ascii")).hexdigest() + ".bin"
        ):
            raise invalid
        source_ref = (
            f"{_BITRIX_TIMELINE_ATTACHMENT_PREFIX}deal:{owner_id}:{comment_id}:{file_id}"
        )
        comment = expected_links[identity]
        comment_ref = comment["source_ref"]
        if len(source_ref) > 255:
            raise invalid
        storage_path = f"{digest[:2]}/{digest[2:4]}/{digest}"
        source_path = cache_dir / "comment_binary_files" / cache_filename
        attachment = {
            "source_ref": source_ref,
            "owner_id": owner_id,
            "comment_id": comment_id,
            "comment_ref": comment_ref,
            "file_id": file_id,
            "binary_key": binary_key,
            "source_path": source_path,
            "sha256": digest,
            "size_bytes": size,
            "filename": filename,
            "content_type": content_type,
            "storage_path": storage_path,
        }
        attachments.append(attachment)
        expected_semantics[source_ref] = (
            comment_ref,
            "deal",
            owner_id,
            f"BX-{owner_id}",
            file_id,
            digest,
            size,
            filename,
            content_type,
            storage_path,
            True,
        )
    return {"attachments": attachments, "expected_semantics": expected_semantics}


def _bitrix_timeline_comment_semantics(
    comment, deal_number: str | None, lead_message: str | None
) -> tuple:
    if comment.entity_type == "deal" and isinstance(deal_number, str):
        match = re.fullmatch(r"BX-([1-9][0-9]*)", deal_number)
        owner_id = match.group(1) if match else None
    elif comment.entity_type == "lead" and isinstance(lead_message, str):
        match = re.fullmatch(re.escape(LEAD_IMPORT_MARKER) + r"([1-9][0-9]*)", lead_message)
        owner_id = match.group(1) if match else None
    else:
        owner_id = None
    owner_identity = (
        f"{comment.entity_type}:{owner_id}" if owner_id is not None else None
    )
    return (
        comment.entity_type,
        comment.source_entity_id,
        owner_identity,
        comment.author_source_id,
        comment.author_display or "",
        comment.body,
        comment.created_at,
    )


async def _validate_existing_bitrix_timeline_comments(
    session, prepared: dict[str, object]
) -> None:
    """Reject stale source refs and destination edits before any load mutation."""
    from modules.leads.models import Lead
    from modules.sales.models import CrmTimelineComment, Deal

    expected = prepared["expected_semantics"]
    scope_owners = prepared["scope_owners"]
    rows = (await session.execute(
        select(CrmTimelineComment, Deal.number, Lead.message)
        .outerjoin(Deal, Deal.id == CrmTimelineComment.deal_id)
        .outerjoin(Lead, Lead.id == CrmTimelineComment.lead_id)
        .where(CrmTimelineComment.source_ref.like(
            f"{_BITRIX_TIMELINE_COMMENT_PREFIX}%"
        ))
        .with_for_update(of=CrmTimelineComment)
    )).all()
    for comment, deal_number, lead_message in rows:
        source_ref = comment.source_ref or ""
        semantics = _bitrix_timeline_comment_semantics(
            comment, deal_number, lead_message
        )
        owner_match = re.fullmatch(r"(?:deal|lead):([1-9][0-9]*)", semantics[2] or "")
        actual_owner = (
            (comment.entity_type, owner_match.group(1)) if owner_match else None
        )
        if source_ref not in expected and actual_owner not in scope_owners:
            continue
        if expected.get(source_ref) != semantics:
            raise ValueError("BITRIX_TIMELINE_COMMENTS_INVALID")


async def _import_bitrix_timeline_comments(
    session, prepared: dict[str, object], stats: dict
) -> None:
    from modules.leads.models import Lead
    from modules.sales.models import CrmTimelineComment, Deal

    comments = prepared["comments"]
    if not comments:
        return
    deal_numbers = {
        f"BX-{item['owner_id']}"
        for item in comments if item["entity_type"] == "deal"
    }
    lead_markers = {
        f"{LEAD_IMPORT_MARKER}{item['owner_id']}"
        for item in comments if item["entity_type"] == "lead"
    }
    deals_by_number = {
        deal.number: deal
        for deal in (await session.execute(
            select(Deal).where(Deal.number.in_(deal_numbers)).with_for_update()
        )).scalars()
    } if deal_numbers else {}
    leads_by_marker = {
        lead.message: lead
        for lead in (await session.execute(
            select(Lead).where(Lead.message.in_(lead_markers)).with_for_update()
        )).scalars()
    } if lead_markers else {}
    if len(deals_by_number) != len(deal_numbers) or len(leads_by_marker) != len(lead_markers):
        raise ValueError("BITRIX_TIMELINE_COMMENTS_INVALID")
    source_refs = [item["source_ref"] for item in comments]
    existing_refs = set((await session.execute(
        select(CrmTimelineComment.source_ref).where(
            CrmTimelineComment.source_ref.in_(source_refs)
        )
    )).scalars())
    for item in comments:
        source_ref = item["source_ref"]
        if source_ref in existing_refs:
            stats["timeline_comment_existing"] += 1
            continue
        owner = (
            deals_by_number.get(f"BX-{item['owner_id']}")
            if item["entity_type"] == "deal"
            else leads_by_marker.get(f"{LEAD_IMPORT_MARKER}{item['owner_id']}")
        )
        if owner is None:
            raise ValueError("BITRIX_TIMELINE_COMMENTS_INVALID")
        session.add(CrmTimelineComment(
            entity_type=item["entity_type"],
            deal_id=owner.id if item["entity_type"] == "deal" else None,
            lead_id=owner.id if item["entity_type"] == "lead" else None,
            source_ref=source_ref,
            source_entity_id=item["owner_id"],
            author_source_id=item["author_source_id"],
            author_display=item["author_display"],
            body=item["body"],
            created_at=item["created_at"],
        ))
        stats["timeline_comment"] += 1


def _attachment_file_chunks(path: Path):
    """Open one staged regular file without following a symlink where supported."""
    if path.is_symlink():
        raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            while chunk := stream.read(1024 * 1024):
                yield chunk
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _store_bitrix_timeline_attachment_blobs(
    prepared: dict[str, object],
) -> dict[str, object]:
    """Persist verified source files by streaming; no attachment bytes enter RAM."""
    from modules.sales import timeline_storage

    stored_by_key: dict[str, object] = {}
    for item in prepared["attachments"]:
        key = item["binary_key"]
        if key in stored_by_key:
            continue
        try:
            stored = timeline_storage.store_attachment(
                _attachment_file_chunks(item["source_path"]),
                max_size_bytes=_MAX_PRIVATE_ATTACHMENT_BYTES,
            )
        except (OSError, TypeError, ValueError):
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID") from None
        if stored.sha256 != item["sha256"] or stored.size_bytes != item["size_bytes"]:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        if stored.storage_path != item["storage_path"]:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        stored_by_key[key] = stored
    return stored_by_key


async def _validate_existing_bitrix_timeline_attachments(
    session, prepared: dict[str, object]
) -> None:
    """Fail closed on stale or edited imported attachment rows before mutations."""
    from modules.sales import timeline_storage
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment, Deal

    expected = prepared["expected_semantics"]
    rows = (await session.execute(
        select(CrmTimelineAttachment, CrmTimelineComment, Deal.number)
        .outerjoin(CrmTimelineComment, CrmTimelineComment.id == CrmTimelineAttachment.comment_id)
        .outerjoin(Deal, Deal.id == CrmTimelineComment.deal_id)
        .where(CrmTimelineAttachment.source_ref.like(
            f"{_BITRIX_TIMELINE_ATTACHMENT_PREFIX}%"
        ))
        .with_for_update(of=CrmTimelineAttachment)
    )).all()
    seen_refs: set[str] = set()
    for attachment, comment, deal_number in rows:
        if comment is None:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        source_ref = attachment.source_ref or ""
        if source_ref in seen_refs:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        seen_refs.add(source_ref)
        expected_semantic = expected.get(source_ref)
        if expected_semantic is None:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        match = _BITRIX_TIMELINE_ATTACHMENT_SOURCE_RE.fullmatch(source_ref)
        if match is None:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        try:
            timeline_storage.verify_attachment(attachment)
        except (OSError, TypeError, ValueError):
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID") from None
        actual_semantic = (
            comment.source_ref,
            comment.entity_type,
            comment.source_entity_id,
            deal_number,
            match.group(3),
            attachment.sha256,
            attachment.size_bytes,
            attachment.filename,
            attachment.content_type,
            attachment.storage_path,
            True,
        )
        if actual_semantic != expected_semantic:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")


async def _import_bitrix_timeline_attachments(
    session, prepared: dict[str, object], stored_by_key: dict[str, object], stats: dict
) -> None:
    from modules.sales.models import CrmTimelineAttachment, CrmTimelineComment

    attachments = prepared["attachments"]
    if not attachments:
        return
    comment_refs = {item["comment_ref"] for item in attachments}
    comments_by_ref = {
        comment.source_ref: comment
        for comment in (await session.execute(
            select(CrmTimelineComment)
            .where(CrmTimelineComment.source_ref.in_(comment_refs))
            .with_for_update()
        )).scalars()
    }
    if set(comments_by_ref) != comment_refs:
        raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
    existing_refs = set((await session.execute(
        select(CrmTimelineAttachment.source_ref).where(
            CrmTimelineAttachment.source_ref.in_(
                [item["source_ref"] for item in attachments]
            )
        )
    )).scalars())
    for item in attachments:
        source_ref = item["source_ref"]
        if source_ref in existing_refs:
            stats["timeline_attachment_existing"] += 1
            continue
        stored = stored_by_key.get(item["binary_key"])
        if stored is None:
            raise ValueError("BITRIX_TIMELINE_ATTACHMENTS_INVALID")
        session.add(CrmTimelineAttachment(
            comment_id=comments_by_ref[item["comment_ref"]].id,
            source_ref=source_ref,
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            filename=item["filename"],
            content_type=item["content_type"],
            storage_path=stored.storage_path,
        ))
        stats["timeline_attachment"] += 1


async def _load_sales_prices(
    session, stats: dict, cache_snapshot: _PrivateCacheSnapshot | None = None
) -> None:
    """Цены подбора из строк реализаций 1С (последняя Цена за месяц на SKU)."""
    from datetime import timezone

    from modules.integrations.models import StockItem

    expected = _expected_stock_semantic_rows(
        _load_jsonl("onec_sku", cache_snapshot),
        _load_jsonl("onec_sales", cache_snapshot),
    )
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


async def _eligible_bitrix_employee_ids(session, portal_ids: Iterable[str], *, lock: bool) -> dict[str, int]:
    """Map exact Bitrix account IDs to active, unique CRM employee identities."""
    from fastapi import HTTPException

    from core.domain.models import User
    from core.services.crm_owners import resolve_crm_owner

    usernames = {
        f"bitrix:{portal_id}" for portal_id in portal_ids
        if portal_id not in ("", "0")
    }
    if not usernames:
        return {}
    users = (await session.execute(
        select(User).where(User.username.in_(usernames))
    )).scalars().all()
    eligible: dict[str, int] = {}
    for user in users:
        if user.employee_id is None:
            continue
        try:
            owner = await resolve_crm_owner(
                session, employee_id=user.employee_id, lock=lock
            )
        except HTTPException:
            continue
        if owner.id == user.id and owner.employee_id is not None:
            eligible[user.username.removeprefix("bitrix:")] = owner.employee_id
    return eligible


async def load() -> None:
    cache_snapshot = _require_isolated_cache_snapshot()
    cache_dir = cache_snapshot.cache_dir if cache_snapshot is not None else OUT_DIR

    def read_cache(name: str) -> list[dict]:
        return _load_jsonl(name, cache_snapshot)

    binary_cache_v2 = (
        cache_snapshot is not None
        and cache_snapshot.cache_format == _PRIVATE_CACHE_V2_FORMAT
    )
    # Register procurement metadata for isolated SQLite loads.
    import modules.procurement.receipt_documents  # noqa: F401
    from core.domain.models import Contact, Counterparty, CounterpartyAlias
    from modules.finance.models import Payment
    from modules.leads.models import Lead
    from modules.sales.models import CallLog, Deal

    user_source_rows = read_cache("bx_users")
    users = {u["ID"]: f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
             for u in user_source_rows}
    companies = {c["ID"]: c for c in read_cache("bx_companies")}
    contacts_bx = {c["ID"]: c for c in read_cache("bx_contacts")}
    raw_deal_source_rows = read_cache("bx_deals")
    deal_source_rows, duplicate_source_deals, conflicting_source_deals, missing_deal_ids = (
        _deduplicate_source_deals(raw_deal_source_rows)
    )
    call_source_rows = read_cache("bx_calls")
    prepared_call_deal_links = _prepare_bitrix_call_deal_links(
        call_source_rows, deal_source_rows
    )
    task_source_path = cache_dir / "bx_tasks.jsonl"
    task_source_available = (
        (cache_snapshot is not None and "bx_tasks" in cache_snapshot.entries)
        or task_source_path.is_file()
    )
    prepared_bitrix_tasks = (
        _prepare_bitrix_tasks(read_cache("bx_tasks"), raw_deal_source_rows)
        if task_source_available else None
    )
    onec_counterparties = read_cache("onec_counterparties")
    onec_sku_rows = read_cache("onec_sku")
    onec_sku_catalog = _prepare_onec_sku_catalog(onec_sku_rows)
    prepared_bitrix_items = _prepare_bitrix_deal_items(
        raw_deal_source_rows,
        read_cache("bx_product_rows"),
        read_cache("bx_products"),
        onec_sku_rows,
        require_complete=(
            cache_snapshot is not None
            or (cache_dir / "bx_product_rows.jsonl").is_file()
        ),
    )
    stage_history_path = cache_dir / "bx_stage_history.jsonl"
    prepared_bitrix_stage_history = (
        _prepare_bitrix_stage_history(
            raw_deal_source_rows, read_cache("bx_stage_history")
        )
        if (
            (cache_snapshot is not None and "bx_stage_history" in cache_snapshot.entries)
            or stage_history_path.is_file()
        )
        else None
    )
    timeline_comments_path = cache_dir / "bx_timeline_comments.jsonl"
    timeline_comment_rows = read_cache("bx_timeline_comments")
    prepared_bitrix_timeline_comments = (
        _prepare_bitrix_timeline_comments(
            raw_deal_source_rows,
            read_cache("bx_leads"),
            timeline_comment_rows,
            user_source_rows,
            allow_files=binary_cache_v2,
        )
        if (
            (cache_snapshot is not None and "bx_timeline_comments" in cache_snapshot.entries)
            or timeline_comments_path.is_file()
        )
        else None
    )
    prepared_bitrix_timeline_attachments = (
        _prepare_bitrix_timeline_attachments(
            prepared_bitrix_timeline_comments,
            timeline_comment_rows,
            read_cache("bx_comment_binary_links") if binary_cache_v2 else [],
            read_cache("bx_comment_binary_inventory") if binary_cache_v2 else [],
            cache_dir,
        )
        if prepared_bitrix_timeline_comments is not None
        else None
    )
    referenced_company_ids = (
        _nonempty_ids(deal_source_rows, "COMPANY_ID")
        | _nonempty_ids(contacts_bx.values(), "COMPANY_ID")
        | {
            str(row.get("CRM_ENTITY_ID"))
            for row in call_source_rows
            if row.get("CRM_ENTITY_TYPE") == "COMPANY"
            and row.get("CRM_ENTITY_ID") not in (None, "", "0")
        }
    )
    company_evidence, company_match_status = _company_1c_evidence(
        list(companies.values()),
        read_cache("bx_requisites"),
        onec_counterparties,
        referenced_company_ids=referenced_company_ids,
    )

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()  # dev-режим: создаст таблицы
    assert db.session_factory is not None

    async with db.session_factory() as s:
        if db.is_sqlite:
            # sqlite3's legacy transaction control does not begin a database
            # transaction for SELECT.  Without a real outer transaction, a
            # released SAVEPOINT can survive the later Session rollback.  It
            # also lets CRM API writers race the import's read/check/create.
            connection = await s.connection()
            raw_connection = await connection.get_raw_connection()
            if not raw_connection.driver_connection.in_transaction:
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
        onec_sku_existing = await _validate_existing_onec_sku_identities(
            s, onec_sku_catalog
        )
        await _validate_existing_bitrix_deal_item_rows(s, prepared_bitrix_items)
        if prepared_bitrix_tasks is not None:
            await _validate_existing_bitrix_tasks(s, prepared_bitrix_tasks)
        if prepared_bitrix_stage_history is not None:
            await _validate_existing_bitrix_stage_events(s, prepared_bitrix_stage_history)
        if prepared_bitrix_timeline_comments is not None:
            await _validate_existing_bitrix_timeline_comments(
                s, prepared_bitrix_timeline_comments
            )
        if prepared_bitrix_timeline_attachments is not None:
            await _validate_existing_bitrix_timeline_attachments(
                s, prepared_bitrix_timeline_attachments
            )
        stored_bitrix_timeline_attachments = (
            _store_bitrix_timeline_attachment_blobs(
                prepared_bitrix_timeline_attachments
            )
            if prepared_bitrix_timeline_attachments is not None
            else {}
        )
        # --- контрагенты: эталон по УНП, привязка внешних id через alias ---
        alias_rows = {(a.source, a.external_ref): a
                      for a in (await s.execute(select(CounterpartyAlias))).scalars()}
        aliases = {key: row.counterparty_id for key, row in alias_rows.items()}
        cps = (await s.execute(select(Counterparty))).scalars().all()
        by_unp: dict[str, list[Counterparty]] = {}
        for row in cps:
            normalized = str(row.unp or "").strip()
            if normalized:
                by_unp.setdefault(normalized, []).append(row)
        stats = {k: 0 for k in ("counterparty", "contact", "deal", "lead", "call",
                                "payment", "sku", "deal_item", "deal_item_existing",
                                "stock_price", "stock_price_updated",
                                "date_fallback", "counterparty_unp_enrichments",
                                "counterparty_unp_conflicts",
                                "counterparty_ambiguous_name_conflicts",
                                "counterparty_ambiguous_1c_unps",
                                "counterparty_1c_ref_splits",
                                "counterparty_1c_name_promotions", "crm_client_links",
                                "crm_contact_links", "crm_directory_ambiguous",
                                "crm_directory_conflicts", "crm_directory_unmatched",
                                "crm_directory_contact_pair_conflicts",
                                "crm_clients_created", "crm_client_contacts_created",
                                "stage_event", "stage_event_existing",
                                "timeline_comment", "timeline_comment_existing",
                                "timeline_attachment", "timeline_attachment_existing",
                                "task", "task_existing", "task_link")}
        stats["duplicate_source_deals"] = duplicate_source_deals
        stats["conflicting_source_deals"] = conflicting_source_deals
        stats["source_deals_missing_id"] = missing_deal_ids

        def promote_legacy_bitrix_master_to_1c(cp: Counterparty, canonical_name: str) -> None:
            """Correct a previously imported Bitrix name only when 1C now proves it."""
            provenance = dict(cp.provenance or {})
            name_source = (provenance.get("name") or {}).get("source")
            canonical_name = (canonical_name or "").strip()[:255]
            if name_source in {"bitrix", "1c"} and canonical_name and cp.name != canonical_name:
                cp.name = canonical_name
                provenance["name"] = {"source": "1c", "at": LABEL}
                cp.provenance = provenance
                stats["counterparty_1c_name_promotions"] += 1

        def _dt_or_nov1(iso: str | None) -> datetime:
            """Дата или 1 ноября с явным счётчиком фолбэков (не искажать данные молча)."""
            dt = _naive(iso)
            if dt is None:
                stats["date_fallback"] += 1
                return datetime.fromisoformat(FROM_ISO)
            return dt

        onec_refs_by_unp: dict[str, set[str]] = {}
        for row in onec_counterparties:
            ref = str(row.get("Ref_Key") or "")
            unp = _valid_unp(row.get("ИНН"))
            if ref and unp:
                onec_refs_by_unp.setdefault(unp, set()).add(ref)
        existing_1c_refs_by_unp: dict[str, set[str]] = {}
        counters_by_id = {row.id: row for row in cps}
        for (source, ref), alias in alias_rows.items():
            if source != "1c":
                continue
            master = counters_by_id.get(alias.counterparty_id)
            master_unp = _valid_unp(master.unp) if master is not None else None
            if master_unp:
                existing_1c_refs_by_unp.setdefault(master_unp, set()).add(ref)
        preferred_1c_ref_by_unp = {
            unp: min(existing_1c_refs_by_unp.get(unp) or refs)
            for unp, refs in onec_refs_by_unp.items()
        }
        duplicate_1c_unp_refs = {
            unp: refs for unp, refs in onec_refs_by_unp.items() if len(refs) > 1
        }
        duplicate_1c_master_claims: dict[int, str] = {}
        stats["counterparty_ambiguous_1c_unps"] = len(duplicate_1c_unp_refs)

        async def upsert_cp(
            source: str,
            ext: str,
            name: str,
            unp: str | None,
            *,
            preserve_identity: bool = False,
            identity_unp: str | None = None,
        ) -> Counterparty:
            name = (name or "").strip()
            incoming_unp = str(unp or "").strip() or None
            observed_identity_unp = str(identity_unp or "").strip() or None
            key = (source, ext)

            if preserve_identity:
                if key in aliases:
                    cp = await s.get(Counterparty, aliases[key])
                    if cp is None:
                        stats["counterparty_unp_conflicts"] += 1
                        raise RuntimeError(
                            "counterparty alias points to a missing master; transaction rolled back"
                        )
                    current_unp = str(cp.unp or "").strip() or None
                    if (
                        observed_identity_unp
                        and current_unp
                        and observed_identity_unp != current_unp
                    ):
                        stats["counterparty_unp_conflicts"] += 1
                        raise RuntimeError(
                            "counterparty alias UNP conflict; transaction rolled back"
                        )
                    claimed_ref = duplicate_1c_master_claims.get(cp.id)
                    if claimed_ref and claimed_ref != ext:
                        cp = Counterparty(
                            name=name, unp=None,
                            provenance={"name": {"source": "1c", "at": LABEL}},
                        )
                        s.add(cp)
                        await s.flush()
                        alias_rows[key].counterparty_id = cp.id
                        aliases[key] = cp.id
                        stats["counterparty"] += 1
                        stats["counterparty_1c_ref_splits"] += 1
                    else:
                        promote_legacy_bitrix_master_to_1c(cp, name)
                    duplicate_1c_master_claims[cp.id] = ext
                    return cp

                cp = Counterparty(
                    name=name, unp=None,
                    provenance={"name": {"source": "1c", "at": LABEL}},
                )
                s.add(cp)
                await s.flush()
                alias = CounterpartyAlias(counterparty_id=cp.id, source=source, external_ref=ext)
                s.add(alias)
                alias_rows[key] = alias
                aliases[key] = cp.id
                duplicate_1c_master_claims[cp.id] = ext
                stats["counterparty"] += 1
                return cp

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
                if source == "1c":
                    promote_legacy_bitrix_master_to_1c(cp, name)
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
                # A new 1C Ref_Key never inherits a master by name.
            # Bitrix name matching is resolved separately through unique 1C evidence.

            if cp is None:
                prov = {"name": {"source": source, "at": LABEL}}
                if incoming_unp:
                    prov["unp"] = {"source": source, "at": LABEL}
                cp = Counterparty(name=name, unp=incoming_unp, provenance=prov)
                s.add(cp)
                await s.flush()
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
            if source == "1c":
                promote_legacy_bitrix_master_to_1c(cp, name)
            alias = CounterpartyAlias(counterparty_id=cp.id, source=source, external_ref=ext)
            s.add(alias)
            alias_rows[key] = alias
            aliases[key] = cp.id
            return cp

        onec_counterparty_ids: dict[str, int] = {}
        onec_cp_names: dict[str, str] = {}
        for row in sorted(onec_counterparties, key=lambda item: str(item.get("Ref_Key") or "")):
            name = (row.get("Description") or "").strip()[:255] or "Без имени"
            unp = (row.get("ИНН") or "").strip() or None
            ref = str(row.get("Ref_Key") or "")
            if not ref:
                continue
            valid_unp = _valid_unp(unp)
            duplicate_refs = duplicate_1c_unp_refs.get(valid_unp or "", set())
            preferred_ref = preferred_1c_ref_by_unp.get(valid_unp or "")
            preserve_ref_identity = bool(preferred_ref and ref != preferred_ref)
            cp = await upsert_cp(
                "1c", ref, name, unp if not preserve_ref_identity else None,
                preserve_identity=preserve_ref_identity,
                identity_unp=unp,
            )
            if len(duplicate_refs) > 1:
                duplicate_1c_master_claims[cp.id] = ref
            onec_counterparty_ids[ref] = cp.id
            onec_cp_names[ref] = cp.name

        # Bitrix company ids are retained only as aliases to a uniquely matched 1C
        # master.  A Bitrix title or requisites never create/update Counterparty.
        cp_by_bx_company: dict[str, Counterparty] = {}
        for cid, evidence in company_evidence.items():
            cp_id = onec_counterparty_ids.get(evidence["ref"])
            if cp_id is None:
                company_match_status[cid] = "missing_1c_master"
                continue
            cp = await s.get(Counterparty, cp_id)
            if cp is None:
                company_match_status[cid] = "missing_1c_master"
                continue
            expected_unp = _valid_unp(evidence.get("unp"))
            actual_unp_raw = str(cp.unp or "").strip()
            actual_unp = _valid_unp(cp.unp)
            match_method = evidence.get("match_method")
            if expected_unp and not actual_unp and (
                match_method != "name" or actual_unp_raw
            ):
                company_match_status[cid] = "master_unp_missing"
                stats["crm_directory_conflicts"] += 1
                continue
            if expected_unp and actual_unp and expected_unp != actual_unp:
                company_match_status[cid] = "master_unp_conflict"
                stats["crm_directory_conflicts"] += 1
                continue
            key = ("bitrix", f"company:{cid}")
            if key in aliases and aliases[key] != cp_id:
                company_match_status[cid] = "existing_alias_conflict"
                stats["crm_directory_conflicts"] += 1
                continue
            if key not in aliases:
                s.add(CounterpartyAlias(
                    counterparty_id=cp_id, source="bitrix", external_ref=f"company:{cid}"
                ))
                aliases[key] = cp_id
            cp_by_bx_company[cid] = cp
            company_match_status[cid] = "matched"

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
        assigned_bitrix_ids = {
            str(row.get("ASSIGNED_BY_ID") or "").strip()
            for row in deal_source_rows
            if str(row.get("CATEGORY_ID") or "0") in ("0", "7")
            and str(row.get("ASSIGNED_BY_ID") or "").strip() not in ("", "0")
        }
        call_portal_user_ids = {
            str(row.get("PORTAL_USER_ID") or "").strip()
            for row in call_source_rows
            if str(row.get("PORTAL_USER_ID") or "").strip() not in ("", "0")
        }
        eligible_employee_by_bitrix_id = await _eligible_bitrix_employee_ids(
            s, assigned_bitrix_ids | call_portal_user_ids, lock=True
        )
        new_deal_owner_ids = {
            str(row.get("ID") or ""): eligible_employee_by_bitrix_id[
                str(row.get("ASSIGNED_BY_ID") or "").strip()
            ]
            for row in deal_source_rows
            if str(row.get("CATEGORY_ID") or "0") in ("0", "7")
            and str(row.get("ASSIGNED_BY_ID") or "").strip()
            in eligible_employee_by_bitrix_id
        }
        directory_links = await _resolve_crm_directory_links(
            s, deal_source_rows, contacts_bx,
            cp_by_bx_company, company_match_status,
            new_deal_owner_ids=new_deal_owner_ids,
            create_missing_directory=True,
        )
        skipped_categories: dict[str, int] = {}
        for d in deal_source_rows:
            cat = str(d.get("CATEGORY_ID") or "0")
            if cat not in ("0", "7"):
                skipped_categories[cat] = skipped_categories.get(cat, 0) + 1
                continue
            number = f"BX-{d['ID']}"
            link = directory_links[number]
            existing_deal = link["deal"]
            expected_client_id = link["expected_client_id"]
            expected_contact_id = link["expected_contact_id"]
            if existing_deal is not None:
                if link["existing_contact_pair_status"] != "none":
                    # Hold an inconsistent stored pair. Attaching a newly matched
                    # client could silently change which client owns that contact.
                    stats["crm_directory_contact_pair_conflicts"] += 1
                    stats["crm_directory_conflicts"] += 1
                    continue
                if expected_client_id is not None:
                    if existing_deal.crm_client_id is None:
                        existing_deal.crm_client_id = expected_client_id
                        stats["crm_client_links"] += 1
                    elif existing_deal.crm_client_id != expected_client_id:
                        stats["crm_directory_conflicts"] += 1
                if (
                    expected_contact_id is not None
                    and existing_deal.crm_client_id == expected_client_id
                ):
                    if existing_deal.crm_contact_id is None:
                        existing_deal.crm_contact_id = expected_contact_id
                        stats["crm_contact_links"] += 1
                    elif existing_deal.crm_contact_id != expected_contact_id:
                        stats["crm_directory_conflicts"] += 1
                if link["client_status"] in {"client_ambiguous", "client_identity_conflict"}:
                    stats["crm_directory_ambiguous"] += 1
                elif link["client_status"] != "matched":
                    stats["crm_directory_unmatched"] += 1
                continue
            stage, funnel, lost_comment = _map_deal_stage(str(d.get("STAGE_ID") or ""), cat)
            comp = cp_by_bx_company.get(str(d.get("COMPANY_ID") or ""))
            cp_name = comp.name if comp else "Не указан"
            created = _dt_or_nov1(d.get("DATE_CREATE"))
            closed = _naive(d.get("CLOSEDATE"))
            terminal = stage in ("won", "lost", "rp_won", "rp_lost")
            s.add(Deal(
                number=number, title=(d.get("TITLE") or number)[:255],
                counterparty=cp_name[:255] or "Не указан",
                amount=_dec(d.get("OPPORTUNITY")), stage=stage, funnel=funnel,
                owner=users.get(str(d.get("ASSIGNED_BY_ID") or ""), "")[:128],
                owner_id=link["expected_owner_id"],
                crm_client_id=expected_client_id,
                crm_contact_id=expected_contact_id,
                deal_date=str(created.date()),
                closed_date=str(closed.date()) if (terminal and closed) else None,
                created_at=created, stage_changed_at=(closed if terminal and closed else created),
                lost_comment=lost_comment,
            ))
            stats["deal"] += 1
            stats["crm_client_links"] += int(expected_client_id is not None)
            stats["crm_contact_links"] += int(expected_contact_id is not None)
            stats["crm_clients_created"] = stats.get("crm_clients_created", 0) + int(
                link["client_created"]
            )
            stats["crm_client_contacts_created"] = (
                stats.get("crm_client_contacts_created", 0)
                + int(link["contact_created"])
            )
            if link["client_status"] in {"client_ambiguous", "client_identity_conflict"}:
                stats["crm_directory_ambiguous"] += 1
            elif link["client_status"] != "matched":
                stats["crm_directory_unmatched"] += 1

        # --- задачи Bitrix: source ID и упорядоченные CRM bindings ---
        if prepared_bitrix_tasks is not None:
            await s.flush()
            task_deal_numbers = {
                number
                for source_task in prepared_bitrix_tasks["tasks"]
                for number in (
                    [source_task["deal_number"]]
                    + [link["deal_number"] for link in source_task["links"]]
                )
                if number is not None
            }
            task_deals_by_number = {
                deal.number: deal
                for deal in (await s.execute(
                    select(Deal).where(Deal.number.in_(task_deal_numbers))
                )).scalars()
            } if task_deal_numbers else {}
            if task_deal_numbers - set(task_deals_by_number):
                raise ValueError("BITRIX_TASK_DEAL_UNRESOLVED")
            await _import_bitrix_tasks(
                s, prepared_bitrix_tasks, task_deals_by_number, stats
            )

        # --- лиды Bitrix ---
        existing_leads = set(
            (await s.execute(select(Lead.message).where(Lead.message.like(f"{LEAD_IMPORT_MARKER}%")))).scalars()
        )
        for ld in read_cache("bx_leads"):
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
        call_deal_numbers = {
            number for number in prepared_call_deal_links.values() if number is not None
        }
        call_deal_source_rows = {
            f"BX-{row['ID']}": row for row in deal_source_rows
            if str(row.get("CATEGORY_ID") or "0") in ("0", "7")
        }
        call_deals_by_number: dict[str, Deal] = {}
        if call_deal_numbers:
            await s.flush()
            call_deals_by_number = {
                deal.number: deal
                for deal in (await s.execute(
                    select(Deal).where(Deal.number.in_(call_deal_numbers))
                )).scalars()
            }
            if call_deal_numbers - set(call_deals_by_number):
                raise ValueError("BITRIX_CALL_DEAL_UNRESOLVED")
        existing_calls = {
            row.call_id: row
            for row in (await s.execute(select(CallLog))).scalars()
        }
        for c in call_source_rows:
            call_id = _canonical_bitrix_call_id(c)
            started = _dt_or_nov1(c.get("CALL_START_DATE"))
            duration = int(c.get("CALL_DURATION") or 0)
            answered = str(c.get("CALL_FAILED_CODE") or "") == "200" and duration > 0
            ent_type, ent_id = c.get("CRM_ENTITY_TYPE"), str(c.get("CRM_ENTITY_ID") or "")
            deal_number = prepared_call_deal_links.get(call_id)
            call_deal = call_deals_by_number.get(deal_number) if deal_number else None
            counterparty_id = (
                cp_by_bx_company[ent_id].id
                if ent_type == "COMPANY" and ent_id in cp_by_bx_company
                else cp_by_bx_contact.get(ent_id) if ent_type == "CONTACT" else None
            )
            if ent_type == "DEAL" and deal_number is not None:
                deal_source = call_deal_source_rows.get(deal_number)
                source_company_id = str(deal_source.get("COMPANY_ID") or "") if deal_source else ""
                matched_company = cp_by_bx_company.get(source_company_id)
                counterparty_id = matched_company.id if matched_company is not None else None
            contact_id = contact_id_map.get(ent_id) if ent_type == "CONTACT" else None
            call_values = {
                "direction": "out" if str(c.get("CALL_TYPE")) in ("1", "4") else "in",
                "phone_e164": (c.get("PHONE_NUMBER") or "")[:32] or None,
                "owner": users.get(str(c.get("PORTAL_USER_ID") or ""), "")[:128],
                "owner_id": eligible_employee_by_bitrix_id.get(
                    str(c.get("PORTAL_USER_ID") or "").strip()
                ),
                "counterparty_id": counterparty_id,
                "contact_id": contact_id,
                "deal_id": call_deal.id if call_deal is not None else None,
                "status": "ended" if answered else "missed",
                "recording_url": (c.get("CALL_RECORD_URL") or "")[:255] or None,
                "started_at": started,
                "answered_at": started if answered else None,
                "ended_at": started + timedelta(seconds=duration),
                "duration_sec": duration or None,
            }
            existing_call = existing_calls.get(call_id)
            if existing_call is not None:
                if any(
                    getattr(existing_call, field) != value
                    for field, value in call_values.items()
                ):
                    raise ValueError("BITRIX_CALL_CONFLICT")
                continue
            imported_call = CallLog(call_id=call_id, **call_values)
            s.add(imported_call)
            existing_calls[call_id] = imported_call
            stats["call"] += 1

        # --- реализации 1С -> finance.payment (выручка по факту отгрузки) ---
        existing_refs = set((await s.execute(select(Payment.entity_ref))).scalars())
        for doc in read_cache("onec_sales"):
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

        # --- номенклатура 1С -> SKU по подтверждённой identity Ref_Key ---
        _upsert_onec_sku_rows(s, onec_sku_catalog, onec_sku_existing, stats)

        await s.flush()
        await _import_bitrix_deal_items(s, prepared_bitrix_items, stats)
        await _load_sales_prices(s, stats, cache_snapshot)
        if prepared_bitrix_stage_history is not None:
            await _import_bitrix_stage_history(s, prepared_bitrix_stage_history, stats)
        if prepared_bitrix_timeline_comments is not None:
            await _import_bitrix_timeline_comments(
                s, prepared_bitrix_timeline_comments, stats
            )
            await s.flush()
        if prepared_bitrix_timeline_attachments is not None:
            await _import_bitrix_timeline_attachments(
                s,
                prepared_bitrix_timeline_attachments,
                stored_bitrix_timeline_attachments,
                stats,
            )

        await s.commit()

    await db.disconnect()
    if skipped_categories:
        print("load: пропущены сделки не-продажных воронок Bitrix:", skipped_categories)
    print("load: добавлено —", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def load_prices() -> None:
    """Только цены подбора из кэша реализаций (без Bitrix/лидов)."""
    cache_snapshot = _require_isolated_cache_snapshot()

    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    async with db.session_factory() as s:
        stats = {"stock_price": 0, "stock_price_updated": 0}
        await _load_sales_prices(s, stats, cache_snapshot)
        await s.commit()
    await db.disconnect()
    print("load-prices:", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def load_onec() -> None:
    """Sku + StockItem.price из кэша 1С (без Bitrix). Идемпотентно."""
    cache_snapshot = _require_isolated_cache_snapshot()
    from core.domain.models import Sku as Sku

    onec_sku_catalog = _prepare_onec_sku_catalog(
        _load_jsonl("onec_sku", cache_snapshot)
    )
    db = _isolated_database()
    if db.is_sqlite:
        await db.connect()
    assert db.session_factory is not None
    stats = {"sku": 0, "stock_price": 0, "stock_price_updated": 0}
    async with db.session_factory() as s:
        if db.is_sqlite:
            connection = await s.connection()
            raw_connection = await connection.get_raw_connection()
            if not raw_connection.driver_connection.in_transaction:
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
        existing_sku = await _validate_existing_onec_sku_identities(s, onec_sku_catalog)
        _upsert_onec_sku_rows(s, onec_sku_catalog, existing_sku, stats)
        await _load_sales_prices(s, stats, cache_snapshot)
        await s.commit()
    await db.disconnect()
    print("load-onec:", ", ".join(f"{k}: {v}" for k, v in stats.items()))


async def _destination_reconciliation(
    db,
    source_report: dict,
    source_semantic_rows: dict[str, list[dict]] | None = None,
    detail_rows: list[dict] | None = None,
    source_identity_ids: dict[str, dict[str, str]] | None = None,
    bitrix_product_expected_semantics: dict[
        str, tuple[str, str, Decimal, Decimal | None]
    ] | None = None,
    bitrix_product_scope_deal_ids: set[str] | None = None,
    onec_sku_identity_expected: dict[str, dict[str, str]] | None = None,
    bitrix_stage_expected_semantics: dict[str, tuple] | None = None,
    bitrix_stage_scope_deal_ids: set[str] | None = None,
    bitrix_timeline_comment_expected_semantics: dict[str, tuple] | None = None,
    bitrix_timeline_comment_scope_owners: set[tuple[str, str]] | None = None,
    bitrix_timeline_attachment_expected_semantics: dict[str, tuple] | None = None,
    cache_snapshot: _PrivateCacheSnapshot | None = None,
    bitrix_call_expected_deal_links: dict[str, str | None] | None = None,
    bitrix_task_expected_semantics: dict[str, tuple] | None = None,
) -> dict:
    from core.domain.models import Contact, Counterparty, CounterpartyAlias, Sku, User
    from modules.finance.models import Payment, PaymentAllocation
    from modules.integrations.models import StockItem
    from modules.leads.models import Lead
    from modules.sales.models import (
        Activity,
        CallLog,
        CrmTimelineAttachment,
        CrmTimelineComment,
        Deal,
        DealItem,
        DealStageEvent,
        DealTask,
        DealTaskCrmLink,
        Stage,
    )

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
    onec_sku_identity_expected = onec_sku_identity_expected or {}
    destination_task_semantic_rows = []
    async with db.session_factory() as session:
        if source_semantic_rows is not None:
            # Owner identity depends on the active 1C/CRM employee crosswalk in this DB.
            # Resolve it with the same rule as load so owner drift is visible in fidelity.
            call_portal_ids: dict[str, str] = {}
            for source_call in _load_jsonl("bx_calls", cache_snapshot):
                try:
                    call_id = _canonical_bitrix_call_id(source_call)
                except ValueError:
                    continue
                portal_id = str(source_call.get("PORTAL_USER_ID") or "").strip()
                call_portal_ids[call_id] = portal_id
            expected_owners = await _eligible_bitrix_employee_ids(
                session, call_portal_ids.values(), lock=False
            )
            for source_call in source_semantic_rows.get("bitrix_calls", []):
                source_call["owner_id"] = expected_owners.get(
                    call_portal_ids.get(source_call["identity"], "")
                )
            source_semantic["bitrix_calls"] = _semantic_summary(
                source_semantic_rows.get("bitrix_calls", [])
            )
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
            "deal_items_bitrix": await count(
                DealItem, DealItem.source_ref.like(f"{_BITRIX_DEAL_ITEM_PREFIX}%")
            ),
            "activities": await count(Activity),
            "stage_events": await count(DealStageEvent),
            "deal_tasks_bitrix": await count(
                DealTask, DealTask.source_ref.like(f"{_BITRIX_TASK_PREFIX}%")
            ),
            "deal_task_crm_links_bitrix": await count(
                DealTaskCrmLink,
                DealTaskCrmLink.task_id.in_(
                    select(DealTask.id).where(
                        DealTask.source_ref.like(f"{_BITRIX_TASK_PREFIX}%")
                    )
                ),
            ),
            "timeline_comments_bitrix": await count(
                CrmTimelineComment,
                CrmTimelineComment.source_ref.like(
                    f"{_BITRIX_TIMELINE_COMMENT_PREFIX}%"
                ),
            ),
            "timeline_attachments_bitrix": await count(
                CrmTimelineAttachment,
                CrmTimelineAttachment.source_ref.like(
                    f"{_BITRIX_TIMELINE_ATTACHMENT_PREFIX}%"
                ),
            ),
            "stages": await count(Stage),
        }

        bitrix_call_deal_source_ref_audit = None
        if bitrix_call_expected_deal_links is not None:
            expected_call_links = dict(bitrix_call_expected_deal_links)
            expected_call_ids = set(expected_call_links)
            if expected_call_ids:
                destination_call_links = (await session.execute(
                    select(CallLog.call_id, CallLog.deal_id, Deal.number)
                    .outerjoin(Deal, Deal.id == CallLog.deal_id)
                    .where(CallLog.call_id.in_(expected_call_ids))
                )).all()
            else:
                destination_call_links = []
            destination_links: dict[str, str | None] = {}
            orphan_destination_rows = 0
            duplicate_destination_keys = 0
            for call_id, deal_id, deal_number in destination_call_links:
                if call_id in destination_links:
                    duplicate_destination_keys += 1
                if deal_id is not None and deal_number is None:
                    orphan_destination_rows += 1
                    destination_links[call_id] = "__orphan__"
                else:
                    destination_links[call_id] = deal_number
            destination_call_ids = set(destination_links)
            link_mismatches = sum(
                expected_call_id not in destination_call_ids
                or destination_links.get(expected_call_id)
                != expected_call_links.get(expected_call_id)
                for expected_call_id in expected_call_ids
            ) + len(destination_call_ids - expected_call_ids) + duplicate_destination_keys
            bitrix_call_deal_source_ref_audit = {
                "expected_keys": len(expected_call_ids),
                "destination_keys": len(destination_call_ids),
                "set_match": destination_call_ids == expected_call_ids,
                "semantic_match": link_mismatches == 0,
                "semantic_mismatches": link_mismatches,
                "orphan_destination_rows": orphan_destination_rows,
            }

        bitrix_task_source_ref_audit = None
        if bitrix_task_expected_semantics is not None:
            expected_task_semantics = dict(bitrix_task_expected_semantics)
            expected_task_refs = set(expected_task_semantics)
            destination_task_rows = (await session.execute(
                select(
                    DealTask.id,
                    DealTask.source_ref,
                    DealTask.title,
                    DealTask.description,
                    DealTask.description_in_bbcode,
                    DealTask.source_responsible_id,
                    DealTask.source_status_code,
                    DealTask.status,
                    DealTask.due_at,
                    DealTask.assignee_id,
                    DealTask.deal_id,
                    Deal.number,
                )
                .outerjoin(Deal, Deal.id == DealTask.deal_id)
                .where(DealTask.source_ref.like(f"{_BITRIX_TASK_PREFIX}%"))
            )).all()
            imported_task_ids = [row[0] for row in destination_task_rows]
            destination_task_semantics: dict[str, tuple] = {}
            duplicate_task_keys = 0
            orphan_task_rows = 0
            links_by_task: dict[int, list[tuple]] = {
                task_id: [] for task_id in imported_task_ids
            }
            orphan_link_rows = 0
            if imported_task_ids:
                destination_task_links = (await session.execute(
                    select(
                        DealTaskCrmLink.task_id,
                        DealTaskCrmLink.ordinal,
                        DealTaskCrmLink.raw_binding,
                        DealTaskCrmLink.entity_type,
                        DealTaskCrmLink.source_id,
                        DealTaskCrmLink.deal_id,
                        Deal.number,
                    )
                    .outerjoin(Deal, Deal.id == DealTaskCrmLink.deal_id)
                    .where(DealTaskCrmLink.task_id.in_(imported_task_ids))
                    .order_by(
                        DealTaskCrmLink.task_id,
                        DealTaskCrmLink.ordinal,
                        DealTaskCrmLink.id,
                    )
                )).all()
                for task_id, ordinal, raw_binding, entity_type, source_id, deal_id, deal_number in destination_task_links:
                    if deal_id is not None and deal_number is None:
                        deal_number = "__orphan__"
                        orphan_link_rows += 1
                    links_by_task.setdefault(task_id, []).append(
                        (ordinal, raw_binding, entity_type, source_id, deal_number)
                    )
            for (
                task_id, source_ref, title, description, description_in_bbcode,
                responsible_id, status_code, status, due_at, assignee_id,
                deal_id, deal_number,
            ) in destination_task_rows:
                if source_ref in destination_task_semantics:
                    duplicate_task_keys += 1
                if deal_id is not None and deal_number is None:
                    deal_number = "__orphan__"
                    orphan_task_rows += 1
                destination_task_semantics[source_ref] = (
                    title,
                    description,
                    description_in_bbcode,
                    responsible_id,
                    status_code,
                    status,
                    due_at,
                    assignee_id,
                    deal_number,
                    tuple(links_by_task.get(task_id, [])),
                )
            destination_task_refs = set(destination_task_semantics)
            task_mismatches = sum(
                destination_task_semantics.get(source_ref) != semantics
                for source_ref, semantics in expected_task_semantics.items()
            )
            task_mismatches += len(destination_task_refs - expected_task_refs)
            task_mismatches += duplicate_task_keys + orphan_task_rows + orphan_link_rows
            bitrix_task_source_ref_audit = {
                "expected_keys": len(expected_task_refs),
                "destination_keys": len(destination_task_refs),
                "set_match": destination_task_refs == expected_task_refs
                and duplicate_task_keys == 0,
                "semantic_match": task_mismatches == 0,
                "semantic_mismatches": task_mismatches,
                "orphan_destination_rows": orphan_task_rows + orphan_link_rows,
            }
            destination_task_semantic_rows = [
                {
                    "identity": source_ref,
                    "title": title,
                    "description": description,
                    "description_in_bbcode": description_in_bbcode,
                    "source_responsible_id": responsible_id,
                    "source_status_code": status_code,
                    "status": status,
                    "due_at": due_at,
                    "assignee_id": assignee_id,
                    "deal_number": (
                        None if deal_number == "__orphan__" else deal_number
                    ),
                    "links": links_by_task.get(task_id, []),
                }
                for (
                    task_id, source_ref, title, description, description_in_bbcode,
                    responsible_id, status_code, status, due_at, assignee_id,
                    _, deal_number,
                ) in destination_task_rows
            ]

        bitrix_product_source_ref_audit = None
        if (
            bitrix_product_expected_semantics is not None
            and bitrix_product_scope_deal_ids is not None
        ):
            scope_numbers = {
                f"BX-{deal_id}" for deal_id in bitrix_product_scope_deal_ids
            }
            if scope_numbers:
                destination_product_rows = (await session.execute(
                    select(
                        DealItem.source_ref,
                        Deal.number,
                        Sku.code,
                        DealItem.qty,
                        DealItem.unit_price,
                    )
                    .join(Deal, Deal.id == DealItem.deal_id)
                    .outerjoin(Sku, Sku.id == DealItem.sku_id)
                    .where(
                        DealItem.source_ref.like(f"{_BITRIX_DEAL_ITEM_PREFIX}%"),
                    )
                )).all()
            else:
                destination_product_rows = []
            scoped_destination_product_rows = []
            for product_row in destination_product_rows:
                source_ref, deal_number, _, _, _ = product_row
                match = _BITRIX_DEAL_ITEM_SOURCE_RE.fullmatch(source_ref or "")
                if (
                    deal_number in scope_numbers
                    or (match and match.group(1) in bitrix_product_scope_deal_ids)
                ):
                    scoped_destination_product_rows.append(product_row)
            destination_product_semantics = {
                source_ref: (deal_number, sku_code, quantity, unit_price)
                for source_ref, deal_number, sku_code, quantity, unit_price
                in scoped_destination_product_rows
            }
            expected_refs = set(bitrix_product_expected_semantics)
            destination_refs = set(destination_product_semantics)
            semantic_mismatches = sum(
                expected_ref not in destination_refs
                or destination_product_semantics.get(expected_ref)
                != bitrix_product_expected_semantics.get(expected_ref)
                for expected_ref in expected_refs
            ) + len(destination_refs - expected_refs)
            bitrix_product_source_ref_audit = {
                "expected_keys": len(expected_refs),
                "destination_keys": len(destination_refs),
                "set_match": destination_refs == expected_refs,
                "semantic_match": semantic_mismatches == 0,
                "semantic_mismatches": semantic_mismatches,
            }

        bitrix_stage_history_source_ref_audit = None
        if (
            bitrix_stage_expected_semantics is not None
            and bitrix_stage_scope_deal_ids is not None
        ):
            expected_stage_refs = set(bitrix_stage_expected_semantics)
            scope_numbers = {
                f"BX-{deal_id}" for deal_id in bitrix_stage_scope_deal_ids
            }
            imported_stage_rows = (await session.execute(
                select(DealStageEvent, Deal.number)
                .join(Deal, Deal.id == DealStageEvent.deal_id)
                .where(
                    DealStageEvent.source_ref.like(f"{_BITRIX_STAGE_EVENT_PREFIX}%")
                )
            )).all()
            scoped_stage_rows = []
            for event, deal_number in imported_stage_rows:
                source_ref = event.source_ref or ""
                match = _BITRIX_STAGE_EVENT_SOURCE_RE.fullmatch(source_ref)
                if (
                    deal_number in scope_numbers
                    or source_ref in expected_stage_refs
                    or (match and match.group(1) in bitrix_stage_scope_deal_ids)
                ):
                    scoped_stage_rows.append((event, deal_number))
            destination_stage_semantics: dict[str, tuple] = {}
            duplicate_destination_refs = 0
            for event, deal_number in scoped_stage_rows:
                source_ref = event.source_ref or ""
                if source_ref in destination_stage_semantics:
                    duplicate_destination_refs += 1
                destination_stage_semantics[source_ref] = (
                    _bitrix_stage_event_semantics(event, deal_number)
                )
            destination_stage_refs = set(destination_stage_semantics)
            stage_semantic_mismatches = sum(
                expected_ref not in destination_stage_refs
                or destination_stage_semantics.get(expected_ref)
                != bitrix_stage_expected_semantics.get(expected_ref)
                for expected_ref in expected_stage_refs
            ) + len(destination_stage_refs - expected_stage_refs) + duplicate_destination_refs
            bitrix_stage_history_source_ref_audit = {
                "expected_keys": len(expected_stage_refs),
                "destination_keys": len(destination_stage_refs),
                "destination_rows": len(scoped_stage_rows),
                "set_match": destination_stage_refs == expected_stage_refs,
                "semantic_match": stage_semantic_mismatches == 0,
                "semantic_mismatches": stage_semantic_mismatches,
            }

        bitrix_timeline_comment_source_ref_audit = None
        if (
            bitrix_timeline_comment_expected_semantics is not None
            and bitrix_timeline_comment_scope_owners is not None
        ):
            expected_comment_refs = set(bitrix_timeline_comment_expected_semantics)
            imported_comments = (await session.execute(
                select(CrmTimelineComment, Deal.number, Lead.message)
                .outerjoin(Deal, Deal.id == CrmTimelineComment.deal_id)
                .outerjoin(Lead, Lead.id == CrmTimelineComment.lead_id)
                .where(CrmTimelineComment.source_ref.like(
                    f"{_BITRIX_TIMELINE_COMMENT_PREFIX}%"
                ))
            )).all()
            scoped_comments = []
            for comment, deal_number, lead_message in imported_comments:
                source_ref = comment.source_ref or ""
                semantics = _bitrix_timeline_comment_semantics(
                    comment, deal_number, lead_message
                )
                owner_match = re.fullmatch(
                    r"(?:deal|lead):([1-9][0-9]*)", semantics[2] or ""
                )
                actual_owner = (
                    (comment.entity_type, owner_match.group(1)) if owner_match else None
                )
                if source_ref in expected_comment_refs or actual_owner in bitrix_timeline_comment_scope_owners:
                    scoped_comments.append((source_ref, semantics))
            destination_comment_semantics: dict[str, tuple] = {}
            duplicate_comment_refs = 0
            for source_ref, semantics in scoped_comments:
                if source_ref in destination_comment_semantics:
                    duplicate_comment_refs += 1
                destination_comment_semantics[source_ref] = semantics
            destination_comment_refs = set(destination_comment_semantics)
            comment_semantic_mismatches = sum(
                expected_ref not in destination_comment_refs
                or destination_comment_semantics.get(expected_ref)
                != bitrix_timeline_comment_expected_semantics.get(expected_ref)
                for expected_ref in expected_comment_refs
            ) + len(destination_comment_refs - expected_comment_refs) + duplicate_comment_refs
            bitrix_timeline_comment_source_ref_audit = {
                "expected_keys": len(expected_comment_refs),
                "destination_keys": len(destination_comment_refs),
                "destination_rows": len(scoped_comments),
                "set_match": destination_comment_refs == expected_comment_refs,
                "semantic_match": comment_semantic_mismatches == 0,
                "semantic_mismatches": comment_semantic_mismatches,
            }

        bitrix_timeline_attachment_source_ref_audit = None
        if bitrix_timeline_attachment_expected_semantics is not None:
            from modules.sales import timeline_storage

            expected_attachment_refs = set(bitrix_timeline_attachment_expected_semantics)
            imported_attachments = (await session.execute(
                select(CrmTimelineAttachment, CrmTimelineComment, Deal.number)
                .outerjoin(CrmTimelineComment, CrmTimelineComment.id == CrmTimelineAttachment.comment_id)
                .outerjoin(Deal, Deal.id == CrmTimelineComment.deal_id)
                .where(CrmTimelineAttachment.source_ref.like(
                    f"{_BITRIX_TIMELINE_ATTACHMENT_PREFIX}%"
                ))
            )).all()
            destination_attachment_semantics: dict[str, tuple] = {}
            duplicate_attachment_refs = 0
            orphan_attachment_rows = 0
            for attachment, comment, deal_number in imported_attachments:
                source_ref = attachment.source_ref or ""
                match = _BITRIX_TIMELINE_ATTACHMENT_SOURCE_RE.fullmatch(source_ref)
                if comment is None:
                    orphan_attachment_rows += 1
                storage_valid = True
                try:
                    timeline_storage.verify_attachment(attachment)
                except (OSError, TypeError, ValueError):
                    storage_valid = False
                semantics = (
                    comment.source_ref if comment is not None else None,
                    comment.entity_type if comment is not None else None,
                    comment.source_entity_id if comment is not None else None,
                    deal_number,
                    match.group(3) if match else None,
                    attachment.sha256,
                    attachment.size_bytes,
                    attachment.filename,
                    attachment.content_type,
                    attachment.storage_path,
                    storage_valid,
                )
                if source_ref in destination_attachment_semantics:
                    duplicate_attachment_refs += 1
                destination_attachment_semantics[source_ref] = semantics
            destination_attachment_refs = set(destination_attachment_semantics)
            attachment_semantic_mismatches = sum(
                expected_ref not in destination_attachment_refs
                or destination_attachment_semantics.get(expected_ref)
                != bitrix_timeline_attachment_expected_semantics.get(expected_ref)
                for expected_ref in expected_attachment_refs
            ) + len(destination_attachment_refs - expected_attachment_refs) + duplicate_attachment_refs
            bitrix_timeline_attachment_source_ref_audit = {
                "expected_keys": len(expected_attachment_refs),
                "destination_keys": len(destination_attachment_refs),
                "destination_rows": len(imported_attachments),
                "orphan_destination_rows": orphan_attachment_rows,
                "set_match": destination_attachment_refs == expected_attachment_refs,
                "semantic_match": attachment_semantic_mismatches == 0
                and orphan_attachment_rows == 0,
                "semantic_mismatches": attachment_semantic_mismatches,
            }

        counterparties = (await session.execute(select(Counterparty))).scalars().all()
        counterparties_by_id = {row.id: row for row in counterparties}
        aliases = (await session.execute(select(CounterpartyAlias))).scalars().all()
        aliases_by_counterparty: dict[int, list[CounterpartyAlias]] = {}
        for alias in aliases:
            aliases_by_counterparty.setdefault(alias.counterparty_id, []).append(alias)

        # Аудит строится по агрегатам: source external_ref -> destination master -> UNP.
        # Сами external_ref и UNP не попадают в report, чтобы не раскрывать кэш.
        source_companies = _load_jsonl("bx_companies", cache_snapshot)
        source_contacts = _load_jsonl("bx_contacts", cache_snapshot)
        source_deals = _load_jsonl("bx_deals", cache_snapshot)
        source_calls = _load_jsonl("bx_calls", cache_snapshot)
        source_requisites = _load_jsonl("bx_requisites", cache_snapshot)
        source_onec_counterparties = _load_jsonl(
            "onec_counterparties", cache_snapshot
        )
        call_company_refs = {
            str(row.get("CRM_ENTITY_ID"))
            for row in source_calls
            if row.get("CRM_ENTITY_TYPE") == "COMPANY"
            and row.get("CRM_ENTITY_ID") not in (None, "", "0")
        }
        source_company_ids = _company_reference_ids(
            source_companies,
            source_requisites,
            _nonempty_ids(source_deals, "COMPANY_ID")
            | _nonempty_ids(source_contacts, "COMPANY_ID")
            | call_company_refs,
        )
        company_evidence, company_match_status = _company_1c_evidence(
            source_companies,
            source_requisites,
            source_onec_counterparties,
            referenced_company_ids=source_company_ids,
        )
        name_evidence_by_ref = {
            evidence["ref"]: evidence
            for evidence in company_evidence.values()
            if evidence.get("match_method") == "name"
        }
        source_company_unps: dict[str, set[str]] = {}
        for row in source_requisites:
            company_id = str(row.get("ENTITY_ID") or "")
            unp = _valid_unp(row.get("RQ_INN"))
            if company_id and unp:
                source_company_unps.setdefault(company_id, set()).add(unp)
        source_alias_entries: list[tuple[tuple[str, str], str | None]] = []
        for company_id in sorted(source_company_ids):
            key = ("bitrix", f"company:{company_id}")
            unps = source_company_unps.get(company_id, set())
            source_alias_entries.extend((key, unp) for unp in sorted(unps))
            if not unps:
                source_alias_entries.append((key, None))
        for row in source_onec_counterparties:
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
        allowed_unp_omission = 0
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
                    name_evidence = (
                        name_evidence_by_ref.get(key[1])
                        if key[0] == "1c"
                        else None
                    )
                    matched_masters = [
                        counterparties_by_id.get(alias.counterparty_id)
                        for alias in actual_rows
                    ]
                    is_safe_name_omission = (
                        not actual_unps
                        and len(actual_rows) == 1
                        and len(actual_ids) == 1
                        and name_evidence is not None
                        and _valid_unp(name_evidence.get("unp")) == expected_unp
                        and matched_masters[0] is not None
                        and _normalized_contact_name(matched_masters[0].name)
                        == _normalized_contact_name(name_evidence["name"])
                    )
                    if is_safe_name_omission:
                        allowed_unp_omission += 1
                    else:
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
            "allowed_unp_omission_refs": allowed_unp_omission,
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
        if "bitrix_tasks" in source_semantic:
            destination_semantic_rows["bitrix_tasks"] = destination_task_semantic_rows

        deals = (
            await session.execute(select(Deal).where(Deal.number.like("BX-%")))
        ).scalars().all()
        deals_by_id = {row.id: row for row in deals}
        onec_aliases_by_ref: dict[str, set[int]] = {}
        bitrix_aliases_by_company: dict[str, set[int]] = {}
        for alias in aliases:
            if alias.source == "1c":
                onec_aliases_by_ref.setdefault(alias.external_ref, set()).add(alias.counterparty_id)
            elif alias.source == "bitrix" and alias.external_ref.startswith("company:"):
                company_id = alias.external_ref.removeprefix("company:")
                bitrix_aliases_by_company.setdefault(company_id, set()).add(alias.counterparty_id)
        company_counterparties: dict[str, Counterparty] = {}
        for company_id, evidence in company_evidence.items():
            target_ids = onec_aliases_by_ref.get(evidence["ref"], set())
            match_method = evidence.get("match_method")
            evidence_unp = _valid_unp(evidence.get("unp"))
            candidates = [
                counterparties_by_id[target_id]
                for target_id in target_ids
                if target_id in counterparties_by_id
                and (
                    (
                        match_method == "name"
                        and (
                            evidence_unp is None
                            or not str(counterparties_by_id[target_id].unp or "").strip()
                            or _valid_unp(counterparties_by_id[target_id].unp) == evidence_unp
                        )
                    )
                    or (
                        match_method != "name"
                        and _valid_unp(counterparties_by_id[target_id].unp) == evidence_unp
                    )
                )
                and (
                    match_method != "name"
                    or _normalized_contact_name(counterparties_by_id[target_id].name)
                    == _normalized_contact_name(evidence["name"])
                )
            ]
            if len(candidates) == 1 and len(target_ids) == 1:
                existing_company_ids = bitrix_aliases_by_company.get(company_id, set())
                if existing_company_ids and existing_company_ids != {candidates[0].id}:
                    company_match_status[company_id] = "existing_alias_conflict"
                else:
                    company_counterparties[company_id] = candidates[0]
            elif not target_ids:
                company_match_status[company_id] = "missing_1c_master"
            else:
                company_match_status[company_id] = "conflicting_1c_master"
        crm_directory_links = await _resolve_crm_directory_links(
            session,
            source_deals,
            {str(row.get("ID") or ""): row for row in source_contacts},
            company_counterparties,
            company_match_status,
        )
        crm_directory_summary = _crm_directory_link_summary(crm_directory_links)
        if detail_rows is not None:
            for number, outcome in sorted(crm_directory_links.items()):
                deal = outcome["deal"]
                expected_client_id = outcome["expected_client_id"]
                expected_contact_id = outcome["expected_contact_id"]
                client_link_conflict = (
                    deal is not None
                    and expected_client_id is not None
                    and deal.crm_client_id not in (None, expected_client_id)
                )
                contact_link_conflict = (
                    deal is not None
                    and expected_contact_id is not None
                    and deal.crm_contact_id not in (None, expected_contact_id)
                )
                client_issue = outcome["client_status"] != "matched" or client_link_conflict
                owner_issue = outcome["owner_status"] != "matched"
                contact_issue = outcome["contact_status"] not in {
                    "matched", "no_contact_reference"
                } or contact_link_conflict
                if not owner_issue and not client_issue and not contact_issue:
                    continue
                detail_rows.append({
                    "kind": "crm_directory_link_unresolved",
                    "dataset": "bitrix_deals",
                    "source_id": outcome["source_id"],
                    "identity": number,
                    "destination_id": deal.id if deal is not None else None,
                    "reason": {
                        "owner": outcome["owner_status"],
                        "client": outcome["client_status"],
                        "contact": outcome["contact_status"],
                        "existing_contact_pair_status": outcome[
                            "existing_contact_pair_status"
                        ],
                        "existing_client_link_conflict": client_link_conflict,
                        "existing_contact_link_conflict": contact_link_conflict,
                    },
                })
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
                "owner_id": row.owner_id,
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
                "deal_link": (
                    _opaque_identity(
                        "deal_link",
                        deals_by_id[row.deal_id].number
                        if row.deal_id in deals_by_id else "__orphan__",
                    )
                    if row.deal_id is not None else None
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
        expected_code_digests = {
            values["code"]: digest
            for digest, values in onec_sku_identity_expected.items()
        }
        destination_sku_semantics = []
        destination_sku_identity_counts: Counter[str] = Counter()
        destination_unknown_identity_rows = 0
        destination_missing_identity_rows = 0
        destination_identity_conflicts = 0
        for row in skus:
            provenance = row.provenance if isinstance(row.provenance, dict) else {}
            marker_present = "onec_identity" in provenance
            digest = _onec_identity_digest_from_provenance(provenance)
            expected_digest_for_code = expected_code_digests.get(row.code)
            if not marker_present:
                if expected_digest_for_code is not None:
                    destination_missing_identity_rows += 1
                    destination_identity_conflicts += 1
                continue
            if digest is None:
                destination_unknown_identity_rows += 1
                if expected_digest_for_code is not None:
                    destination_identity_conflicts += 1
                continue
            destination_sku_identity_counts[digest] += 1
            expected_identity = onec_sku_identity_expected.get(digest)
            if expected_identity is None:
                destination_unknown_identity_rows += 1
            elif expected_identity["code"] != row.code:
                destination_identity_conflicts += 1
            if expected_digest_for_code is not None and expected_digest_for_code != digest:
                destination_identity_conflicts += 1
            if not row.is_active:
                destination_identity_conflicts += 1
            destination_sku_semantics.append({
                "identity": digest,
                "code": row.code,
                "title": row.title,
                "active": bool(row.is_active),
            })
        destination_duplicate_identity_groups = sum(
            count > 1 for count in destination_sku_identity_counts.values()
        )
        destination_expected_digests = set(onec_sku_identity_expected)
        destination_actual_digests = set(destination_sku_identity_counts)
        destination_missing_source_rows = len(
            destination_expected_digests - destination_actual_digests
        )
        destination_semantic_rows["onec_sku"] = destination_sku_semantics
        source_sku_catalog_stats = source_report["sku_identity_catalog"]
        onec_sku_identity_audit = {
            **source_sku_catalog_stats,
            "destination_identity_rows": sum(destination_sku_identity_counts.values()),
            "destination_duplicate_identity_groups": destination_duplicate_identity_groups,
            "destination_unknown_identity_rows": destination_unknown_identity_rows,
            "destination_missing_identity_rows": destination_missing_identity_rows,
            "destination_missing_source_rows": destination_missing_source_rows,
            "destination_identity_conflicts": destination_identity_conflicts,
            "semantic_match": (
                source_semantic["onec_sku"] == _semantic_summary(destination_sku_semantics)
            ),
        }
        onec_sku_identity_audit["blocker"] = bool(
            not onec_sku_identity_audit["valid"]
            or destination_duplicate_identity_groups
            or destination_unknown_identity_rows
            or destination_missing_identity_rows
            or destination_missing_source_rows
            or destination_identity_conflicts
            or not onec_sku_identity_audit["semantic_match"]
        )
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
                None if name == "onec_sku" else detail_rows,
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
        "onec_sku_identity": onec_sku_identity_audit,
        "fidelity": fidelity,
        "alias_audit": alias_audit,
        "crm_directory_links": crm_directory_summary,
        "fidelity_note": (
            "Fidelity compares transformed semantic rows; source broken links remain under "
            "source.links and are not treated as destination fidelity."
        ),
        "load_counts": {
            "bitrix_companies": {
                "source_rows": source_records.get("bx_companies", 0),
                "referenced_company_ids": source_report["company_1c_mapping"][
                    "company_references"
                ],
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
            "bitrix_product_source_refs": bitrix_product_source_ref_audit,
            "bitrix_stage_history_source_refs": bitrix_stage_history_source_ref_audit,
            "bitrix_timeline_comment_source_refs": bitrix_timeline_comment_source_ref_audit,
            "bitrix_timeline_attachment_source_refs": bitrix_timeline_attachment_source_ref_audit,
            "bitrix_call_deal_links": bitrix_call_deal_source_ref_audit,
            "bitrix_task_source_refs": bitrix_task_source_ref_audit,
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
    cache_snapshot = _require_isolated_cache_snapshot()
    cache_dir = cache_snapshot.cache_dir if cache_snapshot is not None else OUT_DIR
    _guard_report_paths(
        cache_dir,
        _isolated_database_path(),
        aggregate_path,
        detail_path,
    )
    detail_rows = [] if detail_path is not None else None
    source_report = _source_reconciliation(
        include_semantic_rows=True,
        detail_rows=detail_rows,
        cache_snapshot=cache_snapshot,
    )
    source_semantic_rows = source_report.pop("_semantic_rows")
    source_identity_ids = source_report.pop("_source_identity_ids", {})
    onec_sku_identity_expected = source_report.pop("_onec_sku_identity_expected", {})
    bitrix_product_source_invalid = source_report.pop(
        "_bitrix_product_source_invalid", False
    )
    bitrix_product_expected_semantics = source_report.pop(
        "_bitrix_product_expected_semantics", None
    )
    bitrix_product_scope_deal_ids = source_report.pop(
        "_bitrix_product_scope_deal_ids", None
    )
    bitrix_stage_history_source_invalid = source_report.pop(
        "_bitrix_stage_history_source_invalid", False
    )
    bitrix_stage_history_expected_semantics = source_report.pop(
        "_bitrix_stage_history_expected_semantics", None
    )
    bitrix_stage_history_scope_deal_ids = source_report.pop(
        "_bitrix_stage_history_scope_deal_ids", None
    )
    bitrix_timeline_comment_source_invalid = source_report.pop(
        "_bitrix_timeline_comment_source_invalid", False
    )
    bitrix_timeline_comment_expected_semantics = source_report.pop(
        "_bitrix_timeline_comment_expected_semantics", None
    )
    bitrix_timeline_comment_scope_owners = source_report.pop(
        "_bitrix_timeline_comment_scope_owners", None
    )
    bitrix_timeline_attachment_source_invalid = source_report.pop(
        "_bitrix_timeline_attachment_source_invalid", False
    )
    bitrix_timeline_attachment_expected_semantics = source_report.pop(
        "_bitrix_timeline_attachment_expected_semantics", None
    )
    bitrix_call_deal_source_invalid = source_report.pop(
        "_bitrix_call_deal_source_invalid", False
    )
    bitrix_call_expected_deal_links = source_report.pop(
        "_bitrix_call_expected_deal_links", None
    )
    bitrix_task_source_invalid = source_report.pop(
        "_bitrix_task_source_invalid", False
    )
    bitrix_task_expected_semantics = source_report.pop(
        "_bitrix_task_expected_semantics", None
    )
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
            bitrix_product_expected_semantics,
            bitrix_product_scope_deal_ids,
            onec_sku_identity_expected,
            bitrix_stage_history_expected_semantics,
            bitrix_stage_history_scope_deal_ids,
            bitrix_timeline_comment_expected_semantics,
            bitrix_timeline_comment_scope_owners,
            bitrix_timeline_attachment_expected_semantics,
            cache_snapshot,
            bitrix_call_expected_deal_links,
            bitrix_task_expected_semantics,
        )
    finally:
        await db.disconnect()

    def gap_status(available: bool) -> str:
        return "present_not_imported" if available else "source_unavailable"

    product_ref_audit = destination_report["load_counts"][
        "bitrix_product_source_refs"
    ]
    product_source_available = source_report["products"][
        "bitrix_product_rows_available"
    ]
    stage_history_source_available = source_report["history"][
        "stage_history_rows_available"
    ]
    stage_history_ref_audit = destination_report["load_counts"][
        "bitrix_stage_history_source_refs"
    ]
    timeline_comment_source_available = source_report["timeline_comments"][
        "source_available"
    ]
    timeline_comment_ref_audit = destination_report["load_counts"][
        "bitrix_timeline_comment_source_refs"
    ]
    timeline_attachment_source_available = source_report["timeline_attachments"][
        "source_available"
    ]
    timeline_attachment_ref_audit = destination_report["load_counts"][
        "bitrix_timeline_attachment_source_refs"
    ]
    call_deal_source = source_report["call_deal_links"]
    call_deal_ref_audit = destination_report["load_counts"][
        "bitrix_call_deal_links"
    ]
    task_source = source_report["tasks"]
    task_ref_audit = destination_report["load_counts"][
        "bitrix_task_source_refs"
    ]
    report = {
        "schema": 1,
        "period": LABEL,
        "source": source_report,
        "destination": destination_report,
        "gaps": [
            {
                "area": "users",
                "status": "not_imported",
                "reason": "owner links require an existing bitrix:<id> account linked to an eligible sales employee",
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
                "area": "bitrix_call_deal_links",
                "status": (
                    "invalid_source"
                    if call_deal_source["source_available"]
                    and bitrix_call_deal_source_invalid
                    else "source_unavailable"
                    if not call_deal_source["source_available"]
                    else "destination_unavailable"
                    if call_deal_ref_audit is None
                    else "source_ref_mismatch"
                    if not call_deal_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not call_deal_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": call_deal_source["deal_target_rows"],
                "source_ref_expected_keys": (
                    call_deal_ref_audit["expected_keys"]
                    if call_deal_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    call_deal_ref_audit["destination_keys"]
                    if call_deal_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    call_deal_ref_audit["set_match"]
                    if call_deal_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    call_deal_ref_audit["semantic_match"]
                    if call_deal_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    call_deal_ref_audit["semantic_mismatches"]
                    if call_deal_ref_audit is not None else None
                ),
                "orphan_destination_rows": (
                    call_deal_ref_audit["orphan_destination_rows"]
                    if call_deal_ref_audit is not None else None
                ),
                "blocker": (
                    call_deal_source["source_available"]
                    and (
                        bitrix_call_deal_source_invalid
                        or call_deal_ref_audit is None
                        or not call_deal_ref_audit["set_match"]
                        or not call_deal_ref_audit["semantic_match"]
                    )
                ),
                "reason": (
                    "Calls with CRM_ENTITY_TYPE=DEAL must map to a supported Bitrix deal"
                ),
            },
            {
                "area": "bitrix_tasks",
                "status": (
                    "invalid_source"
                    if task_source["source_available"] and bitrix_task_source_invalid
                    else "source_unavailable"
                    if not task_source["source_available"]
                    else "destination_unavailable"
                    if task_ref_audit is None
                    else "source_ref_mismatch"
                    if not task_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not task_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": task_source["source_rows"],
                "source_ref_expected_keys": (
                    task_ref_audit["expected_keys"]
                    if task_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    task_ref_audit["destination_keys"]
                    if task_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    task_ref_audit["set_match"]
                    if task_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    task_ref_audit["semantic_match"]
                    if task_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    task_ref_audit["semantic_mismatches"]
                    if task_ref_audit is not None else None
                ),
                "orphan_destination_rows": (
                    task_ref_audit["orphan_destination_rows"]
                    if task_ref_audit is not None else None
                ),
                "blocker": (
                    task_source["source_available"]
                    and (
                        bitrix_task_source_invalid
                        or task_ref_audit is None
                        or not task_ref_audit["set_match"]
                        or not task_ref_audit["semantic_match"]
                    )
                ),
                "reason": (
                    "Task metadata is source-keyed; task attachments and mail fields remain blocked"
                ),
            },
            {
                "area": "files",
                "status": gap_status(
                    source_report["files"]["dedicated_source_available"]
                    or source_report["timeline_attachments"]["binary_cache_v2"]
                ),
                "reason": (
                    "Ready v2 imports deal-comment attachments; lead/task/call/CRM-field files remain blocked"
                    if source_report["timeline_attachments"]["binary_cache_v2"]
                    else "Only ready-v2 deal-comment attachments are supported; lead/task/call/CRM-field files remain blocked"
                    if source_report["files"]["dedicated_source_available"]
                    else "no file cache; call recording metadata is not a downloaded file"
                ),
            },
            {
                "area": "history",
                "status": gap_status(source_report["history"]["dedicated_source_available"]),
                "reason": (
                    "timeline stages, comments and ready-v2 deal-comment attachments are imported; lead/task/call/CRM-field files remain blocked"
                    if source_report["history"]["dedicated_source_available"]
                    else "no timeline history cache; stage events use the separate bx_stage_history source"
                ),
            },
            {
                "area": "bitrix_timeline_comments",
                "status": (
                    "invalid_source"
                    if timeline_comment_source_available
                    and bitrix_timeline_comment_source_invalid
                    else "source_unavailable"
                    if not timeline_comment_source_available
                    else "destination_unavailable"
                    if timeline_comment_ref_audit is None
                    else "source_ref_mismatch"
                    if not timeline_comment_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not timeline_comment_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": source_report["timeline_comments"]["source_rows"],
                "source_ref_expected_keys": (
                    timeline_comment_ref_audit["expected_keys"]
                    if timeline_comment_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    timeline_comment_ref_audit["destination_keys"]
                    if timeline_comment_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    timeline_comment_ref_audit["set_match"]
                    if timeline_comment_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    timeline_comment_ref_audit["semantic_match"]
                    if timeline_comment_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    timeline_comment_ref_audit["semantic_mismatches"]
                    if timeline_comment_ref_audit is not None else None
                ),
                "blocker": (
                    (timeline_comment_source_available
                     and bitrix_timeline_comment_source_invalid)
                    or (
                        timeline_comment_ref_audit is not None
                        and (
                            not timeline_comment_ref_audit["set_match"]
                            or not timeline_comment_ref_audit["semantic_match"]
                        )
                    )
                ),
                "reason": (
                    "Comments use stable Bitrix identity; ready-v2 deal-comment attachments are imported and other file groups remain blocked"
                    if timeline_comment_source_available
                    else "bx_timeline_comments was not exported; legacy cache remains load-compatible"
                ),
            },
            {
                "area": "bitrix_timeline_attachments",
                "status": (
                    "invalid_source"
                    if timeline_attachment_source_available
                    and bitrix_timeline_attachment_source_invalid
                    else "source_unavailable"
                    if not timeline_attachment_source_available
                    else "destination_unavailable"
                    if timeline_attachment_ref_audit is None
                    else "destination_orphan"
                    if timeline_attachment_ref_audit["orphan_destination_rows"]
                    else "source_ref_mismatch"
                    if not timeline_attachment_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not timeline_attachment_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": source_report["timeline_attachments"]["source_rows"],
                "inventory_rows": source_report["timeline_attachments"]["inventory_rows"],
                "source_bytes": source_report["timeline_attachments"]["source_bytes"],
                "source_ref_expected_keys": (
                    timeline_attachment_ref_audit["expected_keys"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    timeline_attachment_ref_audit["destination_keys"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    timeline_attachment_ref_audit["set_match"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    timeline_attachment_ref_audit["semantic_match"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    timeline_attachment_ref_audit["semantic_mismatches"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "orphan_destination_rows": (
                    timeline_attachment_ref_audit["orphan_destination_rows"]
                    if timeline_attachment_ref_audit is not None else None
                ),
                "blocker": (
                    (timeline_attachment_source_available
                     and bitrix_timeline_attachment_source_invalid)
                    or (
                        timeline_attachment_ref_audit is not None
                        and (
                            timeline_attachment_ref_audit["orphan_destination_rows"] > 0
                            or
                            not timeline_attachment_ref_audit["set_match"]
                            or not timeline_attachment_ref_audit["semantic_match"]
                        )
                    )
                ),
                "reason": (
                    "Supported deal-comment attachments are compared by source identity and content; lead/task/call/CRM-field files remain blocked"
                    if source_report["timeline_attachments"]["binary_cache_v2"]
                    else "Legacy cache contains no binary sidecars; non-empty FILES remain unsupported"
                    if timeline_attachment_source_available
                    else "No timeline comment source cache was exported"
                ),
            },
            {
                "area": "bitrix_stage_history",
                "status": (
                    "invalid_source"
                    if stage_history_source_available and bitrix_stage_history_source_invalid
                    else "source_unavailable"
                    if not stage_history_source_available
                    else "destination_unavailable"
                    if stage_history_ref_audit is None
                    else "source_ref_mismatch"
                    if not stage_history_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not stage_history_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": source_report["history"]["stage_history_source_rows"],
                "source_ref_expected_keys": (
                    stage_history_ref_audit["expected_keys"]
                    if stage_history_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    stage_history_ref_audit["destination_keys"]
                    if stage_history_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    stage_history_ref_audit["set_match"]
                    if stage_history_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    stage_history_ref_audit["semantic_match"]
                    if stage_history_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    stage_history_ref_audit["semantic_mismatches"]
                    if stage_history_ref_audit is not None else None
                ),
                "blocker": (
                    stage_history_source_available
                    and (
                        bitrix_stage_history_source_invalid
                        or stage_history_ref_audit is None
                        or not stage_history_ref_audit["set_match"]
                        or not stage_history_ref_audit["semantic_match"]
                    )
                ),
                "reason": (
                    "Deal-stage events are imported by stable source ID with explicit category mapping"
                    if stage_history_source_available
                    else "bx_stage_history was not exported; legacy cache remains load-compatible"
                ),
            },
            {
                "area": "bitrix_products",
                "status": (
                    "invalid_source"
                    if product_source_available and bitrix_product_source_invalid
                    else "source_unavailable"
                    if not product_source_available or product_ref_audit is None
                    else "source_ref_mismatch"
                    if not product_ref_audit["set_match"]
                    else "source_semantic_mismatch"
                    if not product_ref_audit["semantic_match"]
                    else "source_available"
                ),
                "source_rows": source_report["products"]["bitrix_product_rows"],
                "destination_total_imported_rows": destination_report["counts"][
                    "deal_items_bitrix"
                ],
                "source_ref_expected_keys": (
                    product_ref_audit["expected_keys"]
                    if product_ref_audit is not None else None
                ),
                "source_ref_destination_keys": (
                    product_ref_audit["destination_keys"]
                    if product_ref_audit is not None else None
                ),
                "source_ref_set_match": (
                    product_ref_audit["set_match"]
                    if product_ref_audit is not None else None
                ),
                "source_ref_semantic_match": (
                    product_ref_audit["semantic_match"]
                    if product_ref_audit is not None else None
                ),
                "source_ref_semantic_mismatches": (
                    product_ref_audit["semantic_mismatches"]
                    if product_ref_audit is not None else None
                ),
                "blocker": (
                    (product_source_available and bitrix_product_source_invalid)
                    or (
                        product_ref_audit is not None
                        and (
                            not product_ref_audit["set_match"]
                            or not product_ref_audit["semantic_match"]
                        )
                    )
                ),
                "reason": (
                    "Rows are imported through exact Bitrix XML_ID to unique 1C Ref_Key and Code; "
                    "unit_price remains NULL pending pricing semantics"
                    if source_report["products"]["bitrix_product_rows_available"]
                    else "crm.deal.productrows was not exported; 1C SKU is imported separately"
                ),
            },
            {
                "area": "onec_sku_identity",
                "status": (
                    "identity_mismatch"
                    if destination_report["onec_sku_identity"]["blocker"]
                    else "source_available"
                ),
                "blocker": destination_report["onec_sku_identity"]["blocker"],
                "source_catalog_valid": destination_report["onec_sku_identity"]["valid"],
                "source_active_rows": destination_report["onec_sku_identity"]["active_rows"],
                "source_deleted_rows": destination_report["onec_sku_identity"]["deleted_rows"],
                "unknown_deletion_mark_rows": destination_report["onec_sku_identity"][
                    "unknown_deletion_mark_rows"
                ],
                "invalid_identity_rows": destination_report["onec_sku_identity"][
                    "invalid_identity_rows"
                ],
                "duplicate_active_ref_groups": destination_report["onec_sku_identity"][
                    "duplicate_active_ref_groups"
                ],
                "duplicate_active_code_groups": destination_report["onec_sku_identity"][
                    "duplicate_active_code_groups"
                ],
                "destination_duplicate_identity_groups": destination_report[
                    "onec_sku_identity"
                ]["destination_duplicate_identity_groups"],
                "destination_unknown_identity_rows": destination_report[
                    "onec_sku_identity"
                ]["destination_unknown_identity_rows"],
                "destination_missing_identity_rows": destination_report[
                    "onec_sku_identity"
                ]["destination_missing_identity_rows"],
                "destination_missing_source_rows": destination_report[
                    "onec_sku_identity"
                ]["destination_missing_source_rows"],
                "destination_identity_conflicts": destination_report[
                    "onec_sku_identity"
                ]["destination_identity_conflicts"],
                "semantic_match": destination_report["onec_sku_identity"]["semantic_match"],
                "reason": (
                    "Active 1C SKU identities must map one-to-one to active destination rows"
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


def _safe_cli_diagnostic(exc: Exception) -> str:
    """Return a bounded code-only failure diagnostic; never stringify DB errors."""
    from sqlalchemy.exc import IntegrityError, OperationalError

    if isinstance(exc, IntegrityError):
        code = "DB_INTEGRITY"
    elif isinstance(exc, OperationalError):
        code = "DB_OPERATION"
    elif (
        isinstance(exc, RuntimeError)
        and str(exc)
        == "load-only требует явный AIOS_DATABASE_URL вида sqlite+aiosqlite:///ABSOLUTE_PATH"
    ):
        # Preserve the actionable config key while keeping configured values private.
        code = "CONFIG_AIOS_DATABASE_URL_REQUIRED"
    elif isinstance(exc, RuntimeError) and str(exc) == (
        "Задайте IMPORT_ONEC_PURCHASE_ENTITY явным OData-типом Document_* из метаданных 1С"
    ):
        code = "CONFIG_IMPORT_ONEC_PURCHASE_ENTITY_REQUIRED"
    else:
        code = "IMPORT_FAILED"
    return f"import: failed; code={code}"


def _run_cli() -> None:
    try:
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
        if phase == "extract-onec-purchases":
            extract_onec_purchases()
        if phase == "map-onec-purchases":
            map_onec_purchases()
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
    except Exception as exc:
        print(_safe_cli_diagnostic(exc), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    _run_cli()
