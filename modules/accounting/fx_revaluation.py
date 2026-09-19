"""Reviewed foreign-currency revaluation for explicitly configured books.

The workflow deliberately requires the organisation policy and the exact rate
evidence in the command.  It does not read a demo rate, add a commercial
reserve or silently choose a gain/loss account.  The preview is a pure basis
calculation; confirmation writes one immutable correction-aware ledger package.
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import select

from core.domain.reference import Currency
from modules.accounting import service
from modules.accounting.models import (
    Account,
    Entry,
    FxRevaluationReceipt,
    Line,
    Period,
    Policy,
)
from modules.accounting.schemas import (
    CurrencyRevaluationPolicyInput,
    FxRateInput,
    FxRevaluationConfirmInput,
    FxRevaluationInput,
    LineInput,
    PostingInput,
)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise service.AccountingError("Month must be YYYY-MM") from exc
    if first.strftime("%Y-%m") != month:
        raise service.AccountingError("Month must be YYYY-MM")
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _round_cents(value: Fraction) -> Decimal:
    """Round an exact rational amount to BYN cents, half-up, context-free."""
    sign = -1 if value < 0 else 1
    value = abs(value)
    whole, remainder = divmod(value.numerator, value.denominator)
    cents = whole + int(2 * remainder >= value.denominator)
    return (Decimal(cents) / Decimal("100")) * sign


def _converted(original: Decimal, rate: Decimal, rate_scale: int) -> Decimal:
    return _round_cents(Fraction(original) * Fraction(rate) * 100 / rate_scale)


def _dimensions(value: dict, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise service.AccountingError(f"{label} must be an object")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(item, str) or not item.strip():
            raise service.AccountingError(f"{label} contains an invalid analytical identifier")
        result[key] = item
    return result


async def validate_policy_accounts(session, org_id: int, effective_date: date,
                                  settings: CurrencyRevaluationPolicyInput):
    accounts = await service.accounts_on(session, org_id, effective_date)
    monetary = []
    for code in settings.monetary_accounts:
        account = accounts.get(code)
        if account is None:
            raise service.AccountingError(f"Currency revaluation account {code} is not effective for this organization")
        if account.category not in {"asset", "liability"} or not account.currency_tracking \
                or account.quantity_tracking or account.cash:
            raise service.AccountingError(
                f"Currency revaluation account {code} must be a noncash asset/liability with currency tracking"
            )
        monetary.append(account)
    gain = accounts.get(settings.gain_account)
    loss = accounts.get(settings.loss_account)
    if gain is None or gain.category != "income" or gain.cash or gain.currency_tracking or gain.quantity_tracking:
        raise service.AccountingError("Currency gain account must be an effective noncash BYN income account")
    if loss is None or loss.category != "expense" or loss.cash or loss.currency_tracking or loss.quantity_tracking:
        raise service.AccountingError("Currency loss account must be an effective noncash BYN expense account")
    gain_dimensions = _dimensions(settings.gain_dimensions, label="Currency gain analytics")
    loss_dimensions = _dimensions(settings.loss_dimensions, label="Currency loss analytics")
    if set(gain.required_dimensions) != set(gain_dimensions):
        raise service.AccountingError(f"Currency gain account {gain.code} requires its exact configured analytics")
    if set(loss.required_dimensions) != set(loss_dimensions):
        raise service.AccountingError(f"Currency loss account {loss.code} requires its exact configured analytics")
    return accounts, monetary, gain, loss


async def validate_policy(session, org_id: int, effective_date: date,
                          settings: CurrencyRevaluationPolicyInput):
    """Validate a policy before it is persisted."""
    await validate_policy_accounts(session, org_id, effective_date, settings)


def _rate_map(rates: list[FxRateInput], last: date, posting_date: date):
    result = {}
    for rate in rates:
        if rate.currency == "BYN":
            raise service.AccountingError("BYN does not need an FX revaluation rate")
        if rate.currency in result:
            raise service.AccountingError(f"Duplicate FX rate for {rate.currency}")
        if rate.rate_date > posting_date or rate.rate_date > last:
            raise service.AccountingError("FX rate date cannot be after the revaluation posting date")
        result[rate.currency] = rate
    return result


def _side(delta: Decimal) -> str:
    # Both asset and liability buckets use debit-positive ledger balances.
    return "debit" if delta > 0 else "credit"


def _counterpart(delta: Decimal, gain_account: Account, loss_account: Account):
    # A signed debit increase is offset by income; a credit increase by expense.
    # Liability balances already carry a minus sign, so do not invert twice.
    gain = delta > 0
    return gain_account if gain else loss_account, ("credit" if gain else "debit")


async def _policy(session, org_id: int, month: str, data: FxRevaluationInput):
    first, last = _month_bounds(month)
    if data.posting_date < first or data.posting_date > last:
        raise service.AccountingError("FX revaluation posting date must belong to the selected period")
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.id == data.policy_id,
    ))
    if policy is None or policy.effective_from > first or policy.currency_revaluation is None:
        raise service.AccountingError("The saved currency revaluation policy is not available for this period")
    versions = (await session.scalars(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= data.posting_date,
    ).order_by(Policy.effective_from.desc()))).all()
    if any(row.effective_from > first and row.currency_revaluation != policy.currency_revaluation
           for row in versions):
        raise service.AccountingError("Currency revaluation policy changed within this period; reconcile policy versions")
    settings = CurrencyRevaluationPolicyInput.model_validate(policy.currency_revaluation)
    accounts, monetary, gain, loss = await validate_policy_accounts(session, org_id, data.posting_date, settings)
    return first, last, policy, settings, accounts, monetary, gain, loss


async def _prior_valuations(session, org_id, as_of, balances, foreign_entry_ids):
    """Attribute actual BYN adjustments using their immutable currency receipts."""
    entries = (await session.scalars(select(Entry).where(
        Entry.organization_id == org_id, Entry.operation == "fx_revaluation",
        Entry.posting_date <= as_of,
    ).order_by(Entry.id))).all()
    frontier = set(foreign_entry_ids) | {entry.id for entry in entries}
    visited = set(frontier)
    while frontier:
        corrections = (await session.scalars(select(Entry).where(
            Entry.organization_id == org_id, Entry.posting_date <= as_of,
            Entry.correction_of.in_(frontier),
        ))).all()
        for correction in corrections:
            if correction.operation != "fx_revaluation" and await session.scalar(select(Line.id).where(
                Line.entry_id == correction.id, Line.currency == "BYN",
                Line.account_code.in_({key[0] for key in balances}),
            ).limit(1)) is not None:
                raise service.AccountingError("Foreign monetary history has an unattributed BYN correction; reconcile its currency position")
        frontier = {entry.id for entry in corrections} - visited
        visited.update(frontier)
    evidence = []
    for entry in entries:
        receipt = await session.scalar(select(FxRevaluationReceipt).where(
            FxRevaluationReceipt.organization_id == org_id, FxRevaluationReceipt.entry_id == entry.id,
        ))
        if receipt is None or receipt.digest != _receipt_digest(receipt):
            raise service.AccountingError("Prior FX valuation receipt is missing or damaged")
        try:
            document = PostingInput.model_validate(receipt.snapshot["posting_document"])
            adjustments = receipt.snapshot["adjustments"]
            if (service.digest(document) != entry.digest or receipt.snapshot["digest"] != entry.digest
                    or len(document.lines) != 2 * len(adjustments)):
                raise ValueError("Posting evidence mismatch")
            actual = (await session.scalars(select(Line).where(Line.entry_id == entry.id)
                                            .order_by(Line.id))).all()
            if len(actual) != len(document.lines):
                raise ValueError("Ledger line count mismatch")
            for line, expected in zip(actual, document.lines, strict=True):
                reconstructed = LineInput(account=line.account_code, **{
                    key: getattr(line, key) for key in LineInput.model_fields if key != "account"
                })
                if reconstructed != expected:
                    raise ValueError("Ledger line evidence mismatch")
            for index, adjustment in enumerate(adjustments):
                line = actual[2 * index]
                key = (adjustment["account"], _canonical(adjustment["dimensions"]), adjustment["currency"])
                if (line.account_code != key[0] or _canonical(line.dimensions) != key[1]
                        or line.currency != "BYN" or line.amount != abs(Decimal(adjustment["delta"]))):
                    raise ValueError("Currency position evidence mismatch")
                if key not in balances:
                    continue  # A position outside the currently selected monetary accounts.
                # Use the actual side, including old v1 liabilities; never rewrite history.
                balances[key]["book"] += line.amount if line.side == "debit" else -line.amount
                balances[key]["line_ids"].append(line.id)
        except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
            raise service.AccountingError("Prior FX valuation evidence does not match its ledger") from exc
        evidence.append({"receipt_id": receipt.id, "receipt_digest": receipt.digest,
                         "entry_id": entry.id, "entry_digest": entry.digest})
    return evidence


async def preview(session, org_id: int, month: str, data: FxRevaluationInput) -> dict:
    """Build a deterministic, non-posting package for the selected month."""
    org = await service.lock_organization(session, org_id)
    first, last, policy, settings, accounts, monetary, gain, loss = await _policy(session, org_id, month, data)
    period = await session.scalar(select(Period).where(
        Period.organization_id == org_id, Period.month == month,
    ).execution_options(populate_existing=True))
    if period and period.closed:
        raise service.AccountingError("Reopen the period before calculating an FX revaluation")
    rates = _rate_map(data.rates, last, data.posting_date)
    active = set((await session.scalars(select(Currency.code).where(
        Currency.code.in_(list(rates)), Currency.is_active.is_(True),
    ))).all())
    if active != set(rates):
        raise service.AccountingError(f"Unknown or inactive FX currency: {sorted(set(rates) - active)}")

    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == org_id,
        Entry.posting_date <= data.posting_date,
        Line.account_code.in_(settings.monetary_accounts),
        Line.currency != "BYN",
    ).order_by(Entry.id, Line.id))).all()
    balances: dict[tuple[str, str, str], dict] = {}
    source_lines = []
    account_map = {account.code: account for account in monetary}
    for entry, line in rows:
        if line.original_amount is None:
            raise service.AccountingError("Foreign monetary history is missing its original amount")
        if line.currency not in rates:
            raise service.AccountingError(f"An explicit FX rate is required for {line.currency}")
        account = account_map.get(line.account_code)
        if account is None:
            raise service.AccountingError(f"Currency account {line.account_code} is not in the policy")
        key = (line.account_code, _canonical(line.dimensions), line.currency)
        bucket = balances.setdefault(key, {
            "account": line.account_code,
            "dimensions": line.dimensions,
            "currency": line.currency,
            "original": Decimal("0"),
            "book": Decimal("0"),
            "line_ids": [],
        })
        sign = 1 if line.side == "debit" else -1
        bucket["original"] += line.original_amount * sign
        bucket["book"] += line.amount * sign
        bucket["line_ids"].append(line.id)
        source_lines.append({
            "entry_id": entry.id, "line_id": line.id, "entry_digest": entry.digest,
            "account": line.account_code, "dimensions": line.dimensions, "currency": line.currency,
            "side": line.side, "original_amount": format(line.original_amount, "f"),
            "amount": format(line.amount, "f"), "posting_date": entry.posting_date.isoformat(),
        })

    prior_valuations = await _prior_valuations(session, org_id, data.posting_date, balances, {entry.id for entry, _ in rows})
    posting_lines: list[LineInput] = []
    adjustments = []
    for key in sorted(balances):
        bucket = balances[key]
        rate = rates[bucket["currency"]]
        desired = _converted(bucket["original"], rate.rate, rate.rate_scale)
        delta = desired - bucket["book"]
        if delta == 0:
            continue
        account = account_map[bucket["account"]]
        counterpart, counterpart_side = _counterpart(delta, gain, loss)
        monetary_side = _side(delta)
        amount = abs(delta)
        posting_lines.extend([
            LineInput(account=account.code, side=monetary_side, amount=amount,
                      dimensions=bucket["dimensions"]),
            LineInput(account=counterpart.code, side=counterpart_side, amount=amount,
                      dimensions=(settings.gain_dimensions if counterpart is gain else settings.loss_dimensions)),
        ])
        adjustments.append({
            "account": account.code, "dimensions": bucket["dimensions"], "currency": bucket["currency"],
            "original_balance": format(bucket["original"], "f"), "book_balance": format(bucket["book"], "f"),
            "revalued_balance": format(desired, "f"), "delta": format(delta, "f"),
            "line_ids": bucket["line_ids"], "rate": rate.model_dump(mode="json"),
            "counterpart": counterpart.code, "monetary_side": monetary_side,
            "counterpart_side": counterpart_side,
        })

    previous = await session.scalar(select(FxRevaluationReceipt).where(
        FxRevaluationReceipt.organization_id == org_id, FxRevaluationReceipt.month == month,
    ).order_by(FxRevaluationReceipt.source_version.desc()))
    source_version = (previous.source_version + 1) if previous else 1
    correction_of = await session.scalar(select(Entry.id).where(
        Entry.organization_id == org_id, Entry.source == f"accounting:fx-revaluation:{org_id}:{month}",
        Entry.operation == "fx_revaluation",
    ).order_by(Entry.source_version.desc()).limit(1))
    posting = PostingInput(
        source=f"accounting:fx-revaluation:{org_id}:{month}", source_version=source_version,
        operation="fx_revaluation", document_date=data.posting_date, operation_date=data.posting_date,
        posting_date=data.posting_date, policy_id=policy.id, rule_version="fx-revaluation-v4",
        explanation=f"FX revaluation for {month}: reviewed documented rates", lines=posting_lines,
        correction_of=correction_of,
    ) if posting_lines else None
    if posting is not None:
        await service.validate_posting(session, org_id, posting, fx_revaluation=True)
    basis = {
        "organization_id": org_id, "month": month, "first": first.isoformat(), "last": last.isoformat(),
        "policy_id": policy.id, "policy_reference": policy.reference,
        "policy_settings": settings.model_dump(mode="json"), "period_generation": period.generation if period else 0,
        "organization_generation": org.generation, "source_version": source_version,
        "correction_of": correction_of, "rates": [rates[key].model_dump(mode="json") for key in sorted(rates)],
        "source_lines": source_lines, "prior_valuations": prior_valuations, "adjustments": adjustments,
        "posting": posting.model_dump(mode="json") if posting else None,
        "evidence": data.evidence,
    }
    basis_digest = _digest(basis)
    return {
        "organization_id": org_id, "month": month, "policy_id": policy.id,
        "period_generation": basis["period_generation"], "source_version": source_version,
        "basis_digest": basis_digest, "source_line_count": len(source_lines),
        "adjustments": adjustments, "posting_document": posting.model_dump(mode="json") if posting else None,
        "digest": service.digest(posting) if posting else _digest({"basis": basis_digest, "posting": None}),
        "status": "preview_only", "confirmation_available": bool(policy.normative_verified),
        "normative_verified": policy.normative_verified, "statutory_certified": False,
        "basis": basis,
    }


def serialize(row: FxRevaluationReceipt) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id, "request_key": row.request_key,
        "month": row.month, "source_version": row.source_version, "command": row.command,
        "command_digest": row.command_digest, "snapshot": row.snapshot, "digest": row.digest,
        "entry_id": row.entry_id, "actor": row.actor, "created_at": row.created_at,
        "status": "recorded", "statutory_certified": False,
    }


def _receipt_digest(row: FxRevaluationReceipt) -> str:
    return _digest({
        "organization_id": row.organization_id, "request_key": row.request_key,
        "kind": "fx_revaluation", "month": row.month, "source_version": row.source_version,
        "command": row.command,
        "command_digest": row.command_digest, "snapshot": row.snapshot, "entry_id": row.entry_id,
        "actor": row.actor,
    })


async def confirm(session, org_id: int, month: str, data: FxRevaluationConfirmInput,
                 actor: str, event_bus=None):
    await service.lock_organization(session, org_id)
    command = {"month": month, **data.model_dump(mode="json")}
    command_digest = _digest(command)
    existing = await session.scalar(select(FxRevaluationReceipt).where(
        FxRevaluationReceipt.organization_id == org_id,
        FxRevaluationReceipt.request_key == str(data.request_key),
    ))
    if existing is not None:
        if existing.command_digest != command_digest or existing.snapshot.get("digest") != data.digest:
            raise service.AccountingError("FX revaluation request key was reused with different content")
        return existing
    plan = await preview(session, org_id, month, data)
    if plan["basis_digest"] != data.basis_digest or plan["digest"] != data.digest:
        raise service.AccountingError("FX revaluation basis changed; review it again")
    period = await service.period_for(session, org_id, month)
    if period.generation != data.expected_generation:
        raise service.AccountingError("FX revaluation data changed after review; calculate it again")
    entry = None
    if plan["posting_document"] is not None:
        entry = await service.post(session, org_id, PostingInput.model_validate(plan["posting_document"]),
                                   actor, event_bus, fx_revaluation=True)
    snapshot = {**plan, "confirmation": {"actor": actor, "evidence": data.evidence},
                "posted": entry is not None, "entry_id": entry.id if entry else None}
    row = FxRevaluationReceipt(
        organization_id=org_id, request_key=str(data.request_key), month=month,
        source_version=plan["source_version"], command=command, command_digest=command_digest,
        snapshot=snapshot, digest="", entry_id=entry.id if entry else None, actor=actor,
    )
    row.digest = _receipt_digest(row)
    session.add(row)
    await session.flush()
    service.audit(session, org_id, actor, "fx_revaluation_recorded", {
        "receipt_id": row.id, "month": month, "entry_id": row.entry_id, "digest": row.digest,
    })
    return row
