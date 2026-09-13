"""Internal financial closing packages. Public confirmation awaits PostgreSQL guards."""
import hashlib
from calendar import monthrange
from datetime import date

from sqlalchemy import select

from modules.accounting import service
from modules.accounting.financial_closing import canonical, preview
from modules.accounting.models import (
    Entry,
    FinancialCloseReceipt,
    FinancialReopenItem,
    FinancialReopenReceipt,
    Line,
    Period,
)
from modules.accounting.schemas import CloseInput, FinancialReopenInput, LineInput, PostingInput


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def receipt_checksum(row):
    return checksum({"organization_id": row.organization_id, "request_key": row.request_key,
        "kind": "close" if isinstance(row, FinancialCloseReceipt) else "reopen",
        "command": row.command, "command_digest": row.command_digest,
        "snapshot": row.snapshot, "actor": row.actor})


def closing_posting(month, key, phase, plan):
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return PostingInput(source=f"financial-close:{key}:{phase}", source_version=1,
        operation="period_close", document_date=last, operation_date=last, posting_date=last,
        policy_id=plan["policy_id"], rule_version=f"financial-closing-v1:{phase}",
        explanation=f"Financial closing {month}: {phase}", lines=plan[phase + "_lines"])


def reversal_posting(original, key, entry_id, reason):
    body = original.model_dump(mode="json")
    body.update(source=f"financial-reopen:{key}:{entry_id}", operation="period_reopen",
        correction_of=entry_id, rule_version="financial-reopening-v1", explanation=reason)
    for line in body["lines"]:
        line["side"] = "credit" if line["side"] == "debit" else "debit"
    return PostingInput.model_validate(body)


async def actual_posting(session, entry):
    body = {key: getattr(entry, key) for key in PostingInput.model_fields if key != "lines"}
    lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
    body["lines"] = [{"account": line.account_code, **{key: getattr(line, key)
        for key in LineInput.model_fields if key != "account"}}
        for line in lines]
    return PostingInput.model_validate(body)


async def authenticated_entries(session, org_id):
    """Validate immutable package membership, never classify by operation text alone.

    These application checks complement, and do not replace, the required SQL
    calculation/package guards before enabling public confirmation.
    """
    closes = (await session.scalars(select(FinancialCloseReceipt).where(
        FinancialCloseReceipt.organization_id == org_id))).all()
    reopens = (await session.scalars(select(FinancialReopenReceipt).where(
        FinancialReopenReceipt.organization_id == org_id))).all()
    close_by_id = {row.id: row for row in closes}
    certified = {}

    async def verify_entry(entry_id, expected, actor):
        if entry_id in certified:
            raise service.AccountingError("Financial entry belongs to more than one receipt")
        entry = await session.get(Entry, entry_id)
        if (entry is None or entry.organization_id != org_id or entry.actor != actor
                or entry.digest != service.digest(expected)
                or (await actual_posting(session, entry)).model_dump(mode="json") != expected.model_dump(mode="json")):
            raise service.AccountingError("Financial receipt does not match its posted entry")
        certified[entry_id] = expected

    for receipt in [*closes, *reopens]:
        if receipt.command_digest != checksum(receipt.command) or receipt.digest != receipt_checksum(receipt):
            raise service.AccountingError("Financial receipt checksum mismatch")
    for receipt in closes:
        plan = receipt.snapshot["preview"]
        if plan["organization_id"] != org_id or plan["month"] != receipt.month:
            raise service.AccountingError("Financial receipt scope mismatch")
        for phase in ("monthly", "annual"):
            entry_id = getattr(receipt, phase + "_entry_id")
            if bool(plan[phase + "_lines"]) != (entry_id is not None):
                raise service.AccountingError("Financial receipt has an incomplete transfer")
            if entry_id is not None:
                await verify_entry(entry_id, closing_posting(receipt.month, receipt.request_key, phase, plan), receipt.actor)
    for receipt in reopens:
        items = (await session.scalars(select(FinancialReopenItem).where(
            FinancialReopenItem.reopen_receipt_id == receipt.id).order_by(FinancialReopenItem.close_receipt_id))).all()
        expected_items = [{"close_receipt_id": item.close_receipt_id, "monthly_entry_id": item.monthly_entry_id,
                           "annual_entry_id": item.annual_entry_id} for item in items]
        if expected_items != receipt.snapshot["items"]:
            raise service.AccountingError("Financial reopening receipt has an incomplete cascade")
        for item in items:
            original = close_by_id.get(item.close_receipt_id)
            if original is None or original.month < receipt.from_month:
                raise service.AccountingError("Invalid financial reopening source")
            for phase in ("monthly", "annual"):
                source_id = getattr(original, phase + "_entry_id")
                entry_id = getattr(item, phase + "_entry_id")
                if (source_id is None) != (entry_id is None):
                    raise service.AccountingError("Financial reopening has an incomplete reversal")
                if entry_id is not None:
                    await verify_entry(entry_id, reversal_posting(certified[source_id], receipt.request_key,
                        source_id, receipt.command["reason"]), receipt.actor)
    return certified


