"""Explicit employer evidence for global HR employees; never infer an organization."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func, select

from modules.accounting.models import PayrollEmploymentBinding
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, lock_organization
from modules.hr.models import Employee


class PayrollEmploymentInput(Input):
    request_key: UUID
    employee_id: int = Field(gt=0, strict=True)
    contract_ref: str = Field(min_length=1, max_length=160)
    effective_from: date
    state: Literal["active", "ended"]
    source_document: str = Field(min_length=1, max_length=160)
    evidence: str = Field(min_length=10, max_length=2000)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def result(row: PayrollEmploymentBinding) -> dict:
    if _digest(row.snapshot) != row.digest:
        raise HTTPException(409, "Payroll employment binding integrity requires reconciliation")
    return {
        "binding_id": row.id,
        "organization_id": row.organization_id,
        "employee_id": row.employee_id,
        "contract_ref": row.contract_ref,
        "effective_from": row.effective_from.isoformat(),
        "revision": row.revision,
        "state": row.state,
        "source_document": row.source_document,
        "evidence": row.evidence,
        "employee_name": row.snapshot["employee_name"],
        "department": row.snapshot["department"],
        "position": row.snapshot["position"],
        "request_key": row.request_key,
        "digest": row.digest,
        "actor": row.actor,
        "contract_verified": False,
    }


async def current(session, org_id: int, employee_id: int, contract_ref: str,
                  on: date) -> PayrollEmploymentBinding | None:
    return await session.scalar(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.employee_id == employee_id,
        PayrollEmploymentBinding.contract_ref == contract_ref,
        PayrollEmploymentBinding.effective_from <= on,
    ).order_by(
        PayrollEmploymentBinding.effective_from.desc(),
        PayrollEmploymentBinding.revision.desc(),
    ).limit(1))


async def create(session, org_id: int, data: PayrollEmploymentInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    request_digest = _digest(command)
    existing = await session.scalar(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Payroll employment request key was reused with different content")
        return result(existing)

    employee = await session.get(Employee, data.employee_id)
    if employee is None:
        raise AccountingError("HR employee does not exist; no employer is inferred")
    previous = await current(session, org_id, data.employee_id, data.contract_ref, data.effective_from)
    if data.state == "ended" and (previous is None or previous.state != "active"):
        raise AccountingError("Ending employment requires a prior active binding")
    revision = (await session.scalar(select(func.max(PayrollEmploymentBinding.revision)).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.employee_id == data.employee_id,
        PayrollEmploymentBinding.contract_ref == data.contract_ref,
        PayrollEmploymentBinding.effective_from == data.effective_from,
    ))) or 0
    snapshot = {
        "organization_id": org_id,
        **command,
        "employee_name": employee.full_name,
        "department": employee.department,
        "position": employee.position,
    }
    row = PayrollEmploymentBinding(
        organization_id=org_id,
        employee_id=data.employee_id,
        contract_ref=data.contract_ref,
        effective_from=data.effective_from,
        revision=revision + 1,
        state=data.state,
        source_document=data.source_document,
        evidence=data.evidence,
        request_key=str(data.request_key),
        request_digest=request_digest,
        digest=_digest(snapshot),
        snapshot=snapshot,
        actor=actor,
    )
    session.add(row)
    await session.flush()
    return result(row)


async def effective(session, org_id: int, on: date) -> list[dict]:
    rows = (await session.scalars(select(PayrollEmploymentBinding).where(
        PayrollEmploymentBinding.organization_id == org_id,
        PayrollEmploymentBinding.effective_from <= on,
    ).order_by(
        PayrollEmploymentBinding.employee_id,
        PayrollEmploymentBinding.contract_ref,
        PayrollEmploymentBinding.effective_from.desc(),
        PayrollEmploymentBinding.revision.desc(),
    ))).all()
    seen = set()
    output = []
    for row in rows:
        key = (row.employee_id, row.contract_ref)
        if key not in seen:
            seen.add(key)
            output.append(result(row))
    return output
