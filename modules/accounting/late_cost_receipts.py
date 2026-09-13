"""Reproduce a saved late-cost receipt from its original authenticated history."""
from modules.accounting import service
from modules.accounting.closing_commands import actual_posting
from modules.accounting.late_cost_posting import ExpenseAccounts, candidate
from modules.accounting.late_cost_preview import calculate, validate_currency
from modules.accounting.late_cost_sources import expense_history
from modules.accounting.models import Entry, LateCostReceipt, Policy
from modules.accounting.schemas import Input, LateCostPreviewInput, PostingInput


class LateCostCommand(Input):
    allocation: LateCostPreviewInput
    accounts: ExpenseAccounts


async def verified_value_lines(session, organization_id, rows, procurement):
    """Authenticate every value-only line before allowing it into costing."""
    candidates = [(entry, line) for entry, line in rows if line.quantity is None]
    if not candidates:
        return frozenset()
    if procurement is None:
        raise service.AccountingError("Cost adjustments require the procurement source gateway")
    for entry_id in sorted({entry.id for entry, _ in candidates}):
        await verify_receipt(session, organization_id, entry_id, procurement)
    return frozenset((entry.id, line.id) for entry, line in candidates)


async def verify_receipt(session, organization_id, entry_id, procurement):
    """Caller authorizes organization access; no current-period recalculation."""
    await service.lock_organization(session, organization_id)
    saved = await session.get(LateCostReceipt, entry_id)
    entry = await session.get(Entry, entry_id)
    if (saved is None or entry is None or saved.organization_id != organization_id
        or entry.organization_id != organization_id):
        raise service.AccountingError("Late cost has no matching source receipt")
    command = LateCostCommand.model_validate(saved.command)
    policy = await session.get(Policy, command.allocation.policy_id)
    if (policy is None or policy.organization_id != organization_id
        or policy.inventory_method not in {"specific", "fifo", "weighted_average"}
        or policy.effective_from > entry.posting_date or command.allocation.expected_version != saved.source_version):
        raise service.AccountingError("Late cost policy or source version is inconsistent")
    history = await expense_history(session, organization_id, saved.expense_id, saved.source_version,
        command.allocation.posting_date, procurement, before_entry_id=entry_id)
    await validate_currency(session, history["document"]["currency"], command.allocation)
    calculated = calculate(organization_id, saved.expense_id, command.allocation, policy, history)
    expected = candidate(calculated, command.accounts)
    if (calculated != saved.calculation or PostingInput.model_validate(saved.posting).model_dump() != expected.model_dump()
        or service.digest(expected) != saved.digest or entry.digest != saved.digest or entry.actor != saved.actor
        or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise service.AccountingError("Late cost source, calculation or ledger package changed")
    return expected
