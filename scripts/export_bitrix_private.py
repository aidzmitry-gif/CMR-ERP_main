"""Stage Bitrix CRM data in a private directory on the ERP server.

This is the metadata phase of CRM-LIVE-001. For company matching it requests
only ID and TITLE for referenced Bitrix company IDs; these are evidence, never
the master card. It never writes to ERP and prints only counts and digests.
The separate binary phase reads this sealed metadata directory and stores
task/comment files and available call recordings with private link records.

Run with a root-only webhook file mounted read-only at /run/secrets/bitrix_webhook
and /private mounted to an empty mode-0700 server directory. For the binary
phase, pass ``binaries`` and also mount the completed metadata directory at
/metadata read-only. Never pass the webhook in command arguments or Docker
environment variables.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import requests

PORTAL = "microchops.bitrix24.by"
LISTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("deals", "crm.deal.list", {"order": {"ID": "ASC"}, "filter": {}, "select": ["*", "UF_*"]}),
    ("contacts", "crm.contact.list", {"order": {"ID": "ASC"}, "filter": {}, "select": ["*", "UF_*"]}),
    ("leads", "crm.lead.list", {"order": {"ID": "ASC"}, "filter": {}, "select": ["*", "UF_*"]}),
    ("activities", "crm.activity.list", {"order": {"ID": "ASC"}, "filter": {},
                                           "select": ["*", "COMMUNICATIONS", "FILES", "STORAGE_ELEMENT_IDS"]}),
    ("calls", "voximplant.statistic.get", {"FILTER": {}, "SORT": "ID", "ORDER": "ASC"}),
    ("users", "user.get", {}),
    ("deal_stage_history", "crm.stagehistory.list", {"entityTypeId": 2, "order": {"ID": "ASC"},
                                                   "filter": {}, "select": ["ID", "TYPE_ID", "OWNER_ID",
                                                                            "CREATED_TIME", "CATEGORY_ID",
                                                                            "STAGE_SEMANTIC_ID", "STAGE_ID"]}),
    ("lead_stage_history", "crm.stagehistory.list", {"entityTypeId": 1, "order": {"ID": "ASC"},
                                                   "filter": {}, "select": ["ID", "TYPE_ID", "OWNER_ID",
                                                                            "CREATED_TIME", "STATUS_SEMANTIC_ID",
                                                                            "STATUS_ID"]}),
)
ALLOWED = frozenset(method for _, method, _ in LISTS) | {
    "crm.deal.productrows.get", "crm.product.get", "crm.timeline.comment.list", "crm.company.list",
    "crm.deal.fields", "crm.contact.fields", "crm.lead.fields", "crm.requisite.list",
    "crm.contact.company.items.get", "crm.deal.contact.items.get",
    "tasks.task.list", "tasks.task.get", "disk.attachedObject.get", "disk.file.get",
    "crm.item.get",
}
SCHEMA_METHODS = {"deals": "crm.deal.fields", "contacts": "crm.contact.fields",
                  "leads": "crm.lead.fields"}


class ExportError(Exception):
    """Safe error code; never include REST URL, response body or row values."""


def _validate_webhook(value: str) -> str:
    url = urlsplit(value.strip().rstrip("/"))
    if (url.scheme != "https" or url.hostname != PORTAL or url.username or url.password
            or url.query or url.fragment or not url.path.startswith("/rest/")):
        raise ExportError("BAD_WEBHOOK_CONFIGURATION")
    pieces = [piece for piece in url.path.split("/") if piece]
    if len(pieces) != 3 or not pieces[1].isdigit() or not pieces[2]:
        raise ExportError("BAD_WEBHOOK_CONFIGURATION")
    return value.strip().rstrip("/")


class BitrixReadOnly:
    def __init__(self, webhook: str, session: requests.Session | None = None):
        self.webhook = _validate_webhook(webhook)
        self.session = session or requests.Session()
        if session is None:
            # Keep signed download links on the server's direct network path.
            self.session.trust_env = False

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in ALLOWED:
            raise ExportError("METHOD_NOT_ALLOWED")
        if method == "crm.company.list":
            company_filter = params.get("filter")
            company_ids = company_filter.get("@ID") if isinstance(company_filter, dict) else None
            if (params.get("select") != ["ID", "TITLE"] or not isinstance(company_ids, list)
                    or not company_ids or len(company_ids) > 50
                    or any(not str(value).isdigit() for value in company_ids)):
                raise ExportError("COMPANY_SCOPE_VIOLATION")
        if method == "crm.product.get":
            if (set(params) != {"id"} or type(params["id"]) is not int or params["id"] < 1):
                raise ExportError("PRODUCT_SCOPE_VIOLATION")
        if method == "crm.item.get":
            if (params.get("entityTypeId") not in (1, 2, 3)
                    or not isinstance(params.get("id"), int) or params["id"] < 1
                    or params.get("useOriginalUfNames") != "Y"):
                raise ExportError("CRM_ITEM_SCOPE_VIOLATION")
        if method == "voximplant.statistic.get":
            allowed_page = (set(params) == {"FILTER", "SORT", "ORDER", "start"}
                            and params.get("FILTER") == {}
                            and isinstance(params.get("start"), int) and params["start"] >= 0)
            call_ids = params.get("FILTER", {}).get("ID") if isinstance(params.get("FILTER"), dict) else None
            allowed_one = (set(params) == {"FILTER", "SORT", "ORDER"}
                           and isinstance(call_ids, list) and len(call_ids) == 1
                           and isinstance(call_ids[0], int) and call_ids[0] > 0
                           and params["FILTER"] == {"ID": call_ids})
            if (params.get("SORT") != "ID" or params.get("ORDER") != "ASC"
                    or not (allowed_page or allowed_one)):
                raise ExportError("CALL_SCOPE_VIOLATION")
        for attempt in range(4):
            try:
                response = self.session.post(
                    f"{self.webhook}/{method}.json", json=params,
                    timeout=45, allow_redirects=False,
                )
            except requests.RequestException as exc:
                if attempt == 3:
                    raise ExportError("NETWORK_" + type(exc).__name__) from None
                time.sleep(2**attempt)
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2**attempt)
                continue
            if response.status_code != 200:
                raise ExportError("HTTP_" + str(response.status_code))
            try:
                data = response.json()
            except ValueError:
                raise ExportError("BAD_JSON") from None
            if not isinstance(data, dict) or "error" in data or "result" not in data:
                raise ExportError("API_ERROR_OR_MISSING_RESULT")
            return data
        raise ExportError("RETRY_EXHAUSTED")

    def pages(self, method: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        start = 0
        seen_offsets: set[int] = set()
        fetched = 0
        expected: int | None = None
        while True:
            if start in seen_offsets:
                raise ExportError("PAGINATION_LOOP")
            seen_offsets.add(start)
            data = self.call(method, {**params, "start": start})
            rows = data["result"]
            if method == "crm.stagehistory.list" and isinstance(rows, dict):
                rows = rows.get("items")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ExportError("BAD_PAGE_ROWS")
            if "total" in data:
                if not isinstance(data["total"], int) or data["total"] < 0:
                    raise ExportError("BAD_TOTAL")
                if expected is not None and expected != data["total"]:
                    raise ExportError("SOURCE_CHANGED_DURING_EXPORT")
                expected = data["total"]
            fetched += len(rows)
            yield from rows
            next_start = data.get("next")
            if next_start is None:
                if expected is not None and fetched != expected:
                    raise ExportError("INCOMPLETE_PAGE_SET")
                if expected is None and len(rows) >= 50:
                    raise ExportError("PAGINATION_UNCERTAIN")
                break
            if not isinstance(next_start, int) or next_start <= start:
                raise ExportError("BAD_NEXT_OFFSET")
            start = next_start

    def task_ids(self) -> Iterator[str]:
        """Read every visible task ID from the legacy 50-row REST API."""
        start = 0
        fetched = 0
        expected: int | None = None
        seen: set[str] = set()
        while True:
            data = self.call("tasks.task.list", {
                "order": {"ID": "asc"}, "filter": {}, "select": ["ID"], "start": start,
            })
            result = data["result"]
            if not isinstance(result, dict):
                raise ExportError("BAD_TASK_PAGE")
            rows = result.get("tasks")
            total = data.get("total")
            if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                    or not isinstance(total, int) or total < 0 or len(rows) > 50):
                raise ExportError("BAD_TASK_PAGE")
            if expected is not None and total != expected:
                raise ExportError("SOURCE_CHANGED_DURING_EXPORT")
            expected = total
            for row in rows:
                task_id = str(row.get("id") or row.get("ID") or "")
                if not task_id.isdigit() or task_id in seen:
                    raise ExportError("MISSING_OR_DUPLICATE_ID_tasks")
                seen.add(task_id)
                yield task_id
            fetched += len(rows)
            if fetched == expected:
                break
            if not rows or fetched > expected or len(rows) != 50:
                raise ExportError("INCOMPLETE_TASK_PAGE_SET")
            start += 50


class Dataset:
    def __init__(self, root: Path, name: str):
        self.folder = root / name
        self.folder.mkdir(mode=0o700 if os.name == "posix" else 0o777)
        self.name = name
        self.files: list[tuple[str, int, str]] = []
        self.keys: set[str] = set()

    def add(self, key: str, row: dict[str, Any]) -> None:
        if not key or key in self.keys:
            raise ExportError("MISSING_OR_DUPLICATE_ID_" + self.name)
        self.keys.add(key)
        filename = hashlib.sha256((self.name + ":" + key).encode()).hexdigest() + ".json"
        body = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(body).hexdigest()
        target = self.folder / filename
        with target.open("xb") as stream:
            stream.write(body)
        self.files.append((filename, len(body), digest))

    def summary(self) -> dict[str, int | str]:
        fingerprint = hashlib.sha256()
        for filename, size, digest in sorted(self.files):
            fingerprint.update(f"{filename}:{size}:{digest}\n".encode("ascii"))
        return {"records": len(self.files), "bytes": sum(size for _, size, _ in self.files),
                "sha256": fingerprint.hexdigest()}


def _json_object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _staged_rows(root: Path, name: str) -> Iterator[dict[str, Any]]:
    """Verify the private metadata digest before trusting source references."""
    try:
        if root.is_symlink() or (root / name).is_symlink():
            raise ExportError("BAD_STAGED_DATASET")
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
        expected = manifest[name]
        folder = root / name
        if not folder.is_dir() or any(path.suffix != ".json" for path in folder.iterdir()):
            raise ExportError("BAD_STAGED_DATASET")
        files = sorted(folder.glob("*.json"))
        fingerprint = hashlib.sha256()
        total_bytes = 0
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ExportError("BAD_STAGED_DATASET")
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            fingerprint.update(f"{path.name}:{len(body)}:{digest}\n".encode("ascii"))
            total_bytes += len(body)
            row = json.loads(body, object_pairs_hook=_json_object_without_duplicate_keys)
            if not isinstance(row, dict):
                raise ExportError("BAD_STAGED_DATASET")
            yield row
        if (len(files) != expected["records"] or total_bytes != expected["bytes"]
                or fingerprint.hexdigest() != expected["sha256"]):
            raise ExportError("STAGED_DATASET_MISMATCH")
    except ExportError:
        raise
    except (OSError, KeyError, TypeError, ValueError):
        raise ExportError("BAD_STAGED_DATASET") from None


def _verified_binary_snapshot(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Verify every binary and reference before selecting an import subset.

    Keep file bytes on disk: a single Bitrix file may be as large as 2 GiB.
    The binary export manifest covers all downloaded sources, not only CRM
    comments, so verify the complete snapshot before using any of its links.
    """
    try:
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise ExportError("BAD_BINARY_SNAPSHOT")
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise ExportError("BAD_BINARY_SNAPSHOT")
        manifest = json.loads(
            manifest_path.read_bytes(), object_pairs_hook=_json_object_without_duplicate_keys
        )
        if (not isinstance(manifest, dict)
                or set(manifest) != {"binary_files", "binary_inventory", "binary_links",
                                     "unavailable_recordings"}):
            raise ExportError("BAD_BINARY_SNAPSHOT")
        if {path.name for path in root.iterdir()} != {
            "manifest.json", "binary_files", "binary_inventory", "binary_links"
        }:
            raise ExportError("BAD_BINARY_SNAPSHOT")
        links = list(_staged_rows(root, "binary_links"))
        inventory_rows = list(_staged_rows(root, "binary_inventory"))
        folder = root / "binary_files"
        if folder.is_symlink() or not folder.is_dir():
            raise ExportError("BAD_BINARY_SNAPSHOT")
        fingerprints = hashlib.sha256()
        actual_files: dict[str, tuple[int, str]] = {}
        total_bytes = 0
        for path in sorted(folder.iterdir(), key=lambda entry: entry.name):
            if (path.is_symlink() or not path.is_file()
                    or not re.fullmatch(r"[0-9a-f]{64}\.bin", path.name)):
                raise ExportError("BAD_BINARY_SNAPSHOT")
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > 2 * 1024**3:
                        raise ExportError("BAD_BINARY_SNAPSHOT")
                    digest.update(chunk)
            actual_files[path.name] = (size, digest.hexdigest())
            total_bytes += size
            fingerprints.update(f"{path.name}:{size}:{digest.hexdigest()}\n".encode("ascii"))
        expected_files = manifest["binary_files"]
        if (not isinstance(expected_files, dict)
                or type(expected_files.get("records")) is not int
                or expected_files["records"] != len(actual_files)
                or type(expected_files.get("bytes")) is not int
                or expected_files["bytes"] != total_bytes
                or expected_files.get("sha256") != fingerprints.hexdigest()):
            raise ExportError("BINARY_SNAPSHOT_CHANGED")
        inventory: dict[str, dict[str, Any]] = {}
        filenames: set[str] = set()
        for row in inventory_rows:
            key = row.get("key")
            filename = row.get("filename")
            size = row.get("bytes")
            digest = row.get("sha256")
            if (not isinstance(key, str) or not key or key in inventory
                    or not isinstance(filename, str) or filename in filenames
                    or type(size) is not int or size < 0
                    or not isinstance(digest, str)
                    or actual_files.get(filename) != (size, digest)
                    or filename != hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"):
                raise ExportError("BINARY_INVENTORY_MISMATCH")
            inventory[key] = row
            filenames.add(filename)
        if filenames != set(actual_files):
            raise ExportError("BINARY_INVENTORY_MISMATCH")
        for row in links:
            if not isinstance(row.get("binary_key"), str) or row["binary_key"] not in inventory:
                raise ExportError("BINARY_LINK_MISMATCH")
        if {row["binary_key"] for row in links} != set(inventory):
            raise ExportError("UNLINKED_BINARY_INVENTORY")
        unavailable = manifest["unavailable_recordings"]
        if (not isinstance(unavailable, dict) or set(unavailable) != {"records"}
                or type(unavailable["records"]) is not int or unavailable["records"] < 0):
            raise ExportError("BAD_BINARY_SNAPSHOT")
        if unavailable["records"]:
            raise ExportError("BINARY_RECORDINGS_UNAVAILABLE")
        return links, inventory
    except ExportError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError):
        raise ExportError("BAD_BINARY_SNAPSHOT") from None