async def confirm(session, org_id, month, data, actor, event_bus=None):
    await service.lock_organization(session, org_id)
    command = {"month": month, **data.model_dump(mode="json")}
    existing = await session.scalar(select(FinancialCloseReceipt).where(
        FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.request_key == str(data.request_key)))
    if existing:
        if existing.command_digest != checksum(command):
            raise service.AccountingError("Financial closing UUID reused with different content")
        await authenticated_entries(session, org_id)
        return existing
    plan = await preview(session, org_id, month, include_basis=True)
    if plan["basis_digest"] != data.expected_basis_digest:
        raise service.AccountingError("Financial closing basis changed; calculate and review again")
    # Validate all user-reviewed controls before writing either technical entry.
    await service.validate_close_period(session, org_id, month, data)
    entries = {}
    for phase in ("monthly", "annual"):
        entries[phase + "_entry_id"] = None
        if plan[phase + "_lines"]:
            entry = await service.post(session, org_id, closing_posting(month, data.request_key, phase, plan),
                actor, event_bus, financial_transfer=True)
            entries[phase + "_entry_id"] = entry.id
    period = await service.period_for(session, org_id, month)
    await service.close_period(session, org_id, month, CloseInput(
        expected_generation=period.generation, evidence=data.evidence), actor, financial_transfer=True)
    receipt = FinancialCloseReceipt(organization_id=org_id, request_key=str(data.request_key), month=month,
        command=command, command_digest=checksum(command), actor=actor, **entries,
        snapshot={"preview": plan, "closed_generation": period.closed_generation, **entries}, digest="")
    receipt.digest = receipt_checksum(receipt)
    session.add(receipt)
    await session.flush()
    service.audit(session, org_id, actor, "financial_period_closed", {"receipt_id": receipt.id, "digest": receipt.digest})
    if event_bus is not None:
        event_bus.emit(session, "accounting.financial_period.closed", {
            "organization_id": org_id, "receipt_id": receipt.id, "digest": receipt.digest})
    await session.flush()
    return receipt


async def preview_reopening(session, org_id, month):
    """Describe the authenticated cascade under the organization lock, without writes."""
    await service.lock_organization(session, org_id)
    certified = await authenticated_entries(session, org_id)
    periods = (await session.scalars(select(Period).where(
        Period.organization_id == org_id, Period.month >= month).order_by(Period.month))).all()
    if not any(period.month == month and period.closed for period in periods):
        raise service.AccountingError("Select a closed period to reopen")
    closes = (await session.scalars(select(FinancialCloseReceipt).outerjoin(FinancialReopenItem,
        FinancialReopenItem.close_receipt_id == FinancialCloseReceipt.id).where(
        FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.month >= month,
        FinancialReopenItem.id.is_(None)).order_by(FinancialCloseReceipt.id))).all()
    return reopening_basis(org_id, month,
        [{"month": p.month, "generation": p.generation, "closed": p.closed} for p in periods], closes, certified)


def reopening_basis(org_id, month, periods, closes, certified):
    entries = []
    for receipt in closes:
        for phase in ("annual", "monthly"):
            entry_id = getattr(receipt, phase + "_entry_id")
            if entry_id is not None:
                original = certified[entry_id].model_dump(mode="json")
                entries.append({"close_receipt_id": receipt.id, "entry_id": entry_id,
                    "month": receipt.month, "phase": phase, "lines": [
                        {**line, "side": "credit" if line["side"] == "debit" else "debit"}
                        for line in original["lines"]]})
    result = {"organization_id": org_id, "from_month": month,
        "periods": periods,
        "reversals": entries, "status": "preview", "posted": False}
    return {**result, "basis_digest": checksum(result)}


