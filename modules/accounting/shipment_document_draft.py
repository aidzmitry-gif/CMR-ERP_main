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
_SCENARIO_TEXT_FIELDS = (
    "form_version",
    "numbering_rule",
    "signing_rule",
    "exchange_rule",
    "evidence",
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


def _shipment_policy(policy: object | None, kind: DocumentKind | None, operation_date: object) -> dict:
    """Expose only an explicit, date-selected policy scenario for review.

    A configured scenario is intentionally *not* a statutory issue approval:
    electronic signing and external exchange remain outside this local module.
    """
    result = {
        "status": "missing_accounting_policy",
        "policy_id": None,
        "effective_from": None,
        "normative_verified": None,
        "operation_date": str(operation_date),
        "scenario": None,
    }
    if policy is None:
        return result

    result.update({
        "policy_id": getattr(policy, "id", None),
        "effective_from": str(getattr(policy, "effective_from", "")) or None,
        "normative_verified": bool(getattr(policy, "normative_verified", False)),
    })
    if kind is None:
        result["status"] = "document_kind_not_selected"
        return result
    configured = getattr(policy, "shipment_documents", None)
    if not isinstance(configured, dict):
        result["status"] = "missing_shipment_document_policy"
        return result
    scenarios = configured.get("scenarios")
    if not isinstance(scenarios, list):
        result["status"] = "invalid_shipment_document_policy"
        return result
    scenario = next((item for item in scenarios if isinstance(item, dict) and item.get("kind") == kind), None)
    if scenario is None:
        result["status"] = "document_kind_not_configured"
        return result
    if (scenario.get("exchange_mode") not in {"paper", "electronic"}
            or any(not isinstance(scenario.get(field), str) or not scenario[field].strip()
                   or "\x00" in scenario[field] for field in _SCENARIO_TEXT_FIELDS)):
        result["status"] = "invalid_shipment_document_policy"
        return result
    result["scenario"] = {field: scenario[field] for field in ("kind", "exchange_mode", *_SCENARIO_TEXT_FIELDS)}
    result["status"] = "review_ready" if result["normative_verified"] else "normative_basis_unverified"
    return result


def _policy_blocker(status: str) -> str | None:
    messages = {
        "missing_accounting_policy": "На дату операции нет применимой версии учётной политики.",
        "document_kind_not_selected": "Выберите вид ТН или ТТН; вид документа не определяется по акту WMS.",
        "missing_shipment_document_policy": "В версии учётной политики нет настроенного сценария ТН/ТТН.",
        "document_kind_not_configured": "Для выбранного вида документа в учётной политике нет отдельного сценария.",
        "invalid_shipment_document_policy": "Настройка ТН/ТТН в учётной политике неполная или повреждена.",
        "normative_basis_unverified": "Нормативная база выбранной версии учётной политики не подтверждена бухгалтером.",
    }
    return messages.get(status)


def build(receipt: dict, kind: DocumentKind | None = None, policy: object | None = None) -> dict:
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
    shipment_policy = _shipment_policy(policy, selected, snapshot.get("operation_date"))
    blockers = [
        "Внутренний акт WMS не является ТН или ТТН.",
        "Черновик не содержит подписи, ЭЦП или подтверждения внешнего оператора.",
        "Заполните обязательные реквизиты и подтвердите форму бухгалтером.",
        "Выпуск ТН/ТТН из этого черновика недоступен до отдельного подключённого контура.",
    ]
    policy_blocker = _policy_blocker(shipment_policy["status"])
    if policy_blocker is not None:
        blockers.insert(1, policy_blocker)
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
        "shipment_document_policy": shipment_policy,
        "prefilled": prefilled,
        "required_fields": required,
        "blockers": blockers,
        "can_issue": False,
        "statutory_certified": False,
    }
    package["draft_digest"] = _digest(package)
    return package