def _stage_comment_binary_cache(
    bitrix_root: Path, binary_root: Path, output: Path,
) -> tuple[dict[str, dict[str, int | str]], dict[str, int | str], int]:
    """Seal only deal-comment binaries, while checking all source links."""
    links, inventory = _verified_binary_snapshot(binary_root)
    if any(row.get("source") != "comment" for row in links):
        raise ExportError("UNSUPPORTED_BINARY_SOURCE")
    expected: set[tuple[str, str, str, str]] = set()
    for comment in _staged_rows(bitrix_root, "timeline_comments"):
        entity_type = comment.get("ENTITY_TYPE")
        if entity_type not in {"deal", "lead"}:
            raise ExportError("BAD_COMMENT_OWNER")
        owner_id = _positive_id(comment.get("ENTITY_ID"), "BAD_COMMENT_OWNER")
        comment_id = _positive_id(comment.get("ID"), "BAD_COMMENT_ID")
        files = comment.get("FILES")
        if files is None:
            files = {}
        if not isinstance(files, dict):
            raise ExportError("BAD_COMMENT_FILES")
        for file_key, file_row in files.items():
            if (not isinstance(file_row, dict)
                    or _positive_id(file_key, "BAD_COMMENT_FILE_ID")
                    != _positive_id(file_row.get("id"), "BAD_COMMENT_FILE_ID")):
                raise ExportError("COMMENT_FILE_ID_MISMATCH")
            expected.add((entity_type, owner_id, comment_id, str(file_key)))
    actual: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in links:
        if row.get("source") != "comment":
            continue
        entity_type = row.get("entity_type")
        if entity_type not in {"deal", "lead"}:
            raise ExportError("BINARY_COMMENT_LINK_MISMATCH")
        identity = (
            entity_type,
            _positive_id(row.get("entity_id"), "BINARY_COMMENT_LINK_MISMATCH"),
            _positive_id(row.get("source_id"), "BINARY_COMMENT_LINK_MISMATCH"),
            _positive_id(row.get("file_id"), "BINARY_COMMENT_LINK_MISMATCH"),
        )
        if (identity in actual or row.get("binary_key") != "disk:" + identity[3]):
            raise ExportError("BINARY_COMMENT_LINK_MISMATCH")
        actual[identity] = row
    if set(actual) != expected:
        raise ExportError("BINARY_COMMENT_LINK_MISMATCH")
    selected_links = [actual[key] for key in sorted(actual) if key[0] == "deal"]
    selected_keys = sorted({row["binary_key"] for row in selected_links})

    def write_jsonl(name: str, rows: list[dict[str, Any]]) -> dict[str, int | str]:
        digest = hashlib.sha256()
        count = size = 0
        with (output / f"{name}.jsonl").open("xb") as stream:
            for row in rows:
                line = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8") + b"\n"
                stream.write(line)
                digest.update(line)
                count += 1
                size += len(line)
        return {"records": count, "bytes": size, "sha256": digest.hexdigest()}

    cache = {
        "bx_comment_binary_links": write_jsonl("bx_comment_binary_links", selected_links),
        "bx_comment_binary_inventory": write_jsonl(
            "bx_comment_binary_inventory", [inventory[key] for key in selected_keys]
        ),
    }
    destination = output / "comment_binary_files"
    destination.mkdir(exist_ok=False)
    copied_files: list[tuple[str, int, str]] = []
    file_bytes = 0
    for key in selected_keys:
        item = inventory[key]
        filename = item["filename"]
        source = binary_root / "binary_files" / filename
        target = destination / filename
        if source.is_symlink() or not source.is_file():
            raise ExportError("BINARY_SNAPSHOT_CHANGED")
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > 2 * 1024**3:
                    raise ExportError("BINARY_SNAPSHOT_CHANGED")
                digest.update(chunk)
                output_stream.write(chunk)
        if size != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise ExportError("BINARY_SNAPSHOT_CHANGED")
        copied_files.append((filename, size, digest.hexdigest()))
        file_bytes += size
    fingerprint = hashlib.sha256()
    for filename, size, digest in sorted(copied_files):
        fingerprint.update(f"{filename}:{size}:{digest}\n".encode("ascii"))
    files_summary: dict[str, int | str] = {
        "records": len(selected_keys), "bytes": file_bytes,
        "sha256": fingerprint.hexdigest(),
    }
    lead_refs = sum(1 for key in actual if key[0] == "lead")
    return cache, files_summary, lead_refs


