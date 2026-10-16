"""Explicit fixed-asset register and reviewed straight-line depreciation.

The register is bound to an already posted acquisition line.  It does not infer
an asset from a generic purchase.  Depreciation is available only when the
organization policy, useful life, residual value and accounts are explicit; the
current implementation intentionally supports straight-line calculation only.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.models import (
    Entry,
    FixedAssetDepreciationReceipt,
    FixedAssetRegisterEntry,
    Line,
    Period,
    Policy,
)
from modules.accounting.schemas import Code, Input, Money, PostingInput

CENT = Decimal("0.01")


class FixedAssetRegisterInput(Input):
    request_key: UUID
    asset_key: str = Field(min_length=1, max_length=160)
    source_entry_id: int = Field(gt=0, strict=True)
    source_line_id: int = Field(gt=0, strict=True)
    expected_source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=200)
    inventory_number: str = Field(min_length=1, max_length=100)
    acquisition_date: date
    commissioning_date: date
    depreciation_start: date
    cost: Money = Field(gt=0)
    residual_value: Money = Field(ge=0)
    useful_life_months: int = Field(gt=0, le=1200, strict=True)
    depreciation_method: Literal["straight_line", "declining_balance", "production_units"]
    asset_account: Code
    accumulated_account: Code
    expense_account: Code
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_dates_and_cost(self):
        if self.commissioning_date < self.acquisition_date:
            raise ValueError("Commissioning cannot precede acquisition")
        if self.depreciation_start < self.commissioning_date:
            raise ValueError("Depreciation cannot start before commissioning")
        if self.residual_value > self.cost:
            raise ValueError("Residual value cannot exceed cost")
        if self.asset_account == self.accumulated_account or self.asset_account == self.expense_account:
            raise ValueError("Fixed-asset accounts must be distinct")
        if self.accumulated_account == self.expense_account:
            raise ValueError("Accumulated and expense accounts must be distinct")
        return self


class FixedAssetRegisterConfirmInput(FixedAssetRegisterInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class FixedAssetDepreciationInput(Input):
    request_key: UUID
    asset_id: int = Field(gt=0, strict=True)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    expected_asset_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_id: int = Field(gt=0, strict=True)
    posting_date: date
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def validate_identity(self):
        if self.posting_date.strftime("%Y-%m") != self.month:
            raise ValueError("Depreciation posting date must belong to the selected month")
        return self


class FixedAssetDepreciationConfirmInput(FixedAssetDepreciationInput):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise service.AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise service.AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _account_error(account, code: str, *, categories: set[str]) -> str | None:
    if account is None:
        return f"Account {code} is not effective for this organization"
    if account.cash or account.currency_tracking or account.quantity_tracking:
        return f"Fixed-asset account {code} must be noncash BYN without quantity tracking"
    if account.category not in categories:
        return f"Account {code} has an invalid category for this fixed-asset role"
    return None


async def _validate_accounts(session, org_id: int, on: date, data: FixedAssetRegisterInput):
    accounts = await service.accounts_on(session, org_id, on)
    asset = accounts.get(data.asset_account)
    accumulated = accounts.get(data.accumulated_account)
    expense = accounts.get(data.expense_account)
    if not data.asset_account == "01" and not data.asset_account.startswith("01."):
        raise service.AccountingError("Fixed-asset account must belong to account 01")
    if not data.accumulated_account == "02" and not data.accumulated_account.startswith("02."):
        raise service.AccountingError("Accumulated depreciation account must belong to account 02")
    for account, code, categories in (
        (asset, data.asset_account, {"asset"}),
        (accumulated, data.accumulated_account, {"asset", "liability"}),
        (expense, data.expense_account, {"asset", "expense"}),
    ):
        error = _account_error(account, code, categories=categories)
        if error:
            raise service.AccountingError(error)
    return accounts


async def _source(session, org_id: int, data: FixedAssetRegisterInput):
    entry = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.id == data.source_entry_id,
    ))
    line = await session.scalar(select(Line).where(
        Line.id == data.source_line_id, Line.entry_id == data.source_entry_id,
    ))
    if entry is None or line is None:
        raise service.AccountingError("Fixed-asset acquisition source was not found in this organization")
    if entry.digest != data.expected_source_digest:
        raise service.AccountingError("The fixed-asset acquisition posting changed; read it again")
    if line.account_code != data.asset_account or line.side != "debit" or line.amount != data.cost:
        raise service.AccountingError("The source line must be a positive debit of the configured account 01 for the exact cost")
    if line.currency != "BYN":
        raise service.AccountingError("Fixed-asset acquisition must be recorded in BYN")
    if entry.posting_date > data.commissioning_date:
        raise service.AccountingError("Commissioning cannot precede the acquisition posting")
    period = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id,
        Period.month == entry.posting_date.strftime("%Y-%m"),
        Period.closed.is_(True),
    ))
    if period is not None:
        raise service.AccountingError("Reopen the acquisition period before registering the fixed asset")
    await _validate_accounts(session, org_id, data.commissioning_date, data)
    policy = await session.get(Policy, entry.policy_id)
    if policy is None or policy.organization_id != org_id:
        raise service.AccountingError("The acquisition has no policy belonging to this organization")
    if policy.depreciation_method != data.depreciation_method:
        raise service.AccountingError("Asset depreciation method must match the acquisition policy")
    return entry, line, policy


def serialize_asset(row: FixedAssetRegisterEntry) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "request_key": row.request_key,
        "asset_key": row.asset_key,
        "source_entry_id": row.source_entry_id,
        "source_line_id": row.source_line_id,
        "source_digest": row.source_digest,
        "name": row.name,
        "inventory_number": row.inventory_number,
        "acquisition_date": row.acquisition_date,
        "commissioning_date": row.commissioning_date,
        "depreciation_start": row.depreciation_start,
        "cost": format(row.cost, ".2f"),
        "residual_value": format(row.residual_value, ".2f"),
        "useful_life_months": row.useful_life_months,
        "depreciation_method": row.depreciation_method,
        "asset_account": row.asset_account,
        "accumulated_account": row.accumulated_account,
        "expense_account": row.expense_account,
        "dimensions": row.dimensions,
        "evidence": row.evidence,
        "digest": row.digest,
        "actor": row.actor,
        "created_at": row.created_at,
        "statutory_certified": False,
    }


async def prepare_register(session, org_id: int, data: FixedAssetRegisterInput) -> dict:
    existing_request = await session.scalar(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        return {**serialize_asset(existing_request), "status": "already_registered",
                "register_available": False, "registered_id": existing_request.id}
    entry, line, policy = await _source(session, org_id, data)
    existing_asset = await session.scalar(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.asset_key == data.asset_key,
    ))
    source = {
        "entry_id": entry.id, "line_id": line.id, "source": entry.source,
        "source_version": entry.source_version, "entry_digest": entry.digest,
        "posting_date": entry.posting_date.isoformat(), "operation_date": entry.operation_date.isoformat(),
        "account_code": line.account_code, "side": line.side, "amount": format(line.amount, ".2f"),
        "currency": line.currency, "policy_id": policy.id,
    }
    command = data.model_dump(mode="json", exclude={"digest"})
    digest = _digest({"command": command, "source": source})
    return {
        "organization_id": org_id, "source": source,
        "asset": {
            "asset_key": data.asset_key, "name": data.name, "inventory_number": data.inventory_number,
            "acquisition_date": data.acquisition_date, "commissioning_date": data.commissioning_date,
            "depreciation_start": data.depreciation_start, "cost": format(data.cost, ".2f"),
            "residual_value": format(data.residual_value, ".2f"), "useful_life_months": data.useful_life_months,
            "depreciation_method": data.depreciation_method, "asset_account": data.asset_account,
            "accumulated_account": data.accumulated_account, "expense_account": data.expense_account,
            "dimensions": data.dimensions, "evidence": data.evidence,
        },
        "command": command, "digest": digest, "status": "reviewed_fixed_asset",
        "register_available": existing_asset is None, "registered_id": existing_asset.id if existing_asset else None,
        "statutory_certified": False,
    }


async def confirm_register(session, org_id: int, data: FixedAssetRegisterConfirmInput, actor) -> FixedAssetRegisterEntry:
    # Serialize the request-key, asset-key and source-line checks with the
    # immutable insert.  PostgreSQL must return a deterministic replay instead
    # of letting concurrent confirmations race into a unique-key error.
    await service.lock_organization(session, org_id)
    existing_request = await session.scalar(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        if existing_request.digest != data.digest:
            raise service.AccountingError("Fixed-asset request key was reused with different content")
        return existing_request
    existing_asset = await session.scalar(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.asset_key == data.asset_key,
    ))
    if existing_asset is not None:
        if existing_asset.digest != data.digest:
            raise service.AccountingError("Fixed-asset key is already registered with different content")
        return existing_asset
    prepared = await prepare_register(session, org_id, data)
    if prepared["digest"] != data.digest:
        raise service.AccountingError("Fixed-asset package changed; review it again")
    source = prepared["source"]
    row = FixedAssetRegisterEntry(
        organization_id=org_id, request_key=str(data.request_key), asset_key=data.asset_key,
        source_entry_id=data.source_entry_id, source_line_id=data.source_line_id,
        source_digest=source["entry_digest"], name=data.name, inventory_number=data.inventory_number,
        acquisition_date=data.acquisition_date, commissioning_date=data.commissioning_date,
        depreciation_start=data.depreciation_start, cost=data.cost, residual_value=data.residual_value,
        useful_life_months=data.useful_life_months, depreciation_method=data.depreciation_method,
        asset_account=data.asset_account, accumulated_account=data.accumulated_account,
        expense_account=data.expense_account, dimensions=data.dimensions, evidence=data.evidence,
        command=data.model_dump(mode="json"), digest=data.digest, actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def assets(session, org_id: int) -> list[dict]:
    rows = (await session.scalars(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
    ).order_by(FixedAssetRegisterEntry.commissioning_date, FixedAssetRegisterEntry.id))).all()
    return [serialize_asset(row) for row in rows]


async def asset_result(session, org_id: int, asset_id: int) -> FixedAssetRegisterEntry | None:
    return await session.scalar(select(FixedAssetRegisterEntry).where(
        FixedAssetRegisterEntry.organization_id == org_id,
        FixedAssetRegisterEntry.id == asset_id,
    ))


async def _depreciation_context(session, org_id: int, data: FixedAssetDepreciationInput):
    asset = await asset_result(session, org_id, data.asset_id)
    if asset is None:
        raise service.AccountingError("Fixed asset was not found in this organization")
    if asset.digest != data.expected_asset_digest:
        raise service.AccountingError("The fixed-asset register row changed; read it again")
    first, last = _month_bounds(data.month)
    if first < asset.depreciation_start.replace(day=1):
        raise service.AccountingError("Depreciation month precedes the explicit depreciation start")
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.id == data.policy_id,
    ))
    if policy is None or policy.effective_from > last:
        raise service.AccountingError("Select an applicable policy for the depreciation month")
    if policy.depreciation_method != asset.depreciation_method:
        raise service.AccountingError("Depreciation method does not match the registered asset policy")
    if asset.depreciation_method != "straight_line":
        raise service.AccountingError("Only explicit straight-line depreciation is implemented in this pilot")
    accounts = await service.accounts_on(session, org_id, data.posting_date)
    register_input = FixedAssetRegisterInput(
        request_key=UUID(asset.request_key), asset_key=asset.asset_key,
        source_entry_id=asset.source_entry_id, source_line_id=asset.source_line_id,
        expected_source_digest=asset.source_digest, name=asset.name,
        inventory_number=asset.inventory_number, acquisition_date=asset.acquisition_date,
        commissioning_date=asset.commissioning_date, depreciation_start=asset.depreciation_start,
        cost=asset.cost, residual_value=asset.residual_value, useful_life_months=asset.useful_life_months,
        depreciation_method=asset.depreciation_method, asset_account=asset.asset_account,
        accumulated_account=asset.accumulated_account, expense_account=asset.expense_account,
        dimensions=asset.dimensions, evidence=asset.evidence,
    )
    await _validate_accounts(session, org_id, data.posting_date, register_input)
    expense = accounts.get(asset.expense_account)
    accumulated = accounts.get(asset.accumulated_account)
    if expense is None or accumulated is None:
        raise service.AccountingError("Depreciation accounts are not effective for the posting date")
    receipts = (await session.scalars(select(FixedAssetDepreciationReceipt).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
        FixedAssetDepreciationReceipt.asset_id == asset.id,
    ).order_by(FixedAssetDepreciationReceipt.month))).all()
    existing = next((row for row in receipts if row.month == data.month), None)
    if existing is not None:
        return asset, policy, existing, None
    later = next((row for row in receipts if row.month > data.month), None)
    if later is not None:
        raise service.AccountingError("Cannot add depreciation before an already posted later month")
    start_index = _month_index(asset.depreciation_start)
    current_index = _month_index(first)
    expected_months = [f"{(start_index + offset) // 12:04d}-{(start_index + offset) % 12 + 1:02d}"
                       for offset in range(current_index - start_index)]
    present = {row.month for row in receipts}
    missing = [month for month in expected_months if month not in present]
    if missing:
        raise service.AccountingError(f"Process earlier depreciation months first: {missing[0]}")
    depreciable = (asset.cost - asset.residual_value).quantize(CENT, rounding=ROUND_HALF_UP)
    accumulated_before = sum((Decimal(str(row.calculation.get("amount", "0"))) for row in receipts), Decimal("0"))
    accumulated_before = accumulated_before.quantize(CENT)
    remaining = (depreciable - accumulated_before).quantize(CENT)
    if remaining <= 0:
        return asset, policy, None, {"status": "fully_depreciated", "amount": "0.00",
                                     "accumulated_before": format(accumulated_before, ".2f"),
                                     "remaining_value": "0.00"}
    monthly = (depreciable / asset.useful_life_months).quantize(CENT, rounding=ROUND_HALF_UP)
    amount = min(monthly, remaining)
    dimensions = {**asset.dimensions, **data.dimensions, "asset": asset.asset_key}
    posting = PostingInput(
        source=f"fixed-asset:depreciation:{org_id}:{asset.asset_key}:{data.month}", source_version=1,
        operation="fixed_asset_depreciation", document_date=data.posting_date,
        operation_date=data.posting_date, posting_date=data.posting_date, policy_id=policy.id,
        rule_version="fixed-asset-straight-line-v1:" + asset.digest,
        explanation=f"Амортизация ОС {asset.inventory_number} за {data.month}",
        lines=[
            {"account": asset.expense_account, "side": "debit", "amount": amount, "dimensions": dimensions},
            {"account": asset.accumulated_account, "side": "credit", "amount": amount, "dimensions": dimensions},
        ],
    )
    await service.validate_posting(session, org_id, posting, fixed_asset_depreciation=True)
    calculation = {
        "method": "straight_line", "amount": format(amount, ".2f"),
        "depreciable_base": format(depreciable, ".2f"),
        "accumulated_before": format(accumulated_before, ".2f"),
        "accumulated_after": format(accumulated_before + amount, ".2f"),
        "remaining_value": format(asset.cost - accumulated_before - amount, ".2f"),
        "useful_life_months": asset.useful_life_months,
    }
    return asset, policy, None, {"status": "reviewed_fixed_asset_depreciation", "calculation": calculation,
                                 "posting": posting, "digest": service.digest(posting)}


def serialize_depreciation(row: FixedAssetDepreciationReceipt) -> dict:
    return {
        "entry_id": row.entry_id, "organization_id": row.organization_id, "asset_id": row.asset_id,
        "month": row.month, "request_key": row.request_key, "calculation": row.calculation,
        "posting": row.posting, "digest": row.digest, "actor": row.actor,
        "created_at": row.created_at, "posted": True, "statutory_certified": False,
        "final_cost_certified": False,
    }


async def prepare_depreciation(session, org_id: int, data: FixedAssetDepreciationInput) -> dict:
    existing_request = await session.scalar(select(FixedAssetDepreciationReceipt).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
        FixedAssetDepreciationReceipt.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        return {**serialize_depreciation(existing_request), "status": "already_posted", "posting_available": False}
    asset, policy, existing, result = await _depreciation_context(session, org_id, data)
    if existing is not None:
        return {**serialize_depreciation(existing), "status": "already_posted", "posting_available": False}
    if result is None:
        raise service.AccountingError("Depreciation calculation returned no result")
    if result["status"] == "fully_depreciated":
        return {"organization_id": org_id, "asset_id": asset.id, "month": data.month,
                "policy_id": policy.id, **result, "posting_available": False,
                "posted": False, "statutory_certified": False, "final_cost_certified": False}
    posting: PostingInput = result["posting"]
    command = data.model_dump(mode="json", exclude={"digest"})
    return {"organization_id": org_id, "asset_id": asset.id, "asset_digest": asset.digest,
            "month": data.month, "policy_id": policy.id, "status": result["status"],
            "calculation": result["calculation"], "posting_document": posting.model_dump(mode="json"),
            "command": command, "digest": result["digest"], "posting_available": True,
            "posted": False, "statutory_certified": False, "final_cost_certified": False}


async def confirm_depreciation(session, org_id: int, data: FixedAssetDepreciationConfirmInput,
                               actor, event_bus=None) -> FixedAssetDepreciationReceipt:
    # The organization lock covers the ordered-month check and the receipt
    # insert, so concurrent confirmations replay the committed receipt.
    await service.lock_organization(session, org_id)
    existing_request = await session.scalar(select(FixedAssetDepreciationReceipt).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
        FixedAssetDepreciationReceipt.request_key == str(data.request_key),
    ))
    if existing_request is not None:
        if existing_request.digest != data.digest:
            raise service.AccountingError("Depreciation request key was reused with different content")
        return existing_request
    prepared = await prepare_depreciation(session, org_id, data)
    if not prepared.get("posting_available"):
        raise service.AccountingError("This depreciation month has no postable amount")
    if prepared["digest"] != data.digest:
        raise service.AccountingError("Depreciation package changed; review it again")
    posting = PostingInput.model_validate(prepared["posting_document"])
    entry = await service.post(session, org_id, posting, actor, event_bus,
                               fixed_asset_depreciation=True)
    row = FixedAssetDepreciationReceipt(
        entry_id=entry.id, organization_id=org_id, asset_id=data.asset_id, month=data.month,
        request_key=str(data.request_key), command=data.model_dump(mode="json"),
        calculation=prepared["calculation"], posting=prepared["posting_document"],
        digest=data.digest, actor=actor,
    )
    session.add(row)
    await session.flush()
    return row


async def depreciation_result(session, org_id: int, request_key: UUID) -> FixedAssetDepreciationReceipt | None:
    return await session.scalar(select(FixedAssetDepreciationReceipt).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
        FixedAssetDepreciationReceipt.request_key == str(request_key),
    ))


async def depreciation_rows(session, org_id: int, month: str | None = None) -> list[dict]:
    query = select(FixedAssetDepreciationReceipt).where(
        FixedAssetDepreciationReceipt.organization_id == org_id,
    )
    if month is not None:
        _month_bounds(month)
        query = query.where(FixedAssetDepreciationReceipt.month == month)
    rows = (await session.scalars(query.order_by(FixedAssetDepreciationReceipt.month,
                                                  FixedAssetDepreciationReceipt.entry_id))).all()
    return [serialize_depreciation(row) for row in rows]
