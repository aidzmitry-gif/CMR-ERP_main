"""Immutable, source-bound preparation versions for TN and TTN drafts."""

import hashlib
import json
from datetime import timezone
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select

from core.domain.models import Counterparty
from modules.accounting.models import Organization, ShipmentPreparationDraft
from modules.accounting.schemas import Input

_COMMON_FIELDS = (
    "contract_reference",
    "document_number",
    "document_date",
)
_TTN_FIELDS = ("carrier", "vehicle_registration", "driver", "route", "loading_point", "unloading_point")
_ITEM_FIELDS = ("unit", "unit_price", "vat_basis")
_RECIPIENT_FIELDS = ("recipient_counterparty_id", "recipient_counterparty_revision")
_MAX_PAYLOAD_BYTES = 2_000_000


class ShipmentDocumentDraftInput(Input):
    kind: Literal["tn", "ttn"]
    request_key: UUID
    expected_revision: int = Field(ge=0, strict=True)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: dict

    @field_validator("fields")
    @classmethod
    def bounded_fields(cls, value):
        allowed = set(_COMMON_FIELDS) | set(_TTN_FIELDS) | set(_RECIPIENT_FIELDS) | {"items"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("Draft contains unsupported TN/TTN fields")
        for key, item in value.items():
            if key == "items":
                if not isinstance(item, list) or len(item) > 10000:
                    raise ValueError("Invalid shipment item draft")
                seen = set()
                for row in item:
                    if not isinstance(row, dict) or set(row) - ({"line_no"} | set(_ITEM_FIELDS)):
                        raise ValueError("Invalid shipment item draft")
                    line_no = row.get("line_no")
                    if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no <= 0 or line_no in seen:
                        raise ValueError("Shipment draft line references must be unique positive integers")
                    seen.add(line_no)
                    for field in _ITEM_FIELDS:
                        _bounded_text(row.get(field, ""), field, 500)
            elif key in _RECIPIENT_FIELDS:
                if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                    raise ValueError(f"{key} must be a positive integer")
            else:
                _bounded_text(item, key, 1000)
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Draft fields must contain plain text only") from exc
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            raise ValueError("Draft exceeds 2 MB")
        return value

    @model_validator(mode="after")
    def kind_fields_match(self):
        if self.kind == "tn" and any(key in self.fields for key in _TTN_FIELDS):
            raise ValueError("TTN-only fields cannot be stored on a TN draft")
        return self


def _bounded_text(value, name: str, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length or "\x00" in value:
        raise ValueError(f"{name} must be plain text no longer than {max_length} characters")
    return value


def source_name(organization_id: int, source_key: str, kind: str) -> str:
    try:
        key = str(UUID(str(source_key)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(409, "TN/TTN draft source is not a verified shipment for this organization") from exc
    source = f"wms:physical-shipment:{organization_id}:{key}:tn-ttn:{kind}"
    if kind not in {"tn", "ttn"} or len(source) > 160:
        raise HTTPException(409, "TN/TTN draft source is not a verified shipment for this organization")
    return source


def _normalize_request_fields(raw: dict, kind: str, package: dict) -> dict:
    allowed = set(_COMMON_FIELDS) | set(_RECIPIENT_FIELDS) | ({"items"} if kind == "tn" else set(_TTN_FIELDS) | {"items"})
    if set(raw) - allowed:
        raise HTTPException(422, "Draft contains fields that do not belong to this document kind")
    fields = {key: raw.get(key, "") for key in _COMMON_FIELDS}
    if kind == "ttn":
        fields.update({key: raw.get(key, "") for key in _TTN_FIELDS})
    for key, value in fields.items():
        try:
            fields[key] = _bounded_text(value, key, 1000).strip()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    for key in _RECIPIENT_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise HTTPException(409, "Select the recipient from the active counterparty directory")
        fields[key] = value

    source_lines = package.get("prefilled", {}).get("items")
    if not isinstance(source_lines, list) or not source_lines:
        raise HTTPException(409, "Verified shipment lines are required")
    requested = raw.get("items", [])
    if not isinstance(requested, list):
        raise HTTPException(422, "Invalid shipment item draft")
    by_line = {}
    for row in requested:
        if not isinstance(row, dict) or set(row) - ({"line_no"} | set(_ITEM_FIELDS)):
            raise HTTPException(422, "Invalid shipment item draft")
        line_no = row.get("line_no")
        if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no in by_line:
            raise HTTPException(422, "Shipment draft line references must be unique integers")
        by_line[line_no] = row
    fields["items"] = []
    source_numbers = set()
    for source_line in source_lines:
        line_no = source_line.get("line_no")
        if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no <= 0 or line_no in source_numbers:
            raise HTTPException(409, "Verified shipment line identities are invalid")
        source_numbers.add(line_no)
        item = by_line.pop(line_no, {})
        normalized = {"line_no": line_no}
        for key in _ITEM_FIELDS:
            try:
                normalized[key] = _bounded_text(item.get(key, ""), key, 500).strip()
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        fields["items"].append(normalized)
    if by_line:
        raise HTTPException(409, "Draft contains an item that is not in the verified shipment")
    return fields


async def _directory_snapshots(session, organization_id: int, recipient_id: int,
                               recipient_revision: int) -> tuple[dict, dict]:
    organization = await session.scalar(select(Organization).where(
        Organization.id == organization_id,
    ).with_for_update())
    if organization is None:
        raise HTTPException(404, "Accounting organization was not found")
    counterparty = await session.scalar(select(Counterparty).where(
        Counterparty.id == recipient_id,
    ).with_for_update())
    if counterparty is None or not counterparty.is_active or counterparty.merged_into_id is not None:
        raise HTTPException(409, "Select an active recipient from the counterparty directory")
    if counterparty.revision != recipient_revision:
        raise HTTPException(409, "Recipient directory entry changed; select it again before saving")
    sender = {
        "reference": "accounting.organization",
        "id": organization.id,
        "name": organization.name,
        "unp": organization.unp,
    }
    recipient = {
        "reference": "core.counterparties",
        "id": counterparty.id,
        "name": counterparty.legal_name or counterparty.name,
        "unp": counterparty.unp or "",
        "revision": counterparty.revision,
    }
    return sender, recipient


def _materialize_fields(request_fields: dict, sender: dict, recipient: dict) -> dict:
    fields = {key: value for key, value in request_fields.items() if key not in _RECIPIENT_FIELDS}
    fields["sender_identity"] = sender
    fields["sender_legal_entity"] = sender["name"]
    fields["recipient_identity"] = recipient
    fields["recipient_legal_entity"] = recipient["name"]
    return fields


def _blank_fields(package: dict, kind: str, sender: dict) -> dict:
    fields = {key: "" for key in _COMMON_FIELDS}
    if kind == "ttn":
        fields.update({key: "" for key in _TTN_FIELDS})
    fields.update({
        "sender_identity": sender,
        "sender_legal_entity": sender["name"],
        "recipient_identity": None,
        "recipient_legal_entity": "",
    })
    fields["items"] = [
        {"line_no": line["line_no"], **{key: "" for key in _ITEM_FIELDS}}
        for line in package.get("prefilled", {}).get("items", [])
    ]
    return fields


def _flatten(value, prefix="") -> dict[str, object]:
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("line_no"), int):
                line = item["line_no"]
                result.update(_flatten({key: child for key, child in item.items() if key != "line_no"}, f"{prefix}.line_{line}"))
            else:
                result.update(_flatten(item, f"{prefix}.{len(result)}"))
    else:
        result[prefix] = value
    return result


def _timestamp(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _history(rows) -> list[dict]:
    output = []
    previous = {}
    for row in rows:
        fields = row.payload.get("fields", {})
        flat = _flatten(fields)
        before = _flatten(previous)
        changes = [
            {"field": key, "before": before.get(key), "after": flat.get(key)}
            for key in sorted(before.keys() | flat.keys())
            if before.get(key) != flat.get(key)
            and (bool(before.get(key)) or bool(flat.get(key)))
        ]
        output.append({
            "id": row.id,
            "revision": row.revision,
            "actor": row.actor,
            "created_at": _timestamp(row.created_at),
            "fields": fields,
            "changes": changes,
        })
        previous = fields
    return output


async def attach_history(session, organization_id: int, source_key: str, kind: str, package: dict) -> dict:
    source = source_name(organization_id, source_key, kind)
    organization = await session.scalar(select(Organization).where(Organization.id == organization_id))
    if organization is None:
        raise HTTPException(404, "Accounting organization was not found")
    sender = {
        "reference": "accounting.organization",
        "id": organization.id,
        "name": organization.name,
        "unp": organization.unp,
    }
    rows = (await session.scalars(select(ShipmentPreparationDraft).where(
        ShipmentPreparationDraft.organization_id == organization_id,
        ShipmentPreparationDraft.source == source,
    ).order_by(ShipmentPreparationDraft.revision))).all()
    if any(
        not isinstance(row.payload, dict)
        or row.payload.get("kind") != kind
        or not isinstance(row.payload.get("fields"), dict)
        or not isinstance(row.payload.get("basis"), dict)
        for row in rows
    ):
        raise HTTPException(409, "Saved TN/TTN draft history is inconsistent; manual review is required")
    history = _history(rows)
    package.update({
        "saved_revision": rows[-1].revision if rows else 0,
        "saved_fields": rows[-1].payload["fields"] if rows else _blank_fields(package, kind, sender),
        "saved_by": rows[-1].actor if rows else None,
        "saved_at": _timestamp(rows[-1].created_at) if rows else None,
        "history": history,
    })
    latest_fields = rows[-1].payload["fields"] if rows else package["saved_fields"]
    package["directory_identity_status"] = (
        "verified" if isinstance(latest_fields.get("sender_identity"), dict)
        and isinstance(latest_fields.get("recipient_identity"), dict)
        else "legacy_unbound" if rows else "recipient_required"
    )
    if any(row.payload.get("source_digest") != package["source"]["digest"] for row in rows):
        package["source_history_current"] = False
        package["blockers"].append("Сохранённая редакция связана с другой версией акта; продолжение сохранения заблокировано.")
    else:
        package["source_history_current"] = True
    return package


async def save(session, organization_id: int, source_key: str, package: dict,
               data: ShipmentDocumentDraftInput, actor: str) -> ShipmentPreparationDraft:
    """Append one draft version; caller holds the organization lock and transaction."""
    source = source_name(organization_id, source_key, data.kind)
    current_digest = package.get("source", {}).get("digest")
    if data.source_digest != current_digest:
        raise HTTPException(409, "Verified shipment changed; reload the draft before saving")
    request_fields = _normalize_request_fields(data.fields, data.kind, package)
    command = {
        "source": source,
        "kind": data.kind,
        "request_key": str(data.request_key),
        "expected_revision": data.expected_revision,
        "source_digest": current_digest,
        "fields": request_fields,
    }
    digest = hashlib.sha256(json.dumps(command, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    replay = await session.scalar(select(ShipmentPreparationDraft).where(
        ShipmentPreparationDraft.organization_id == organization_id,
        ShipmentPreparationDraft.request_key == str(data.request_key),
    ))
    if replay is not None:
        if replay.source != source or replay.command_digest != digest or replay.actor != actor:
            raise HTTPException(409, "Draft request key already belongs to another command")
        return replay

    head = await session.scalar(select(ShipmentPreparationDraft).where(
        ShipmentPreparationDraft.organization_id == organization_id,
        ShipmentPreparationDraft.source == source,
    ).order_by(ShipmentPreparationDraft.revision.desc()).limit(1))
    revision = head.revision if head else 0
    if revision != data.expected_revision:
        raise HTTPException(409, "TN/TTN draft changed; reload history before saving another version")
    sender, recipient = await _directory_snapshots(
        session, organization_id,
        request_fields["recipient_counterparty_id"],
        request_fields["recipient_counterparty_revision"],
    )
    fields = _materialize_fields(request_fields, sender, recipient)
    payload = {
        "kind": data.kind,
        "source_digest": current_digest,
        "fields": fields,
        "request_fields": request_fields,
        "basis": package,
    }
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(422, "Draft exceeds 2 MB")
    row = ShipmentPreparationDraft(
        organization_id=organization_id,
        source=source,
        revision=revision + 1,
        request_key=str(data.request_key),
        command_digest=digest,
        payload=payload,
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return row
