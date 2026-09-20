"""Internal atomic late-cost command; public authorization belongs to its caller."""
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from modules.accounting import service
from modules.accounting.late_cost_posting import candidate
from modules.accounting.late_cost_preview import preview
from modules.accounting.late_cost_receipts import LateCostCommand, verify_receipt
from modules.accounting.models import LateCostReceipt, SourceControl


class LateCostConfirmation(LateCostCommand):
    request_key: UUID
    expected_basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


async def prepare(session, organization_id, expense_id, command, procurement):
    calculated = await preview(session, organization_id, expense_id, command.allocation, procurement)
    posting = candidate(calculated, command.accounts)
    accounts, _ = await service.validate_posting(session, organization_id, posting, late_cost=True)
    validate_account_roles(posting, accounts)
    return calculated, posting


def validate_account_roles(posting, accounts, *, material=False):
    """Keep settlement, expense and inventory semantics shared by both writers."""
    for line in posting.lines:
        account = accounts[line.account]
        root = line.account.split(".")[0]
        asset_roots = {"10", "41", "18", "20"} if material else {"10", "41", "18"}
        category = "asset" if root in asset_roots else "liability" if root == "60" else "expense"
        if account.category != category or account.cash or account.quantity_tracking != (root in {"10", "41"}):
            raise service.AccountingError("Late-cost account role or quantity tracking is inconsistent")


async def confirm(session, organization_id, expense_id, command: LateCostCommand, request_key: UUID,
                  expected_basis_digest, expected_digest, actor, procurement, event_bus=None):
    """Caller owns transaction; all writes roll back together on any failure."""
    await service.lock_organization(session, organization_id)
    saved = await session.scalar(select(LateCostReceipt).where(
        LateCostReceipt.organization_id == organization_id,
        (LateCostReceipt.expense_id == expense_id) | (LateCostReceipt.request_key == str(request_key))))
    if saved is not None:
        if (saved.expense_id != expense_id or saved.request_key != str(request_key) or saved.actor != actor
            or saved.command != command.model_dump(mode="json") or saved.digest != expected_digest
            or saved.calculation["basis_digest"] != expected_basis_digest):
            raise service.AccountingError("Late-cost command conflicts with the saved receipt")
        await verify_receipt(session, organization_id, saved.entry_id, procurement)
        return saved
    calculated, posting = await prepare(session, organization_id, expense_id, command, procurement)
    if calculated["basis_digest"] != expected_basis_digest or service.digest(posting) != expected_digest:
        raise service.AccountingError("Late-cost basis changed; preview again")
    control = await session.scalar(select(SourceControl).where(SourceControl.organization_id == organization_id,
        SourceControl.source == posting.source))
    if control is None or control.version != posting.source_version or control.entry_id is not None:
        raise service.AccountingError("Late-cost primary completeness state is inconsistent")
    entry = await service.post(session, organization_id, posting, actor, event_bus, late_cost=True)
    saved = LateCostReceipt(entry_id=entry.id, organization_id=organization_id, expense_id=expense_id,
        source_version=posting.source_version, request_key=str(request_key), command=command.model_dump(mode="json"),
        calculation=calculated, posting=posting.model_dump(mode="json"), digest=service.digest(posting), actor=actor)
    session.add(saved)
    await session.flush()
    control.entry_id = entry.id
    await session.flush()
    await verify_receipt(session, organization_id, entry.id, procurement)
    return saved
