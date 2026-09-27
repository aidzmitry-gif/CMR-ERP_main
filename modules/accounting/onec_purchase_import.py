"""Fail-closed mapping of cached 1C receipt documents to procurement drafts.

This module only builds the existing procurement receipt API payload. It never
creates a draft, resolves references heuristically, calculates VAT, or posts a
ledger entry. Every source reference must be mapped explicitly by an accountant.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

CACHE_SCHEMA = "onec-purchase-cache-v1"
MAPPING_SCHEMA = "onec-purchase-map-v1"
PLAN_SCHEMA = "onec-purchase-draft-plan-v1"


class PurchaseImportError(ValueError):
    """A source package or explicit mapping is incomplete or inconsistent."""


class UnmappedPurchaseDocuments(PurchaseImportError):
    def __init__(self, issues: list[dict[str, str]]):
        self.issues = tuple(issues)
        super().__init__(f"{len(issues)} document(s) need mapping or correction")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PurchaseImportError(f"{label} must be an object")
    return value


def _keys(value: dict[str, Any], required: set[str], label: str) -> None:
    missing = required - value.keys()
    extra = value.keys() - required
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if extra:
            details.append("unknown " + ", ".join(sorted(extra)))
        raise PurchaseImportError(f"{label}: {'; '.join(details)}")


def _positive_id(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise PurchaseImportError(f"{label} must be a positive integer")
    return value


def _nonblank(value: Any, label: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PurchaseImportError(f"{label} must be a nonblank, trimmed string")
    if len(value) > max_length:
        raise PurchaseImportError(f"{label} exceeds {max_length} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PurchaseImportError(f"{label} contains a control character")
    return value


def validate_mapping_profile(profile: Any) -> dict[str, Any]:
    """Validate a complete exact-reference mapping profile before reading rows."""
    profile = _object(profile, "mapping profile")
    _keys(
        profile,
        {"schema_version", "entity", "organization_id", "paths", "currency_refs",
         "suppliers", "contracts", "warehouses", "skus"},
        "mapping profile",
    )
    if profile["schema_version"] != MAPPING_SCHEMA:
        raise PurchaseImportError(f"mapping schema_version must be {MAPPING_SCHEMA}")
    entity = _nonblank(profile["entity"], "entity", max_length=180)
    if not entity.startswith("Document_"):
        raise PurchaseImportError("entity must be an explicit 1C Document_* type")
    suffix = entity[len("Document_"):]
    if not suffix or any(not (char.isalnum() or char == "_") for char in suffix):
        raise PurchaseImportError("entity contains unsupported OData type characters")
    _positive_id(profile["organization_id"], "organization_id")

    paths = _object(profile["paths"], "paths")
    _keys(paths, {"document", "line"}, "paths")
    document_paths = _object(paths["document"], "paths.document")
    _keys(
        document_paths,
        {"number", "document_date", "operation_date", "supplier_ref", "contract_ref",
         "warehouse_ref", "currency_ref", "lines"},
        "paths.document",
    )
    if document_paths["document_date"] != "/Date":
        raise PurchaseImportError("paths.document.document_date must be the 1C system Date field /Date")
    line_paths = _object(paths["line"], "paths.line")
    _keys(
        line_paths,
        {"sku_ref", "quantity", "net_amount", "vat_rate", "vat_amount", "vat_basis"},
        "paths.line",
    )
    for group_name, group in (("document", document_paths), ("line", line_paths)):
        for field, pointer in group.items():
            if (not isinstance(pointer, str) or not pointer.startswith("/")
                    or re.search(r"~(?![01])", pointer)):
                raise PurchaseImportError(f"paths.{group_name}.{field} must be an absolute JSON Pointer")

    currencies = _object(profile["currency_refs"], "currency_refs")
    for ref, currency in currencies.items():
        _nonblank(ref, "currency_refs key", max_length=200)
        if currency != "BYN":
            raise PurchaseImportError("the current owned-inventory receipt flow accepts BYN only")
    if not currencies:
        raise PurchaseImportError("currency_refs must explicitly map at least one 1C currency Ref_Key")

    suppliers = _validate_catalog(profile["suppliers"], "suppliers", {
        "id": "id", "name": "name", "unp": "unp",
    })
    contracts = _validate_catalog(profile["contracts"], "contracts", {
        "id": "id", "number": "number",
    })
    warehouses = _validate_catalog(profile["warehouses"], "warehouses", {
        "id": "id", "code": "code", "title": "title",
    })
    skus = _validate_catalog(profile["skus"], "skus", {
        "id": "id", "code": "code", "title": "title", "unit": "unit",
    })
    if not suppliers or not contracts or not warehouses or not skus:
        raise PurchaseImportError("supplier, contract, warehouse and SKU catalogue maps must be explicit")

    return {
        **profile,
        "entity": entity,
        "paths": {"document": document_paths, "line": line_paths},
        "currency_refs": currencies,
        "suppliers": suppliers,
        "contracts": contracts,
        "warehouses": warehouses,
        "skus": skus,
    }


def _validate_catalog(value: Any, label: str, required: dict[str, str]) -> dict[str, dict[str, Any]]:
    catalog = _object(value, label)
    normalized: dict[str, dict[str, Any]] = {}
    for ref, raw_entry in catalog.items():
        _nonblank(ref, f"{label} source Ref_Key", max_length=200)
        entry = _object(raw_entry, f"{label}[{ref}]")
        _keys(entry, set(required), f"{label}[{ref}]")
        item: dict[str, Any] = {}
        for field, kind in required.items():
            if kind == "id":
                item[field] = _positive_id(entry[field], f"{label}[{ref}].id")
            else:
                item[field] = _nonblank(entry[field], f"{label}[{ref}].{field}", max_length=255)
        normalized[ref] = item
    return normalized


def _pointer(value: Any, pointer: str, label: str) -> Any:
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and str(int(part)) == part:
            index = int(part)
            if index >= len(current):
                raise PurchaseImportError(f"{label}: JSON Pointer index is out of range")
            current = current[index]
        else:
            raise PurchaseImportError(f"{label}: required JSON Pointer value is missing")
    return current


def _source_ref(value: Any, label: str) -> str:
    return _nonblank(value, label, max_length=200)


def _text(value: Any, label: str, *, max_length: int = 200) -> str:
    if not isinstance(value, str):
        raise PurchaseImportError(f"{label} must be text")
    return _nonblank(value, label, max_length=max_length)


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PurchaseImportError(f"{label} must be an explicit decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PurchaseImportError(f"{label} is not a valid decimal") from exc
    if not result.is_finite():
        raise PurchaseImportError(f"{label} must be finite")
    return result


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise PurchaseImportError(f"{label} must use the source ISO date format YYYY-MM-DD[THH:MM:SS]")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise PurchaseImportError(f"{label} is not a valid calendar date") from exc
    raise PurchaseImportError(f"{label} must use the source ISO date format YYYY-MM-DD[THH:MM:SS]")


def load_verified_cache(cache_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], bytes]:
    """Read the extraction cache only when its sidecar count and digest agree."""
    cache_path = cache_dir / "onec_purchases.jsonl"
    meta_path = cache_dir / "onec_purchases.meta.json"
    try:
        payload = cache_path.read_bytes()
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PurchaseImportError("monthly 1C purchase cache or metadata is unavailable") from exc
    if not isinstance(metadata, dict) or metadata.get("schema_version") != CACHE_SCHEMA:
        raise PurchaseImportError("monthly 1C purchase cache has an unsupported schema")
    if metadata.get("source_system") != "onec":
        raise PurchaseImportError("monthly cache source_system must be onec")
    if type(metadata.get("record_count")) is not int or metadata["record_count"] < 0:
        raise PurchaseImportError("monthly 1C purchase cache record_count must be a nonnegative integer")
    digest = hashlib.sha256(payload).hexdigest()
    if metadata.get("source_sha256") != digest:
        raise PurchaseImportError("monthly 1C purchase cache digest does not match its metadata")
    try:
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PurchaseImportError("monthly 1C purchase cache contains invalid JSONL") from exc
    if len(rows) != metadata.get("record_count"):
        raise PurchaseImportError("monthly 1C purchase cache record count does not match its metadata")
    if any(not isinstance(row, dict) for row in rows):
        raise PurchaseImportError("monthly 1C purchase cache rows must be JSON objects")
    for key in ("entity", "date_from", "date_to"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise PurchaseImportError(f"monthly 1C purchase cache metadata is missing {key}")
    if metadata["date_from"] >= metadata["date_to"]:
        raise PurchaseImportError("monthly 1C purchase cache has an invalid date window")
    return rows, metadata, payload


def build_receipt_drafts(
    rows: list[dict[str, Any]], metadata: dict[str, Any], profile: Any,
) -> list[dict[str, Any]]:
    """Map every cached source document to a schema-checked procurement draft.

    If any document is malformed or any reference is unmapped, no partial list
    is returned. Posting accounts and confirmation digest remain accountant work.
    """
    mapping = validate_mapping_profile(profile)
    if mapping["entity"] != metadata.get("entity"):
        raise PurchaseImportError("mapping entity does not match the cached 1C OData entity")
    start = _iso_date(metadata.get("date_from"), "cache date_from")
    end = _iso_date(metadata.get("date_to"), "cache date_to")
    if start >= end:
        raise PurchaseImportError("cache date window is invalid")

    drafts: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        ref = row.get("Ref_Key") if isinstance(row, dict) else None
        display_ref = ref if isinstance(ref, str) and ref.strip() else f"row-{index}"
        if not isinstance(row, dict):
            issues.append({"source_ref": display_ref, "field": "document", "reason": "row is not an object"})
            continue
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip():
            issues.append({"source_ref": display_ref, "field": "Ref_Key", "reason": "stable source key is missing"})
            continue
        if ref in seen:
            issues.append({"source_ref": ref, "field": "Ref_Key", "reason": "duplicate source key"})
            continue
        seen.add(ref)
        try:
            draft = _map_document(row, mapping, start, end)
        except PurchaseImportError as exc:
            issues.append({"source_ref": ref, "field": "document", "reason": str(exc)})
            continue
        except ValidationError as exc:  # value-free diagnostics; never echo document contents
            for error in exc.errors(include_input=False):
                field = ".".join(str(part) for part in error.get("loc", ())) or "document"
                issues.append({"source_ref": ref, "field": field, "reason": error["msg"]})
            continue
        drafts.append(draft)
    if issues:
        raise UnmappedPurchaseDocuments(issues)
    return drafts


def _map_document(
    row: dict[str, Any], mapping: dict[str, Any], start: date, end: date,
) -> dict[str, Any]:
    from modules.procurement.receipt_documents import ReceiptCreate

    doc_paths = mapping["paths"]["document"]
    line_paths = mapping["paths"]["line"]
    entity = mapping["entity"]
    ref = row["Ref_Key"]
    source_date_text = _pointer(row, doc_paths["document_date"], "document_date")
    document_date = _iso_date(source_date_text, "document_date")
    if not start <= document_date < end:
        raise PurchaseImportError("document Date is outside the cached month")

    number = _text(_pointer(row, doc_paths["number"], "number"), "invoice_reference")
    operation_date = _iso_date(
        _pointer(row, doc_paths["operation_date"], "operation_date"), "operation_date",
    )
    supplier_ref = _source_ref(_pointer(row, doc_paths["supplier_ref"], "supplier_ref"), "supplier_ref")
    contract_ref = _source_ref(_pointer(row, doc_paths["contract_ref"], "contract_ref"), "contract_ref")
    warehouse_ref = _source_ref(_pointer(row, doc_paths["warehouse_ref"], "warehouse_ref"), "warehouse_ref")
    currency_ref = _source_ref(_pointer(row, doc_paths["currency_ref"], "currency_ref"), "currency_ref")
    supplier = mapping["suppliers"].get(supplier_ref)
    contract = mapping["contracts"].get(contract_ref)
    warehouse = mapping["warehouses"].get(warehouse_ref)
    currency = mapping["currency_refs"].get(currency_ref)
    if supplier is None:
        raise PurchaseImportError("supplier_ref has no exact supplier catalogue mapping")
    if contract is None:
        raise PurchaseImportError("contract_ref has no exact contract catalogue mapping")
    if warehouse is None:
        raise PurchaseImportError("warehouse_ref has no exact organization warehouse mapping")
    if currency is None:
        raise PurchaseImportError("currency_ref has no explicit BYN mapping")

    source_lines = _pointer(row, doc_paths["lines"], "lines")
    if not isinstance(source_lines, list) or not source_lines:
        raise PurchaseImportError("lines must contain at least one source line")
    if len(source_lines) > 300:
        raise PurchaseImportError("source document exceeds the 300-line receipt limit")
    items: list[dict[str, Any]] = []
    for line_number, source_line in enumerate(source_lines, start=1):
        if not isinstance(source_line, dict):
            raise PurchaseImportError(f"line {line_number} is not an object")
        sku_ref = _source_ref(
            _pointer(source_line, line_paths["sku_ref"], f"line {line_number} sku_ref"),
            f"line {line_number} sku_ref",
        )
        sku = mapping["skus"].get(sku_ref)
        if sku is None:
            raise PurchaseImportError(f"line {line_number} sku_ref has no exact SKU catalogue mapping")
        quantity = _decimal(
            _pointer(source_line, line_paths["quantity"], f"line {line_number} quantity"),
            f"line {line_number} quantity",
        )
        net_amount = _decimal(
            _pointer(source_line, line_paths["net_amount"], f"line {line_number} net_amount"),
            f"line {line_number} net_amount",
        )
        vat_rate = _decimal(
            _pointer(source_line, line_paths["vat_rate"], f"line {line_number} vat_rate"),
            f"line {line_number} vat_rate",
        )
        vat_amount = _decimal(
            _pointer(source_line, line_paths["vat_amount"], f"line {line_number} vat_amount"),
            f"line {line_number} vat_amount",
        )
        if net_amount <= 0:
            raise PurchaseImportError(f"line {line_number} net_amount must be positive")
        if not Decimal(0) <= vat_rate <= Decimal(100):
            raise PurchaseImportError(f"line {line_number} vat_rate must be between 0 and 100")
        expected_vat = (net_amount * vat_rate / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        if vat_amount != expected_vat:
            raise PurchaseImportError(f"line {line_number} VAT amount does not match explicit rate and net amount")
        vat_basis = _text(
            _pointer(source_line, line_paths["vat_basis"], f"line {line_number} vat_basis"),
            f"line {line_number} vat_basis",
        )
        lot = f"onec:{ref}:{line_number}"
        if len(lot) > 200:
            raise PurchaseImportError(f"line {line_number} source Ref_Key is too long for the receipt lot")
        items.append({
            "sku_id": sku["id"], "sku_title": sku["title"], "sku": sku["code"],
            "unit": sku["unit"], "lot": lot, "quantity": str(quantity),
            "net_amount": str(net_amount), "vat_rate": str(vat_rate),
            "vat_amount": str(vat_amount), "vat_basis": vat_basis,
        })

    identity = f"{entity}\0{ref}".encode("utf-8")
    key = "onec:purchase:" + hashlib.sha256(identity).hexdigest()
    request = {
        "key": key,
        "document": {
            "currency": currency,
            "invoice_reference": number,
            "document_date": document_date.isoformat(),
            "operation_date": operation_date.isoformat(),
            "supplier": supplier["name"], "supplier_id": supplier["id"],
            "supplier_unp": supplier["unp"], "contract": contract["number"],
            "contract_id": contract["id"], "warehouse": warehouse["code"],
            "warehouse_id": warehouse["id"], "warehouse_title": warehouse["title"],
            "explanation": f"Импорт из 1С {entity}; Ref_Key={ref}",
            "items": items,
        },
    }
    validated = ReceiptCreate.model_validate(request)
    return {
        "organization_id": mapping["organization_id"],
        **validated.model_dump(mode="json", exclude_none=True),
    }


def prepare_month_plan(cache_dir: Path, mapping_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and verify both inputs, then build a deterministic draft plan."""
    try:
        mapping_bytes = mapping_path.read_bytes()
        raw_mapping = json.loads(mapping_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PurchaseImportError("explicit 1C purchase mapping file is unavailable or invalid JSON") from exc
    mapping = validate_mapping_profile(raw_mapping)
    rows, source_meta, source_bytes = load_verified_cache(cache_dir)
    drafts = build_receipt_drafts(rows, source_meta, mapping)
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    mapping_digest = hashlib.sha256(mapping_bytes).hexdigest()
    metadata = {
        "schema_version": PLAN_SCHEMA,
        "source_system": "onec",
        "source_entity": source_meta["entity"],
        "source_date_from": source_meta["date_from"],
        "source_date_to": source_meta["date_to"],
        "source_record_count": len(rows),
        "draft_count": len(drafts),
        "organization_id": mapping["organization_id"],
        "source_sha256": source_digest,
        "mapping_sha256": mapping_digest,
        "posting_previewed": False,
        "posted": False,
    }
    return drafts, metadata


def write_month_plan(cache_dir: Path, drafts: list[dict[str, Any]], metadata: dict[str, Any]) -> tuple[Path, Path]:
    """Write an immutable, digest-addressed draft package; exact replay is safe."""
    stem = (
        f"onec_purchase_drafts_{metadata['source_sha256'][:12]}_"
        f"{metadata['mapping_sha256'][:12]}"
    )
    data_path = cache_dir / f"{stem}.jsonl"
    meta_path = cache_dir / f"{stem}.meta.json"
    data_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in drafts
    ).encode("utf-8")
    metadata = {**metadata, "draft_sha256": hashlib.sha256(data_bytes).hexdigest()}
    meta_bytes = (json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_once(data_path, data_bytes)
    _write_once(meta_path, meta_bytes)
    return data_path, meta_path


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise PurchaseImportError(f"refusing to replace a different existing plan: {path.name}")
        return
    temp_path = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temp_path.open("xb") as stream:
            created = True
            stream.write(payload)
        temp_path.replace(path)
    except FileExistsError as exc:
        raise PurchaseImportError(f"another plan writer is active for {path.name}") from exc
    finally:
        if created and temp_path.exists():
            temp_path.unlink()


def write_unmapped_report(cache_dir: Path, issues: tuple[dict[str, str], ...]) -> Path:
    """Write a value-free report that names unresolved source rows and fields."""
    payload = "".join(
        json.dumps(issue, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for issue in issues
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:12]
    path = cache_dir / f"onec_purchase_unmapped_{digest}.jsonl"
    _write_once(path, payload)
    return path