PRIVATE_CACHE_MAP = {
    "deals": "bx_deals", "contacts": "bx_contacts", "leads": "bx_leads",
    "calls": "bx_calls", "users": "bx_users",
    "company_name_evidence": "bx_companies", "requisites": "bx_requisites",
    "deal_product_rows": "bx_product_rows",
    "product_catalog_evidence": "bx_products",
    "deal_stage_history": "bx_stage_history",
    "timeline_comments": "bx_timeline_comments",
    "tasks": "bx_tasks",
    "Catalog_Контрагенты": "onec_counterparties",
    "Catalog_Номенклатура": "onec_sku",
}
PRIVATE_BITRIX_DATASETS = (
    {name for name, _, _ in LISTS}
    | {"field_schemas", "crm_file_items", "contact_company_links",
       "deal_contact_links", "company_name_evidence", "requisites",
       "unresolved_company_ids", "deal_product_rows", "product_catalog_evidence",
       "timeline_comments", "tasks"}
)
PRIVATE_ONEC_DATASETS = {"Catalog_Контрагенты", "Catalog_Номенклатура"}


def _canonical_private_source_id(value: Any, code: str) -> tuple[str, str]:
    raw = _positive_id(value, code)
    if len(raw) > 20:
        raise ExportError(code)
    return str(int(raw)), raw


