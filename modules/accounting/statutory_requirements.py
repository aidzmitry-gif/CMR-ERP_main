"""Append-only external statutory form/rate requirements by legal entity."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select

from modules.accounting.models import StatutoryRequirement
from modules.accounting.service import lock_organization


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _snapshot(org_id: int, data) -> dict:
    return {"organization_id": org_id, **data.model_dump(mode="json")}


def _decimal_text(value) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def result(row: StatutoryRequirement) -> dict:
    snapshot = dict(row.snapshot)
    if _digest(snapshot) != row.digest:
        raise HTTPException(409, "Statutory requirement integrity requires reconciliation")
    return {
        "requirement_id": row.id,
        "organization_id": row.organization_id,
        "kind": row.kind,
        "code": row.code,
        "title": row.title,
        "effective_from": row.effective_from.isoformat(),
        "revision": row.revision,
        "source_reference": row.source_reference,
        "evidence": row.evidence,
        "form_version": row.form_version,
        "electronic_format_version": row.electronic_format_version,
        "rate_value": _decimal_text(row.rate_value) if row.rate_value is not None else None,
        "rate_unit": row.rate_unit,
        "rate_basis": row.rate_basis,
        "request_key": row.request_key,
        "digest": row.digest,
        "actor": row.actor,
    }


async def create(session, org_id: int, data, actor: str):
    await lock_organization(session, org_id)
    request_digest = _digest(data.model_dump(mode="json"))
    existing = await session.scalar(select(StatutoryRequirement).where(
        StatutoryRequirement.organization_id == org_id,
        StatutoryRequirement.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Statutory requirement request was reused with different content")
        return result(existing)

    revision = (await session.scalar(select(func.max(StatutoryRequirement.revision)).where(
        StatutoryRequirement.organization_id == org_id,
        StatutoryRequirement.kind == data.kind,
        StatutoryRequirement.code == data.code,
        StatutoryRequirement.effective_from == data.effective_from,
    ))) or 0
    snapshot = _snapshot(org_id, data)
    row = StatutoryRequirement(
        organization_id=org_id,
        revision=revision + 1,
        request_key=str(data.request_key),
        request_digest=request_digest,
        digest=_digest(snapshot),
        snapshot=snapshot,
        actor=actor,
        **data.model_dump(mode="python", exclude={"request_key"}),
    )
    session.add(row)
    await session.flush()
    return result(row)


async def effective_for(session, org_id: int, on):
    rows = (await session.scalars(select(StatutoryRequirement).where(
        StatutoryRequirement.organization_id == org_id,
        StatutoryRequirement.effective_from <= on,
    ).order_by(
        StatutoryRequirement.kind,
        StatutoryRequirement.code,
        StatutoryRequirement.effective_from.desc(),
        StatutoryRequirement.revision.desc(),
    ))).all()
    current = {}
    for row in rows:
        current.setdefault((row.kind, row.code), row)
    return [result(row) for row in current.values()]
