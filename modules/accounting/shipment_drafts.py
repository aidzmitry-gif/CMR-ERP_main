"""Optimistic, idempotent storage of incomplete accountant preparation inputs."""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select

from modules.accounting.models import ShipmentPreparationDraft, SourceControl
from modules.accounting.schemas import Input


class DraftInput(Input):
    request_key: UUID
    expected_revision: int = Field(ge=0, strict=True)
    payload: dict

    @field_validator("payload")
    @classmethod
    def bounded_input(cls, value):
        if set(value) != {"act_digest", "posting_date", "policy_id", "form", "allocations", "terms"}:
            raise ValueError("A draft contains preparation inputs only")
        if not isinstance(value["act_digest"], str) or len(value["act_digest"]) != 64:
            raise ValueError("Draft needs its original act digest")
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 2_000_000:
            raise ValueError("Draft exceeds 2 MB")
        if not isinstance(value["form"], dict) or not isinstance(value["allocations"], list) or not isinstance(value["terms"], list):
            raise ValueError("Invalid preparation input shape")
        if len(value["allocations"]) > 10000 or len(value["terms"]) > 1000:
            raise ValueError("Too many draft rows")
        return value


async def latest(session, org_id, source):
    return await session.scalar(select(ShipmentPreparationDraft).where(
        ShipmentPreparationDraft.organization_id == org_id,
        ShipmentPreparationDraft.source == source,
    ).order_by(ShipmentPreparationDraft.revision.desc()).limit(1))


async def save(session, org_id, source, data, actor):
    # Caller holds the same organization lock as posting and source resolution.
    command = {"source": source, **data.model_dump(mode="json")}
    digest = hashlib.sha256(json.dumps(command, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    old = await session.scalar(select(ShipmentPreparationDraft).where(
        ShipmentPreparationDraft.organization_id == org_id,
        ShipmentPreparationDraft.request_key == str(data.request_key),
    ))
    if old:
        if old.command_digest != digest or old.actor != actor:
            raise HTTPException(409, "Draft request key already belongs to another command")
        return old
    control = await session.scalar(select(SourceControl).where(
        SourceControl.organization_id == org_id, SourceControl.source == source,
    ))
    if control is None or control.entry_id is not None or control.version != 1:
        raise HTTPException(409, "A pending physical shipment is required")
    head = await latest(session, org_id, source)
    revision = head.revision if head else 0
    if revision != data.expected_revision:
        raise HTTPException(409, "Draft changed; reload before saving another version")
    row = ShipmentPreparationDraft(organization_id=org_id, source=source,
        revision=revision + 1, request_key=str(data.request_key), command_digest=digest,
        payload=data.payload, actor=actor)
    session.add(row)
    await session.flush()
    return row
