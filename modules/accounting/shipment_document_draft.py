"""Prefill a statutory shipment-document review from a verified WMS act.

The result is deliberately a read-only draft.  A warehouse act is evidence of
physical movement, but it is not a Belarusian TN/TTN and this module does not
invent sender, recipient, vehicle, prices, VAT treatment or signatures.
"""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Literal

from modules.accounting import service

DocumentKind = Literal["tn", "ttn"]

_COMMON_REQUIRED = (
    "sender_legal_entity",
    "recipient_legal_entity",
    "contract_reference",
    "document_number",
    "document_date",
    "operation_date",
    "items.unit_and_price",
    "items.vat_basis",
)
_TTN_REQUIRED = (
    "carrier",
    "vehicle_registration",
    "driver",
    "route",
    "loading_point",
    "unloading_point",
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _quantity(lines: list[dict]) -> str:
    total = Decimal("0")
    try:
        for line in lines:
            total += Decimal(str(line["qty"]))
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise service.AccountingError("Physical shipment quantity is invalid") from exc
    return format(total, ".6f").rstrip("0").rstrip(".") or "0"


def build(receipt: dict, kind: DocumentKind | None = None) -> dict:
    """Return a stable, source-bound TN/TTN preparation package."""
    if not isinstance(receipt, dict) or not isinstance(receipt.get("snapshot"), dict):
        raise service.AccountingError("Verified physical shipment source is required")
    snapshot = receipt["snapshot"]
    lines = snapshot.get("lines")
    if not isinstance(lines, list) or not lines:
        raise service.AccountingError("Physical shipment has no verified lines")
    selected = kind if kind in {"tn", "ttn"} else None
    label = {"tn": "ТН", "ttn": "ТТН"}.get(selected) if selected else None
    required = list(_COMMON_REQUIRED) + (list(_TTN_REQUIRED) if selected == "ttn" else [])
    prefilled = {
        "source_key": receipt.get("source_key"),
        "source_digest": receipt.get("digest"),
        "act_id": receipt.get("act_id"),
        "organization_id": snapshot.get("organization_id"),
        "sales_document_id": snapshot.get("document_id"),
        "sales_document_version": snapshot.get("document_version"),
        "operation_date": snapshot.get("operation_date"),
        "items": [
            {
                "line_no": row.get("line_no"),
                "sku_code": row.get("sku_code"),
                "warehouse": row.get("warehouse"),
                "quantity": row.get("qty"),
                "source": row.get("source"),
            }
            for row in lines
        ],
        "total_quantity": _quantity(lines),
    }
    package = {
        "status": "draft_required",
        "document_kind": selected,
        "document_label": label,
        "options": [
            {"kind": "tn", "label": "ТН"},
            {"kind": "ttn", "label": "ТТН"},
        ],
        "source": {
            "kind": "verified_internal_physical_shipment",
            "source_key": receipt.get("source_key"),
            "digest": receipt.get("digest"),
            "act_id": receipt.get("act_id"),
        },
        "prefilled": prefilled,
        "required_fields": required,
        "blockers": [
            "Внутренний акт WMS не является ТН или ТТН.",
            "Черновик не содержит подписи, ЭЦП или подтверждения внешнего оператора.",
            "Заполните обязательные реквизиты и подтвердите форму бухгалтером.",
        ],
        "can_issue": False,
        "statutory_certified": False,
    }
    package["draft_digest"] = _digest(package)
    return package