def _verify_private_source_keys(
    root: Path, name: str, raw_keys: list[str], *, key_field: str,
) -> None:
    """Bind each staged file name to the ID stored in that same file."""
    if len(raw_keys) != len(set(raw_keys)):
        raise ExportError("BAD_PRIVATE_SOURCE_ID")
    folder = root / name
    try:
        if not folder.is_dir() or folder.is_symlink():
            raise ExportError("BAD_PRIVATE_SOURCE_ID")
        bound: set[str] = set()
        for path in folder.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ExportError("BAD_PRIVATE_SOURCE_ID")
            row = json.loads(
                path.read_bytes(),
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
            if not isinstance(row, dict):
                raise ExportError("BAD_PRIVATE_SOURCE_ID")
            raw_value = row.get(key_field)
            raw = "" if raw_value is None else str(raw_value)
            filename = hashlib.sha256((name + ":" + raw).encode()).hexdigest() + ".json"
            if path.name != filename or raw in bound:
                raise ExportError("BAD_PRIVATE_SOURCE_ID")
            bound.add(raw)
    except ExportError:
        raise
    except (OSError, TypeError, ValueError):
        raise ExportError("BAD_STAGED_DATASET") from None
    if bound != set(raw_keys):
        raise ExportError("BAD_PRIVATE_SOURCE_ID")


def _private_product_source_context(
    bitrix_root: Path,
) -> tuple[set[str], set[str]]:
    """Prove every product row belongs to a known deal and exact catalog row."""
    deals = list(_staged_rows(bitrix_root, "deals"))
    deal_ids: set[str] = set()
    raw_deal_ids: list[str] = []
    for deal in deals:
        canonical, raw = _canonical_private_source_id(
            deal.get("ID"), "BAD_PRIVATE_SOURCE_ID"
        )
        if canonical in deal_ids:
            raise ExportError("BAD_PRIVATE_SOURCE_ID")
        deal_ids.add(canonical)
        raw_deal_ids.append(raw)
    _verify_private_source_keys(bitrix_root, "deals", raw_deal_ids, key_field="ID")

    products = list(_staged_rows(bitrix_root, "product_catalog_evidence"))
    product_ids: set[str] = set()
    raw_product_ids: list[str] = []
    for product in products:
        if set(product) != {"ID", "XML_ID", "CODE", "NAME"}:
            raise ExportError("BAD_PRODUCT_CATALOG_EVIDENCE")
        canonical, raw = _canonical_private_source_id(
            product.get("ID"), "BAD_PRODUCT_CATALOG_EVIDENCE"
        )
        if canonical in product_ids or any(
            product.get(field) is not None and not isinstance(product.get(field), str)
            for field in ("XML_ID", "CODE", "NAME")
        ):
            raise ExportError("BAD_PRODUCT_CATALOG_EVIDENCE")
        product_ids.add(canonical)
        raw_product_ids.append(raw)
    _verify_private_source_keys(
        bitrix_root, "product_catalog_evidence", raw_product_ids, key_field="ID",
    )

    rows_by_deal = list(_staged_rows(bitrix_root, "deal_product_rows"))
    row_deal_ids: set[str] = set()
    raw_row_deal_ids: list[str] = []
    referenced_products: set[str] = set()
    seen_row_ids: set[str] = set()
    for envelope in rows_by_deal:
        if set(envelope) != {"deal_id", "rows"}:
            raise ExportError("BAD_PRODUCT_ROW_LINK")
        deal_id, raw_deal_id = _canonical_private_source_id(
            envelope.get("deal_id"), "BAD_PRODUCT_ROW_LINK"
        )
        if deal_id not in deal_ids or deal_id in row_deal_ids:
            raise ExportError("BAD_PRODUCT_ROW_LINK")
        row_deal_ids.add(deal_id)
        raw_row_deal_ids.append(raw_deal_id)
        rows = envelope.get("rows")
        if not isinstance(rows, list):
            raise ExportError("BAD_PRODUCT_ROWS")
        for row in rows:
            if not isinstance(row, dict):
                raise ExportError("BAD_PRODUCT_ROWS")
            row_id, _ = _canonical_private_source_id(
                row.get("ID"), "BAD_PRODUCT_ROW_LINK"
            )
            product_id, _ = _canonical_private_source_id(
                row.get("PRODUCT_ID"), "BAD_PRODUCT_ROW_LINK"
            )
            if row_id in seen_row_ids:
                raise ExportError("BAD_PRODUCT_ROW_LINK")
            seen_row_ids.add(row_id)
            owner_id = row.get("OWNER_ID")
            if owner_id not in (None, ""):
                owner_canonical, _ = _canonical_private_source_id(
                    owner_id, "BAD_PRODUCT_ROW_LINK"
                )
                if owner_canonical != deal_id:
                    raise ExportError("BAD_PRODUCT_ROW_LINK")
            if row.get("OWNER_TYPE") not in (None, "", "D"):
                raise ExportError("BAD_PRODUCT_ROW_LINK")
            referenced_products.add(product_id)
    if row_deal_ids != deal_ids:
        raise ExportError("BAD_PRODUCT_ROW_LINK")
    _verify_private_source_keys(
        bitrix_root, "deal_product_rows", raw_row_deal_ids, key_field="deal_id",
    )
    if referenced_products != product_ids:
        raise ExportError("PRODUCT_CATALOG_EVIDENCE_MISMATCH")
    return deal_ids, product_ids


def stage_import_cache(
    bitrix_root: Path, onec_root: Path, output: Path,
    binary_root: Path | None = None,
) -> dict[str, Any]:
    """Seal current private source snapshots as a local-only importer cache.

    Supported task metadata and deal product rows are staged for the importer.
    Unsupported source groups and task file/mail sidecars remain blocked.
    """
    roots = ((bitrix_root, PRIVATE_BITRIX_DATASETS), (onec_root, PRIVATE_ONEC_DATASETS))
    if (not all(root.is_absolute() and root.is_dir() and not root.is_symlink()
                and not (root / "manifest.json").is_symlink() for root, _ in roots)
            or not output.is_absolute() or output.is_symlink()):
        raise ExportError("BAD_PRIVATE_STAGE_PATH")
    source_roots = [root for root, _ in roots]
    if binary_root is not None:
        if not binary_root.is_absolute() or not binary_root.is_dir() or binary_root.is_symlink():
            raise ExportError("BAD_BINARY_SNAPSHOT")
        source_roots.append(binary_root)
        try:
            binary_manifest_digest = hashlib.sha256(
                (binary_root / "manifest.json").read_bytes()
            ).hexdigest()
        except OSError:
            raise ExportError("BAD_BINARY_SNAPSHOT") from None
    else:
        binary_manifest_digest = None
    if any(output.resolve() == root.resolve() or root.resolve() in output.resolve().parents
           for root in source_roots):
        raise ExportError("BAD_PRIVATE_STAGE_PATH")
    manifests: list[tuple[Path, dict[str, Any], str]] = []
    for root, expected_names in roots:
        try:
            body = (root / "manifest.json").read_bytes()
            manifest = json.loads(body, object_pairs_hook=_json_object_without_duplicate_keys)
        except (OSError, ValueError):
            raise ExportError("BAD_PRIVATE_SOURCE_MANIFEST") from None
        if (not isinstance(manifest, dict) or set(manifest) != expected_names
                or any(not isinstance(entry, dict)
                       or type(entry.get("records")) is not int or entry["records"] < 0
                       or type(entry.get("bytes")) is not int or entry["bytes"] < 0
                       or not isinstance(entry.get("sha256"), str)
                       or len(entry["sha256"]) != 64
                       for entry in manifest.values())):
            raise ExportError("BAD_PRIVATE_SOURCE_MANIFEST")
        manifests.append((root, manifest, hashlib.sha256(body).hexdigest()))
    output.mkdir(mode=0o700 if os.name == "posix" else 0o777, parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ExportError("OUTPUT_NOT_EMPTY")
    if os.name == "posix" and output.stat().st_mode & 0o077:
        raise ExportError("PRIVATE_OUTPUT_PERMISSIONS")
    (output / "PRIVATE_CACHE_FORMAT").write_text("CRM-LIVE-001-private-cache-v1\n", encoding="ascii")
    (output / "PRIVATE_CACHE_INCOMPLETE").touch(exist_ok=False)
    known_deal_ids, catalog_product_ids = _private_product_source_context(
        bitrix_root
    )
    cache: dict[str, dict[str, int | str]] = {}
    blocked: dict[str, int] = {}
    recording_refs = 0
    timeline_attachment_refs = 0
    task_attachment_rows = 0
    task_mail_rows = 0
    for root, manifest, _ in manifests:
        for source_name in sorted(manifest):
            cache_name = PRIVATE_CACHE_MAP.get(source_name)
            seen: set[str] = set()
            fingerprint = hashlib.sha256()
            size = 0
            count = 0
            stream = (output / f"{cache_name}.jsonl").open("xb") if cache_name else None
            try:
                for row in _staged_rows(root, source_name):
                    count += 1
                    if stream is None:
                        continue
                    if source_name == "timeline_comments":
                        entity_type = row.get("ENTITY_TYPE")
                        if entity_type not in {"deal", "lead"}:
                            raise ExportError("BAD_PRIVATE_SOURCE_ID")
                        identity = entity_type + ":" + _positive_id(row.get("ID"), "BAD_PRIVATE_SOURCE_ID")
                        _positive_id(row.get("ENTITY_ID"), "BAD_PRIVATE_SOURCE_ID")
                        files = row.get("FILES")
                        if files is None:
                            files = {}
                        if not isinstance(files, dict):
                            raise ExportError("BAD_COMMENT_FILES")
                        for file_key, file_row in files.items():
                            if (not isinstance(file_row, dict)
                                    or _positive_id(file_key, "BAD_COMMENT_FILE_ID")
                                    != _positive_id(file_row.get("id"), "BAD_COMMENT_FILE_ID")):
                                raise ExportError("COMMENT_FILE_ID_MISMATCH")
                        timeline_attachment_refs += len(files)
                    elif source_name == "tasks":
                        task_ids = []
                        for field in ("id", "ID"):
                            value = row.get(field)
                            if value in (None, ""):
                                continue
                            if isinstance(value, bool):
                                raise ExportError("BAD_PRIVATE_SOURCE_ID")
                            if isinstance(value, int):
                                task_id = str(value)
                            elif isinstance(value, str):
                                task_id = value
                            else:
                                raise ExportError("BAD_PRIVATE_SOURCE_ID")
                            if not re.fullmatch(r"[1-9][0-9]*", task_id):
                                raise ExportError("BAD_PRIVATE_SOURCE_ID")
                            task_ids.append(task_id)
                        if not task_ids or len(set(task_ids)) != 1:
                            raise ExportError("BAD_PRIVATE_SOURCE_ID")
                        identity = task_ids[0]
                        if any(
                            field in row and row[field] not in (None, "", [])
                            for field in ("ufTaskWebdavFiles", "UF_TASK_WEBDAV_FILES")
                        ):
                            task_attachment_rows += 1
                        if any(
                            field in row and row[field] not in (None, "", [])
                            for field in ("ufMailMessage", "UF_MAIL_MESSAGE")
                        ):
                            task_mail_rows += 1
                    elif source_name == "deal_product_rows":
                        canonical, _ = _canonical_private_source_id(
                            row.get("deal_id"), "BAD_PRODUCT_ROW_LINK"
                        )
                        if canonical not in known_deal_ids:
                            raise ExportError("BAD_PRODUCT_ROW_LINK")
                        identity = canonical
                    elif source_name == "product_catalog_evidence":
                        canonical, _ = _canonical_private_source_id(
                            row.get("ID"), "BAD_PRODUCT_CATALOG_EVIDENCE"
                        )
                        if canonical not in catalog_product_ids:
                            raise ExportError("BAD_PRODUCT_CATALOG_EVIDENCE")
                        identity = canonical
                    else:
                        identity_field = ("Ref_Key" if source_name.startswith("Catalog_")
                                          else "deal_id" if source_name == "deal_product_rows"
                                          else "ID")
                        identity = str(row.get(identity_field) or "")
                    if not identity or identity in seen:
                        raise ExportError("BAD_PRIVATE_SOURCE_ID")
                    seen.add(identity)
                    if source_name == "calls" and (row.get("CALL_RECORD_URL") or row.get("RECORD_FILE_ID")):
                        recording_refs += 1
                    line = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8") + b"\n"
                    stream.write(line)
                    fingerprint.update(line)
                    size += len(line)
            finally:
                if stream is not None:
                    stream.close()
            if count != manifest[source_name]["records"]:
                raise ExportError("STAGED_DATASET_MISMATCH")
            if cache_name:
                cache[cache_name] = {"records": count, "bytes": size,
                                     "sha256": fingerprint.hexdigest()}
            elif count and source_name != "field_schemas":
                blocked[source_name] = count
    if task_attachment_rows:
        blocked["task_attachments_unimported"] = task_attachment_rows
    if task_mail_rows:
        blocked["task_mail_unimported"] = task_mail_rows
    if recording_refs:
        blocked["call_recordings"] = recording_refs
    binary_files_summary = None
    if binary_root is not None:
        binary_cache, binary_files_summary, lead_refs = _stage_comment_binary_cache(
            bitrix_root, binary_root, output
        )
        cache.update(binary_cache)
        if lead_refs:
            blocked["timeline_lead_attachments"] = lead_refs
    elif timeline_attachment_refs:
        blocked["timeline_attachments"] = timeline_attachment_refs
    for root, _, digest in manifests:
        if hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() != digest:
            raise ExportError("PRIVATE_SOURCE_CHANGED")
    if binary_root is not None and binary_manifest_digest != hashlib.sha256(
        (binary_root / "manifest.json").read_bytes()
    ).hexdigest():
        raise ExportError("PRIVATE_SOURCE_CHANGED")
    format_name = "CRM-LIVE-001-private-cache-v2" if binary_root is not None else "CRM-LIVE-001-private-cache-v1"
    summary = {
        "format": format_name,
        "ready_for_load": not blocked,
        "cache": cache,
        "blocked_source_groups": blocked,
        "source_manifests": {"bitrix": manifests[0][2], "onec": manifests[1][2]},
    }
    if binary_root is not None:
        summary["source_manifests"]["binary"] = binary_manifest_digest
        summary["comment_binary_files"] = binary_files_summary
    manifest_body = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with (output / "private-source-manifest.json").open("xb") as stream:
        stream.write(manifest_body)
    (output / "PRIVATE_CACHE_FORMAT").write_text(
        format_name + ":" + hashlib.sha256(manifest_body).hexdigest() + "\n",
        encoding="ascii",
    )
    (output / "PRIVATE_CACHE_INCOMPLETE").unlink()
    return summary


def _positive_id(value: Any, code: str) -> str:
    candidate = str(value or "")
    if (not candidate.isascii() or not candidate.isdigit()
            or int(candidate) < 1):
        raise ExportError(code)
    return candidate


def _call_id_field(value: Any, code: str) -> str:
    if value is None or value == "":
        return ""
    if (not isinstance(value, str) or value != value.strip() or len(value) > 64
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ExportError(code)
    return value


def _optional_call_file_id(value: Any, code: str) -> str:
    return "" if value is None or value == "" else _positive_id(value, code)


def _optional_call_owner_type(value: Any, code: str) -> str:
    return _call_id_field(value, code)


def _optional_call_owner_id(value: Any, code: str) -> str:
    return _optional_call_file_id(value, code)


def _task_attachment_id(value: Any) -> str:
    # The task API can return an attached-object ID as either 491 or "n491".
    if isinstance(value, str) and value.startswith("n"):
        value = value[1:]
    return _positive_id(value, "BAD_TASK_ATTACHMENT_ID")


def _crm_file_ids(value: Any) -> set[str]:
    if value is None or value == "" or value == [] or value == 0 or value == "0":
        return set()
    entries = value if isinstance(value, list) else [value]
    ids: list[str] = []
    for entry in entries:
        raw_id = (entry.get("id", entry.get("ID")) if isinstance(entry, dict) else entry)
        ids.append(_positive_id(raw_id, "BAD_CRM_FILE_ID"))
    if len(ids) != len(set(ids)):
        raise ExportError("DUPLICATE_CRM_FILE_ID")
    return set(ids)


def _crm_item_file_values(item: dict[str, Any], field_names: list[str],
                          webhook: str) -> dict[str, list[dict[str, str]]]:
    values: dict[str, list[dict[str, str]]] = {}
    for field_name in field_names:
        raw = item.get(field_name)
        if raw is None or raw == "" or raw == [] or raw == 0 or raw == "0":
            continue
        entries = raw if isinstance(raw, list) else [raw]
        if any(not isinstance(entry, dict) for entry in entries):
            raise ExportError("BAD_CRM_FILE_FIELD")
        values[field_name] = []
        for entry in entries:
            file_id = _positive_id(entry.get("id"), "BAD_CRM_FILE_ID")
            machine_url = _signed_download_url(entry.get("urlMachine"), crm_webhook=webhook)
            values[field_name].append({"id": file_id, "urlMachine": machine_url})
        if len(values[field_name]) != len({row["id"] for row in values[field_name]}):
            raise ExportError("DUPLICATE_CRM_FILE_ID")
    return values


def _signed_download_url(value: Any, *, crm_webhook: str | None = None) -> str:
    if not isinstance(value, str):
        raise ExportError("BAD_DOWNLOAD_URL")
    try:
        parts = urlsplit(value)
        allowed_paths = {"/rest/download.json"}
        if crm_webhook is not None:
            webhook_path = urlsplit(_validate_webhook(crm_webhook)).path
            allowed_paths.update({"/rest/crm.controller.item.getFile.json",
                                  webhook_path + "/crm.controller.item.getFile/",
                                  webhook_path + "/crm.controller.item.getFile.json"})
        valid = (parts.scheme == "https" and parts.hostname == PORTAL
                 and parts.port in (None, 443) and not parts.username
                 and not parts.password and not parts.fragment and parts.path in allowed_paths)
    except ValueError:
        valid = False
    if not valid:
        raise ExportError("BAD_DOWNLOAD_URL")
    return value


class BinaryDataset:
    def __init__(self, root: Path):
        self.folder = root / "binary_files"
        self.folder.mkdir(mode=0o700 if os.name == "posix" else 0o777)
        self.files: list[tuple[str, int, str]] = []

    def add(self, key: str, url: str, session: requests.Session, expected_size: int | None,
            *, crm_webhook: str | None = None) -> dict[str, Any]:
        filename = hashlib.sha256(key.encode("ascii")).hexdigest() + ".bin"
        target = self.folder / filename
        signed_url = _signed_download_url(url, crm_webhook=crm_webhook)
        try:
            response = session.get(
                signed_url, stream=True, timeout=120, allow_redirects=False,
                headers={"User-Agent": "CRM-LIVE-001/1.0", "Accept": "*/*",
                         "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                         "Referer": f"https://{PORTAL}/"},
            )
        except requests.RequestException:
            raise ExportError("BINARY_NETWORK_ERROR") from None
        try:
            if response.status_code != 200:
                raise ExportError("BINARY_HTTP_" + str(response.status_code))
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            disposition = str(response.headers.get("Content-Disposition") or "").lower()
            explicit_file = ((expected_size is not None or crm_webhook is not None)
                             and disposition.startswith(("attachment", "inline")))
            if content_type in {"text/html", "application/json"} and not explicit_file:
                raise ExportError("BINARY_NOT_FILE")
            size_header = response.headers.get("Content-Length")
            if size_header is not None and (not str(size_header).isdigit()
                                            or int(size_header) > 2 * 1024**3):
                raise ExportError("BINARY_BAD_SIZE")
            digest = hashlib.sha256()
            count = 0
            prefix = bytearray()
            try:
                with target.open("xb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not isinstance(chunk, bytes):
                            raise ExportError("BINARY_BAD_CHUNK")
                        if len(prefix) < 32:
                            prefix.extend(chunk[:32 - len(prefix)])
                        count += len(chunk)
                        if count > 2 * 1024**3:
                            raise ExportError("BINARY_TOO_LARGE")
                        digest.update(chunk)
                        stream.write(chunk)
                if (not explicit_file and bytes(prefix).lstrip().lower()
                        .startswith((b"<!doctype html", b"<html"))):
                    raise ExportError("BINARY_NOT_FILE")
                if ((expected_size is not None and count != expected_size)
                        or (size_header is not None and count != int(size_header))):
                    raise ExportError("BINARY_SIZE_MISMATCH")
            except Exception:
                target.unlink(missing_ok=True)
                raise
            result = {"key": key, "filename": filename, "bytes": count,
                      "sha256": digest.hexdigest(), "content_type": content_type}
            self.files.append((filename, count, digest.hexdigest()))
            return result
        except requests.RequestException:
            raise ExportError("BINARY_NETWORK_ERROR") from None
        finally:
            response.close()

    def summary(self) -> dict[str, int | str]:
        fingerprint = hashlib.sha256()
        for filename, size, digest in sorted(self.files):
            fingerprint.update(f"{filename}:{size}:{digest}\n".encode("ascii"))
        return {"records": len(self.files), "bytes": sum(size for _, size, _ in self.files),
                "sha256": fingerprint.hexdigest()}


def export_binaries(
    webhook: str, metadata: Path, output: Path, *, session: requests.Session | None = None,
) -> dict[str, dict[str, int | str]]:
    """Download supported CRM binaries from a verified private metadata stage."""
    client = BitrixReadOnly(webhook, session)
    output.mkdir(mode=0o700 if os.name == "posix" else 0o777, parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ExportError("OUTPUT_NOT_EMPTY")
    owner_ids = {
        entity_type: {_positive_id(row.get("ID"), "BAD_COMMENT_OWNER")
                      for row in _staged_rows(metadata, dataset)}
        for entity_type, dataset in (("deal", "deals"), ("lead", "leads"))
    }
    comment_refs: list[tuple[str, str, str, str]] = []
    seen_comments: set[tuple[str, str]] = set()
    for row in _staged_rows(metadata, "timeline_comments"):
        comment_id = _positive_id(row.get("ID"), "BAD_COMMENT_ID")
        entity_type = row.get("ENTITY_TYPE")
        if entity_type not in owner_ids:
            raise ExportError("BAD_COMMENT_OWNER")
        entity_id = _positive_id(row.get("ENTITY_ID"), "BAD_COMMENT_OWNER")
        if entity_id not in owner_ids[entity_type]:
            raise ExportError("COMMENT_WRONG_OWNER")
        comment_key = (entity_type, comment_id)
        if comment_key in seen_comments:
            raise ExportError("DUPLICATE_COMMENT_ID")
        seen_comments.add(comment_key)
        files = row.get("FILES")
        if files is None:
            files = {}
        if not isinstance(files, dict):
            raise ExportError("BAD_COMMENT_FILES")
        for file_key, file_row in files.items():
            if not isinstance(file_row, dict):
                raise ExportError("BAD_COMMENT_FILES")
            disk_id = _positive_id(file_row.get("id"), "BAD_COMMENT_FILE_ID")
            if _positive_id(file_key, "BAD_COMMENT_FILE_ID") != disk_id:
                raise ExportError("COMMENT_FILE_ID_MISMATCH")
            comment_refs.append((entity_type, entity_id, comment_id, disk_id))
    task_refs: list[tuple[str, str]] = []
    for row in _staged_rows(metadata, "tasks"):
        task_id = _positive_id(row.get("id") or row.get("ID"), "BAD_TASK_ID")
        attachment_ids = row.get("ufTaskWebdavFiles", row.get("UF_TASK_WEBDAV_FILES", [])) or []
        if not isinstance(attachment_ids, list):
            raise ExportError("BAD_TASK_FILES")
        for value in attachment_ids:
            task_refs.append((task_id, _task_attachment_id(value)))
    call_refs: list[tuple[str, str, str, bool, str, str, str]] = []
    unavailable_recordings = 0
    for row in _staged_rows(metadata, "calls"):
        call_id = _positive_id(row.get("ID"), "BAD_CALL_ID")
        url = row.get("CALL_RECORD_URL")
        record_file_id = _optional_call_file_id(
            row.get("RECORD_FILE_ID"), "BAD_CALL_FILE_ID"
        )
        if url:
            _signed_download_url(url)
        if url or record_file_id:
            call_refs.append((
                call_id, _call_id_field(row.get("CALL_ID"), "BAD_CALL_ID"),
                record_file_id, bool(url),
                _optional_call_owner_type(row.get("CRM_ENTITY_TYPE"), "BAD_CALL_OWNER_TYPE"),
                _optional_call_owner_id(row.get("CRM_ENTITY_ID"), "BAD_CALL_OWNER_ID"),
                _optional_call_owner_id(row.get("PORTAL_USER_ID"), "BAD_CALL_USER_ID"),
            ))
    crm_file_stages: list[tuple[str, str, list[str], dict[str, set[str]]]] = []
    seen_crm_file_items: set[tuple[str, str]] = set()
    for row in _staged_rows(metadata, "crm_file_items"):
        entity_type = row.get("entity_type")
        if entity_type not in {"deals", "contacts", "leads"}:
            raise ExportError("BAD_CRM_FILE_ENTITY")
        entity_id = _positive_id(row.get("entity_id"), "BAD_CRM_FILE_ENTITY")
        source_key = (entity_type, entity_id)
        if source_key in seen_crm_file_items:
            raise ExportError("DUPLICATE_CRM_FILE_ENTITY")
        seen_crm_file_items.add(source_key)
        field_names = row.get("file_field_names")
        if (not isinstance(field_names, list) or not field_names
                or len(field_names) != len(set(field_names))
                or any(not isinstance(name, str) or not name.startswith("UF_") for name in field_names)):
            raise ExportError("BAD_CRM_FILE_FIELD")
        fields = row.get("fields")
        if not isinstance(fields, dict) or set(fields) - set(field_names):
            raise ExportError("BAD_CRM_FILE_FIELD")
        staged_ids: dict[str, set[str]] = {}
        for field_name in field_names:
            values = fields.get(field_name, [])
            if not isinstance(values, list):
                raise ExportError("BAD_CRM_FILE_FIELD")
            staged_ids[field_name] = _crm_file_ids(values)
            for value in values:
                if not isinstance(value, dict):
                    raise ExportError("BAD_CRM_FILE_FIELD")
                _signed_download_url(value.get("urlMachine"), crm_webhook=client.webhook)
        crm_file_stages.append((entity_type, entity_id, field_names, staged_ids))

    links = Dataset(output, "binary_links")
    inventory = Dataset(output, "binary_inventory")
    binaries = BinaryDataset(output)
    downloaded: set[str] = set()
    for entity_type, entity_id, field_names, staged_ids in crm_file_stages:
        entity_type_id = {"deals": 2, "contacts": 3, "leads": 1}[entity_type]
        targets = [(field_name, file_id)
                   for field_name in field_names
                   for file_id in sorted(staged_ids[field_name], key=int)]
        if not targets:
            targets = [(None, None)]
        for target_field, target_id in targets:
            # Machine URLs are short-lived. Refresh immediately before each GET.
            fresh_result = client.call("crm.item.get", {
                "entityTypeId": entity_type_id, "id": int(entity_id),
                "useOriginalUfNames": "Y",
            })["result"]
            fresh_item = fresh_result.get("item") if isinstance(fresh_result, dict) else None
            if not isinstance(fresh_item, dict) or str(fresh_item.get("id")) != entity_id:
                raise ExportError("CRM_FILE_ITEM_MISMATCH")
            fresh_fields = _crm_item_file_values(fresh_item, field_names, client.webhook)
            for field_name in field_names:
                if {entry["id"] for entry in fresh_fields.get(field_name, [])} != staged_ids[field_name]:
                    raise ExportError("CRM_FILE_SOURCE_CHANGED")
            if target_field is None or target_id is None:
                continue
            target = next(entry for entry in fresh_fields[target_field]
                          if entry["id"] == target_id)
            key = ":".join(("crm", entity_type, entity_id, target_field, target_id))
            result = binaries.add(key, target["urlMachine"], client.session, None,
                                  crm_webhook=client.webhook)
            inventory.add(key, result)
            links.add(key, {"source": "crm_file", "entity_type": entity_type,
                            "source_id": entity_id, "field": target_field,
                            "file_id": target_id, "binary_key": key})
    for entity_type, entity_id, comment_id, disk_id in comment_refs:
        key = "disk:" + disk_id
        links.add(":".join(("comment", entity_type, entity_id, comment_id, disk_id)),
                  {"source": "comment", "entity_type": entity_type,
                   "entity_id": entity_id, "source_id": comment_id,
                   "file_id": disk_id, "binary_key": key})
        if key not in downloaded:
            file_row = client.call("disk.file.get", {"id": int(disk_id)})["result"]
            if not isinstance(file_row, dict) or str(file_row.get("ID")) != disk_id:
                raise ExportError("DISK_FILE_MISMATCH")
            size = file_row.get("SIZE")
            if not str(size).isdigit():
                raise ExportError("DISK_BAD_SIZE")
            result = binaries.add(key, file_row.get("DOWNLOAD_URL"), client.session, int(size))
            inventory.add(key, {**result, "name": file_row.get("NAME")})
            downloaded.add(key)
    for task_id, attachment_id in task_refs:
        attached = client.call("disk.attachedObject.get", {"id": int(attachment_id)})["result"]
        if (not isinstance(attached, dict) or str(attached.get("ID")) != attachment_id
                or str(attached.get("ENTITY_TYPE") or "").lower() != "tasks_task"
                or str(attached.get("ENTITY_ID")) != task_id):
            raise ExportError("TASK_ATTACHMENT_MISMATCH")
        disk_id = _positive_id(attached.get("OBJECT_ID"), "BAD_TASK_FILE_ID")
        key = "disk:" + disk_id
        links.add("task:" + task_id + ":" + attachment_id,
                  {"source": "task", "source_id": task_id, "attachment_id": attachment_id,
                   "binary_key": key})
        if key not in downloaded:
            file_row = client.call("disk.file.get", {"id": int(disk_id)})["result"]
            if not isinstance(file_row, dict) or str(file_row.get("ID")) != disk_id:
                raise ExportError("DISK_FILE_MISMATCH")
            size = file_row.get("SIZE")
            if not str(size).isdigit():
                raise ExportError("DISK_BAD_SIZE")
            result = binaries.add(key, file_row.get("DOWNLOAD_URL"), client.session, int(size))
            inventory.add(key, {**result, "name": file_row.get("NAME")})
            downloaded.add(key)
    for (call_id, source_call_id, record_file_id, had_url,
         source_owner_type, source_owner_id, source_user_id) in call_refs:
        fresh = client.call("voximplant.statistic.get", {
            "FILTER": {"ID": [int(call_id)]}, "SORT": "ID", "ORDER": "ASC",
        })["result"]
        if (not isinstance(fresh, list) or len(fresh) != 1
                or not isinstance(fresh[0], dict) or str(fresh[0].get("ID")) != call_id):
            raise ExportError("CALL_RECORD_MISMATCH")
        fresh_row = fresh[0]
        if (_call_id_field(fresh_row.get("CALL_ID"), "CALL_RECORD_CHANGED") != source_call_id
                or _optional_call_file_id(
                    fresh_row.get("RECORD_FILE_ID"), "CALL_RECORD_CHANGED"
                ) != record_file_id
                or _optional_call_owner_type(
                    fresh_row.get("CRM_ENTITY_TYPE"), "CALL_RECORD_CHANGED"
                ) != source_owner_type
                or _optional_call_owner_id(
                    fresh_row.get("CRM_ENTITY_ID"), "CALL_RECORD_CHANGED"
                ) != source_owner_id
                or _optional_call_owner_id(
                    fresh_row.get("PORTAL_USER_ID"), "CALL_RECORD_CHANGED"
                ) != source_user_id):
            raise ExportError("CALL_RECORD_CHANGED")
        url = fresh_row.get("CALL_RECORD_URL")
        if not url:
            if had_url:
                raise ExportError("CALL_RECORD_UNAVAILABLE")
            unavailable_recordings += 1
            continue
        key = "call:" + call_id
        result = binaries.add(key, _signed_download_url(url), client.session, None)
        inventory.add(key, result)
        links.add(key, {
            "source": "call", "source_id": call_id,
            "call_id": source_call_id or call_id,
            "entity_type": source_owner_type, "entity_id": source_owner_id,
            "portal_user_id": source_user_id,
            "binary_key": key,
        })
    summary = {"binary_files": binaries.summary(), "binary_inventory": inventory.summary(),
               "binary_links": links.summary(), "unavailable_recordings": {"records": unavailable_recordings}}
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, sort_keys=True, indent=2)
    return summary


def export(webhook: str, output: Path, *, session: requests.Session | None = None) -> dict[str, dict[str, int | str]]:
    client = BitrixReadOnly(webhook, session)
    output.mkdir(mode=0o700 if os.name == "posix" else 0o777, parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ExportError("OUTPUT_NOT_EMPTY")
    datasets = {name: Dataset(output, name) for name, _, _ in LISTS}
    field_schemas = Dataset(output, "field_schemas")
    selected_fields: dict[str, list[str]] = {}
    custom_file_fields: dict[str, list[str]] = {}
    for name, method in SCHEMA_METHODS.items():
        fields = client.call(method, {})["result"]
        if not isinstance(fields, dict) or not fields:
            raise ExportError("BAD_FIELD_SCHEMA_" + name)
        multiple = [key for key, spec in fields.items()
                    if (isinstance(key, str) and isinstance(spec, dict)
                        and spec.get("isMultiple") is True and key not in {"COMPANY_IDS", "CONTACT_IDS"})]
        selected_fields[name] = ["*", "UF_*", *sorted(multiple)]
        custom_file_fields[name] = sorted(
            key for key, spec in fields.items()
            if (isinstance(key, str) and key.startswith("UF_") and isinstance(spec, dict)
                and (spec.get("type") == "file" or spec.get("userTypeId") == "file"))
        )
        field_schemas.add(name, {"ID": name, "fields": fields})
    datasets[field_schemas.name] = field_schemas
    crm_file_items = Dataset(output, "crm_file_items")
    deal_ids: list[str] = []
    contact_ids: list[str] = []
    lead_ids: list[str] = []
    company_ids: set[str] = set()
    for name, method, params in LISTS:
        dataset = datasets[name]
        call_params = {**params, "select": selected_fields[name]} if name in selected_fields else params
        for row in client.pages(method, call_params):
            key = str(row.get("ID") or "")
            dataset.add(key, row)
            if name in custom_file_fields and custom_file_fields[name]:
                entity_type = {"deals": 2, "contacts": 3, "leads": 1}[name]
                item_result = client.call("crm.item.get", {
                    "entityTypeId": entity_type, "id": int(_positive_id(key, "BAD_CRM_ITEM_ID")),
                    "useOriginalUfNames": "Y",
                })["result"]
                item = item_result.get("item") if isinstance(item_result, dict) else None
                if not isinstance(item, dict) or str(item.get("id")) != key:
                    raise ExportError("CRM_FILE_ITEM_MISMATCH")
                file_values = _crm_item_file_values(item, custom_file_fields[name], webhook)
                for field_name in custom_file_fields[name]:
                    if _crm_file_ids(row.get(field_name)) != {
                        value["id"] for value in file_values.get(field_name, [])
                    }:
                        raise ExportError("CRM_FILE_ID_MISMATCH")
                crm_file_items.add(name + ":" + key,
                                   {"entity_type": name, "entity_id": key,
                                    "file_field_names": custom_file_fields[name],
                                    "fields": file_values})
            if name == "deals":
                deal_ids.append(key)
            elif name == "contacts":
                contact_ids.append(key)
            elif name == "leads":
                lead_ids.append(key)
            if name in {"deals", "contacts", "leads"} and row.get("COMPANY_ID") not in (None, "", 0, "0"):
                company_ids.add(str(row["COMPANY_ID"]))
            elif name == "calls" and row.get("CRM_ENTITY_TYPE") == "COMPANY" and row.get("CRM_ENTITY_ID"):
                company_ids.add(str(row["CRM_ENTITY_ID"]))
            if name == "activities":
                if str(row.get("OWNER_TYPE_ID") or "") == "4" and row.get("OWNER_ID"):
                    company_ids.add(str(row["OWNER_ID"]))
                communications = row.get("COMMUNICATIONS")
                if isinstance(communications, list):
                    for entry in communications:
                        if (isinstance(entry, dict) and str(entry.get("ENTITY_TYPE_ID") or "") == "4"
                                and entry.get("ENTITY_ID")):
                            company_ids.add(str(entry["ENTITY_ID"]))
    datasets[crm_file_items.name] = crm_file_items

    contact_company_links = Dataset(output, "contact_company_links")
    for contact_id in contact_ids:
        links = client.call("crm.contact.company.items.get", {"id": contact_id})["result"]
        if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
            raise ExportError("BAD_CONTACT_COMPANY_LINKS")
        contact_company_links.add(contact_id, {"contact_id": contact_id, "links": links})
        company_ids.update(str(link["COMPANY_ID"]) for link in links if link.get("COMPANY_ID") not in (None, "", 0, "0"))
    datasets[contact_company_links.name] = contact_company_links

    deal_contact_links = Dataset(output, "deal_contact_links")
    for deal_id in deal_ids:
        links = client.call("crm.deal.contact.items.get", {"id": deal_id})["result"]
        if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
            raise ExportError("BAD_DEAL_CONTACT_LINKS")
        deal_contact_links.add(deal_id, {"deal_id": deal_id, "links": links})
    datasets[deal_contact_links.name] = deal_contact_links

    company_names = Dataset(output, "company_name_evidence")
    requisites = Dataset(output, "requisites")
    ordered_company_ids = sorted(company_ids, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))
    for start in range(0, len(ordered_company_ids), 50):
        chunk = ordered_company_ids[start:start + 50]
        for row in client.pages("crm.requisite.list", {
            "order": {"ID": "ASC"}, "filter": {"ENTITY_TYPE_ID": 4, "@ENTITY_ID": chunk},
            "select": ["ID", "ENTITY_ID", "RQ_INN"],
        }):
            if str(row.get("ENTITY_ID") or "") not in company_ids:
                raise ExportError("UNREQUESTED_REQUISITE_COMPANY_ID")
            requisites.add(str(row.get("ID") or ""), row)
        for row in client.pages("crm.company.list", {
            "order": {"ID": "ASC"}, "filter": {"@ID": chunk}, "select": ["ID", "TITLE"],
        }):
            if set(row) - {"ID", "TITLE"}:
                raise ExportError("UNEXPECTED_COMPANY_FIELDS")
            key = str(row.get("ID") or "")
            if key not in company_ids:
                raise ExportError("UNREQUESTED_COMPANY_ID")
            company_names.add(key, row)
    datasets[requisites.name] = requisites
    datasets[company_names.name] = company_names
    unresolved_companies = Dataset(output, "unresolved_company_ids")
    for company_id in sorted(company_ids - company_names.keys):
        unresolved_companies.add(company_id, {"company_id": company_id})
    datasets[unresolved_companies.name] = unresolved_companies

    product_rows = Dataset(output, "deal_product_rows")
    product_ids: set[int] = set()
    seen_product_row_ids: set[str] = set()
    for deal_id in deal_ids:
        result = client.call("crm.deal.productrows.get", {"id": deal_id})["result"]
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise ExportError("BAD_PRODUCT_ROWS")
        for row in result:
            row_id = str(row.get("ID") or "")
            product_id = row.get("PRODUCT_ID")
            if (not row_id.isascii() or not row_id.isdigit()
                    or len(row_id) > 20 or int(row_id) < 1
                    or str(int(row_id)) in seen_product_row_ids
                    or isinstance(product_id, bool) or not str(product_id).isascii()
                    or not str(product_id).isdigit()
                    or len(str(product_id)) > 20
                    or (row.get("OWNER_ID") not in (None, "")
                        and str(row["OWNER_ID"]) != deal_id)
                    or row.get("OWNER_TYPE") not in (None, "", "D")):
                raise ExportError("BAD_PRODUCT_ROW_LINK")
            seen_product_row_ids.add(str(int(row_id)))
            if int(product_id) > 0:
                product_ids.add(int(product_id))
        product_rows.add(deal_id, {"deal_id": deal_id, "rows": result})
    datasets[product_rows.name] = product_rows

    catalog_evidence = Dataset(output, "product_catalog_evidence")
    for product_id in sorted(product_ids):
        product = client.call("crm.product.get", {"id": product_id})["result"]
        if (not isinstance(product, dict)
                or str(product.get("ID") or "") != str(product_id)):
            raise ExportError("PRODUCT_DETAIL_MISMATCH")
        catalog_evidence.add(str(product_id), {
            "ID": product_id,
            "XML_ID": product.get("XML_ID"),
            "CODE": product.get("CODE"),
            "NAME": product.get("NAME"),
        })
    datasets[catalog_evidence.name] = catalog_evidence

    comments = Dataset(output, "timeline_comments")
    for entity_type, ids in (("deal", deal_ids), ("lead", lead_ids)):
        for entity_id in ids:
            for row in client.pages("crm.timeline.comment.list", {
                "filter": {"ENTITY_ID": entity_id, "ENTITY_TYPE": entity_type},
                "select": ["ID", "CREATED", "ENTITY_ID", "ENTITY_TYPE", "AUTHOR_ID", "COMMENT", "FILES"],
            }):
                if not row.get("ID"):
                    raise ExportError("COMMENT_WITHOUT_ID")
                if str(row.get("ENTITY_ID") or "") != entity_id or row.get("ENTITY_TYPE") != entity_type:
                    raise ExportError("COMMENT_WRONG_OWNER")
                comments.add(entity_type + ":" + str(row["ID"]), row)
    datasets[comments.name] = comments

    tasks = Dataset(output, "tasks")
    for task_id in client.task_ids():
        result = client.call("tasks.task.get", {
            "taskId": int(task_id),
            "select": ["*", "UF_CRM_TASK", "UF_TASK_WEBDAV_FILES", "UF_MAIL_MESSAGE"],
        })["result"]
        task = result.get("task") if isinstance(result, dict) else None
        if not isinstance(task, dict) or str(task.get("id") or task.get("ID") or "") != task_id:
            raise ExportError("TASK_DETAIL_MISMATCH")
        tasks.add(task_id, task)
    datasets[tasks.name] = tasks

    summary = {name: dataset.summary() for name, dataset in datasets.items()}
    manifest = output / "manifest.json"
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, sort_keys=True, indent=2)
    return summary


def main() -> int:
    os.umask(0o077)
    try:
        if sys.argv[1:] == ["stage"]:
            binary_root = Path("/binaries")
            summary = stage_import_cache(
                Path("/metadata"), Path("/onec"), Path("/private"),
                binary_root if binary_root.exists() else None,
            )
            print("CACHE_STAGED", len(summary["cache"]), len(summary["blocked_source_groups"]),
                  int(summary["ready_for_load"]))
            return 0
        if sys.argv[1:] not in ([], ["binaries"]):
            raise ExportError("BAD_PHASE")
        webhook = Path("/run/secrets/bitrix_webhook").read_text(encoding="utf-8").strip()
        summary = (export_binaries(webhook, Path("/metadata"), Path("/private"))
                   if sys.argv[1:] else export(webhook, Path("/private")))
    except ExportError as exc:
        print("EXPORT_FAILED", str(exc))
        return 1
    except Exception:
        print("EXPORT_FAILED UNEXPECTED_ERROR")
        return 1
    for name, result in summary.items():
        if name == "unavailable_recordings":
            print(name, result["records"])
        else:
            print(name, result["records"], result["bytes"], result["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
