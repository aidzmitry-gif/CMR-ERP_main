"""Versioned employer payroll arithmetic rules, configured without defaults."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import func, select

from modules.accounting.models import PayrollRuleSet, StatutoryRequirement
from modules.accounting.payroll_calculation import (
    effective_percentage_rate,
    month_bounds,
    verified_policy,
)
from modules.accounting.schemas import Input
from modules.accounting.service import AccountingError, lock_organization


class PayrollRateRuleInput(Input):
    code: str = Field(min_length=1, max_length=120)
    role: Literal["employee_deduction", "employer_contribution"]
    base_mode: Literal["gross", "gross_less_adjustment"]
    classification_evidence: str = Field(min_length=10, max_length=2000)


class PayrollRuleSetInput(Input):
    request_key: UUID
    policy_id: int = Field(gt=0, strict=True)
    effective_from: date
    gross_method: Literal["monthly_salary_by_hours"]
    rounding: Literal["half_up_cent"]
    rate_rules: list[PayrollRateRuleInput] = Field(min_length=1, max_length=20)
    source_reference: str = Field(min_length=1, max_length=200)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def check_revision(self):
        if self.effective_from.day != 1:
            raise ValueError("Payroll rule set must take effect on the first day of a month")
        codes = [rule.code for rule in self.rate_rules]
        if len(codes) != len(set(codes)):
            raise ValueError("Payroll rule set rate codes must be unique")
        return self


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


def result(row: PayrollRuleSet) -> dict:
    if _digest(row.snapshot) != row.digest:
        raise HTTPException(409, "Payroll rule set integrity requires reconciliation")
    return {
        "rule_set_id": row.id,
        "organization_id": row.organization_id,
        "policy_id": row.policy_id,
        "effective_from": row.effective_from.isoformat(),
        "revision": row.revision,
        "gross_method": row.gross_method,
        "rounding": row.rounding,
        "rate_rules": row.rate_rules,
        "source_reference": row.source_reference,
        "source_digest": row.source_digest,
        "evidence": row.evidence,
        "request_key": row.request_key,
        "digest": row.digest,
        "actor": row.actor,
        "source_document_verified": False,
        "statutory_completeness_verified": False,
    }


async def current(session, org_id: int, on: date) -> PayrollRuleSet | None:
    return await session.scalar(select(PayrollRuleSet).where(
        PayrollRuleSet.organization_id == org_id,
        PayrollRuleSet.effective_from <= on,
    ).order_by(PayrollRuleSet.effective_from.desc(), PayrollRuleSet.revision.desc()).limit(1))


async def create(session, org_id: int, data: PayrollRuleSetInput, actor: str) -> dict:
    await lock_organization(session, org_id)
    command = data.model_dump(mode="json")
    request_digest = _digest(command)
    existing = await session.scalar(select(PayrollRuleSet).where(
        PayrollRuleSet.organization_id == org_id,
        PayrollRuleSet.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise HTTPException(409, "Payroll rule set request key was reused with different content")
        return result(existing)

    first, last = month_bounds(data.effective_from.strftime("%Y-%m"))
    await verified_policy(session, org_id, first, last, data.policy_id)
    rate_versions = []
    for rule in data.rate_rules:
        rate_id = await session.scalar(select(StatutoryRequirement.id).where(
            StatutoryRequirement.organization_id == org_id,
            StatutoryRequirement.kind == "rate",
            StatutoryRequirement.code == rule.code,
            StatutoryRequirement.effective_from <= data.effective_from,
        ).order_by(
            StatutoryRequirement.effective_from.desc(),
            StatutoryRequirement.revision.desc(),
        ).limit(1))
        if rate_id is None:
            raise AccountingError(f"No effective organization rate for payroll rule {rule.code}")
        _, verified = await effective_percentage_rate(session, org_id, rate_id, data.effective_from)
        rate_versions.append({"code": rule.code, "requirement_id": rate_id,
                              "requirement_digest": verified["digest"]})

    revision = (await session.scalar(select(func.max(PayrollRuleSet.revision)).where(
        PayrollRuleSet.organization_id == org_id,
        PayrollRuleSet.effective_from == data.effective_from,
    ))) or 0
    snapshot = {"organization_id": org_id, **command, "rates_at_configuration": rate_versions}
    row = PayrollRuleSet(
        organization_id=org_id,
        policy_id=data.policy_id,
        effective_from=data.effective_from,
        revision=revision + 1,
        gross_method=data.gross_method,
        rounding=data.rounding,
        rate_rules=[rule.model_dump(mode="json") for rule in data.rate_rules],
        source_reference=data.source_reference,
        source_digest=data.source_digest,
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