async def confirm_reopening(session, org_id, month, data, actor, event_bus=None):
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(FinancialReopenReceipt).where(
        FinancialReopenReceipt.organization_id == org_id,
        FinancialReopenReceipt.request_key == str(data.request_key)))
    if existing is None:
        plan = await preview_reopening(session, org_id, month)
    else:
        certified = await authenticated_entries(session, org_id)
        ids = [item["close_receipt_id"] for item in existing.snapshot["items"]]
        closes = (await session.scalars(select(FinancialCloseReceipt).where(
            FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.id.in_(ids))
            .order_by(FinancialCloseReceipt.id))).all()
        plan = reopening_basis(org_id, existing.from_month, existing.snapshot["periods_before"], closes, certified)
    if plan["basis_digest"] != data.expected_basis_digest:
        raise service.AccountingError("Financial reopening basis changed; review affected periods again")
    command = FinancialReopenInput(request_key=data.request_key, reason=data.reason)
    return await reopen(session, org_id, month, command, actor, event_bus)


async def reopen(session, org_id, month, data, actor, event_bus=None):
    from modules.accounting.reopening_checks import reopening_checks

    async with reopening_checks(session):
        return await _reopen(session, org_id, month, data, actor, event_bus)


async def _reopen(session, org_id, month, data, actor, event_bus=None):
    org = await service.lock_organization(session, org_id)
    command = {"from_month": month, **data.model_dump(mode="json")}
    existing = await session.scalar(select(FinancialReopenReceipt).where(
        FinancialReopenReceipt.organization_id == org_id, FinancialReopenReceipt.request_key == str(data.request_key)))
    if existing:
        if existing.command_digest != checksum(command):
            raise service.AccountingError("Financial reopening UUID reused with different content")
        await authenticated_entries(session, org_id)
        return existing
    certified = await authenticated_entries(session, org_id)
    periods = (await session.scalars(select(Period).where(Period.organization_id == org_id, Period.month >= month)
                                    .order_by(Period.month).execution_options(populate_existing=True))).all()
    if not any(period.month == month and period.closed for period in periods):
        raise service.AccountingError("Select a closed period to reopen")
    closes = (await session.scalars(select(FinancialCloseReceipt).outerjoin(FinancialReopenItem,
        FinancialReopenItem.close_receipt_id == FinancialCloseReceipt.id).where(
        FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.month >= month,
        FinancialReopenItem.id.is_(None)).order_by(FinancialCloseReceipt.id))).all()
    before = [{"month": p.month, "generation": p.generation, "closed": p.closed} for p in periods]
    for period in periods:
        period.closed = False
        period.closed_generation = None
        period.generation += 1  # Empty months must invalidate old previews too.
        period.evidence = {}
    org.generation += 1
    await session.flush()
    items = []
    for original in closes:
        item = {"close_receipt_id": original.id, "monthly_entry_id": None, "annual_entry_id": None}
        for phase in ("annual", "monthly"):
            original_id = getattr(original, phase + "_entry_id")
            if original_id is not None:
                entry = await service.post(session, org_id, reversal_posting(certified[original_id],
                    data.request_key, original_id, data.reason), actor, event_bus, financial_transfer=True)
                item[phase + "_entry_id"] = entry.id
        items.append(item)
    receipt = FinancialReopenReceipt(organization_id=org_id, request_key=str(data.request_key), from_month=month,
        command=command, command_digest=checksum(command), actor=actor,
        snapshot={"periods_before": before, "items": items,
                  "periods_after": [{"month": p.month, "generation": p.generation, "closed": p.closed} for p in periods]}, digest="")
    receipt.digest = receipt_checksum(receipt)
    session.add(receipt)
    await session.flush()
    for item in items:
        session.add(FinancialReopenItem(reopen_receipt_id=receipt.id, **item))
    service.audit(session, org_id, actor, "financial_periods_reopened", {"receipt_id": receipt.id, "digest": receipt.digest})
    if event_bus is not None:
        event_bus.emit(session, "accounting.financial_period.reopened", {
            "organization_id": org_id, "receipt_id": receipt.id, "digest": receipt.digest})
    await session.flush()
    return receipt
