"""Versioned mapping from an external bank account to an accounting cash account."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select

from modules.accounting.models import Account, BankAccountMapping, BankImportReceipt, Period


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def result(row):
    snapshot = {
        "mapping_id": row.id, "organization_id": row.organization_id, "provider": row.provider,
        "external_account": row.external_account, "currency": row.currency,
        "valid_from": row.valid_from.isoformat(), "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "version": row.version, "ledger_account_id": row.ledger_account_id,
        "dimensions": dict(row.dimensions),
    }
    return {**snapshot, "digest": _digest(snapshot), "evidence": row.evidence,
            "actor": row.actor, "created_at": row.created_at.isoformat() if row.created_at else None}


async def _effective_account(session, org_id, account_id, on):
    pinned = await session.get(Account, account_id)
    if pinned is None or pinned.organization_id != org_id:
        raise HTTPException(422, "Ledger account must belong to this organization")
    effective = await session.scalar(select(Account).where(
        Account.organization_id == org_id, Account.code == pinned.code, Account.valid_from <= on,
    ).order_by(Account.valid_from.desc(), Account.id.desc()).limit(1))
    if effective is None or effective.id != account_id:
        raise HTTPException(409, "Ledger account version is stale; create a new mapping version")
    return pinned


async def _validate_account(session, org_id, account_id, on, currency, dimensions):
    account = await _effective_account(session, org_id, account_id, on)
    if account.category != "asset" or not account.cash or account.quantity_tracking:
        raise HTTPException(422, "Bank mapping requires an asset cash account without quantity tracking")
    if currency != "BYN" and not account.currency_tracking:
        raise HTTPException(422, "Foreign bank mapping requires currency tracking")
    if set(dimensions) != set(account.required_dimensions):
        raise HTTPException(422, "Bank mapping analytics must exactly match the ledger account")
    return account


async def _assert_open_periods(session, org_id, on):
    closed = await session.scalar(select(Period.id).where(
        Period.organization_id == org_id, Period.month >= on.strftime("%Y-%m"), Period.closed.is_(True),
    ).limit(1))
    if closed is not None:
        raise HTTPException(409, "Bank mapping affects a closed period")


async def _assert_unused_after(session, row, valid_to):
    """Do not let a configuration close exclude a receipt that pinned it."""
    receipts = (await session.scalars(select(BankImportReceipt).where(
        BankImportReceipt.organization_id == row.organization_id,
    ))).all()
    for receipt in receipts:
        mapping = receipt.snapshot.get("mapping") if receipt.snapshot else None
        if mapping and mapping.get("mapping_id") == row.id and receipt.operation_date >= valid_to:
            raise HTTPException(409, "Bank mapping is already used by an immutable receipt on this date")


async def create(session, org_id, data, actor):
    await _assert_open_periods(session, org_id, data.valid_from)
    await _validate_account(session, org_id, data.ledger_account_id, data.valid_from, data.currency, data.dimensions)
    rows = (await session.scalars(select(BankAccountMapping).where(
        BankAccountMapping.provider == data.provider,
        BankAccountMapping.external_account == data.external_account,
        BankAccountMapping.currency == data.currency,
    ).with_for_update())).all()
    predecessor_before = None
    predecessor = None
    for row in rows:
        # A new version is open-ended, so any existing interval ending after
        # its start overlaps it, including a configuration dated in the future.
        if row.valid_to is None or data.valid_from < row.valid_to:
            if (row.organization_id == org_id and row.valid_to is None
                    and row.valid_from < data.valid_from):
                await _assert_unused_after(session, row, data.valid_from)
                predecessor_before = result(row)
                predecessor = row
                row.valid_to = data.valid_from
                continue
            raise HTTPException(409, "External bank account already has an effective mapping")
    version = (await session.scalar(select(func.max(BankAccountMapping.version)).where(
        BankAccountMapping.organization_id == org_id, BankAccountMapping.provider == data.provider,
        BankAccountMapping.external_account == data.external_account, BankAccountMapping.currency == data.currency,
    ))) or 0
    row = BankAccountMapping(organization_id=org_id, provider=data.provider, external_account=data.external_account,
                             currency=data.currency, valid_from=data.valid_from, valid_to=None, version=version + 1,
                             ledger_account_id=data.ledger_account_id, dimensions=data.dimensions,
                             evidence=data.evidence, actor=actor)
    session.add(row)
    await session.flush()
    return row, predecessor_before, predecessor


async def get_one(session, org_id, mapping_id):
    row = await session.scalar(select(BankAccountMapping).where(
        BankAccountMapping.id == mapping_id, BankAccountMapping.organization_id == org_id,
    ))
    if row is None:
        raise HTTPException(404, "Bank account mapping was not found")
    return row


async def list_for(session, org_id, *, provider=None, external_account=None, currency=None, on=None, include_closed=False):
    query = select(BankAccountMapping).where(BankAccountMapping.organization_id == org_id)
    for field, value in ((BankAccountMapping.provider, provider), (BankAccountMapping.external_account, external_account),
                         (BankAccountMapping.currency, currency)):
        if value is not None:
            query = query.where(field == value)
    if on is not None:
        query = query.where(BankAccountMapping.valid_from <= on).where(
            (BankAccountMapping.valid_to.is_(None)) | (on < BankAccountMapping.valid_to))
    elif not include_closed:
        query = query.where(BankAccountMapping.valid_to.is_(None))
    return (await session.scalars(query.order_by(BankAccountMapping.provider, BankAccountMapping.external_account,
                                                  BankAccountMapping.valid_from.desc()))).all()


async def close(session, org_id, mapping_id, data):
    """Close configuration history without excluding a receipt that pinned it."""
    row = await get_one(session, org_id, mapping_id)
    await session.refresh(row, with_for_update=True)
    if row.valid_to is not None:
        raise HTTPException(409, "Bank account mapping is already closed")
    if data.valid_to <= row.valid_from:
        raise HTTPException(422, "Mapping close date must follow its start")
    await _assert_open_periods(session, org_id, data.valid_to)
    await _assert_unused_after(session, row, data.valid_to)
    before = result(row)
    row.valid_to = data.valid_to
    await session.flush()
    return row, before


async def resolve(session, org_id, *, provider, external_account, currency, on):
    """Resolve configuration only; callers must separately enforce SourceBinding."""
    rows = await list_for(session, org_id, provider=provider, external_account=external_account,
                          currency=currency, on=on, include_closed=True)
    if len(rows) != 1:
        raise HTTPException(409, "Bank account mapping is missing or ambiguous")
    row = rows[0]
    await _validate_account(session, org_id, row.ledger_account_id, on, currency, row.dimensions)
    return row


async def resolve_fingerprint(session, org_id, *, provider, external_account, currency, on):
    """Return the exact effective cash configuration for a bank-import preview."""
    row = await resolve(session, org_id, provider=provider, external_account=external_account,
                        currency=currency, on=on)
    account = await _effective_account(session, org_id, row.ledger_account_id, on)
    snapshot = result(row)
    return {
        "mapping_id": snapshot["mapping_id"],
        "version": snapshot["version"],
        "digest": snapshot["digest"],
        "ledger_account_id": snapshot["ledger_account_id"],
        "bank_account": account.code,
        "dimensions": snapshot["dimensions"],
    }
