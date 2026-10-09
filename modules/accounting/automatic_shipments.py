"""Resolve sale accounts only; the native whole-act planner owns all arithmetic."""
from pydantic import Field
from sqlalchemy import select

from modules.accounting import sales, service, shipment_commands, shipment_preview
from modules.accounting.models import Policy, ShipmentAccountingReceipt
from modules.accounting.schemas import DocumentPostingPolicyInput


class AutomaticAllocation(shipment_preview.Allocation):
    expense_account: None = None


class AutomaticCommercialLine(shipment_preview.CommercialLine):
    buyer_account: None = None
    revenue_account: None = None
    vat_revenue_account: None = None
    vat_payable_account: None = None


class ShipmentAutomaticInput(shipment_preview.ShipmentPlanInput):
    allocations: list[AutomaticAllocation] = Field(min_length=1, max_length=10000)
    commercial_lines: list[AutomaticCommercialLine] = Field(min_length=1, max_length=1000)


async def validate_settings(session, org_id, on, settings):
    accounts = await service.accounts_on(session, org_id, on)
    roles = {
        "buyer_account": ("62", "asset"), "revenue_account": ("90.1", "income"),
        "vat_revenue_account": ("90.2", "income"), "vat_payable_account": ("68", "liability"),
        "expense_account": ("90.4", "expense"),
    }
    for field, (root, category) in roles.items():
        code = getattr(settings, field)
        account = accounts.get(code)
        if (account is None or not sales.belongs(code, root) or account.category != category
                or account.cash or account.quantity_tracking):
            raise service.AccountingError(f"Счёт {code} несовместим с правилом реализации: {field}")


async def effective_settings(session, org_id, on):
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == org_id, Policy.effective_from <= on,
    ).order_by(Policy.effective_from.desc()).limit(1))
    if policy is None or policy.document_posting is None:
        raise service.AccountingError("На выбранную дату не настроены автоматические счета реализации")
    settings = DocumentPostingPolicyInput.model_validate(policy.document_posting).sales
    if settings is None:
        raise service.AccountingError("На выбранную дату не настроены автоматические счета реализации")
    await validate_settings(session, org_id, on, settings)
    return policy, settings


async def options(session, org_id, on):
    policy, settings = await effective_settings(session, org_id, on)
    return {"organization_id": org_id, "policy_id": policy.id, "accounts": settings.model_dump()}


def automatic_input(command):
    raw = command.model_dump(mode="json")
    for allocation in raw["allocations"]:
        allocation.pop("expense_account")
    for line in raw["commercial_lines"]:
        for field in ("buyer_account", "revenue_account", "vat_revenue_account", "vat_payable_account"):
            line.pop(field)
    return ShipmentAutomaticInput.model_validate(raw)


async def resolve_command(session, org_id, data):
    await service.lock_organization(session, org_id)
    policy, settings = await effective_settings(session, org_id, data.posting_date)
    if policy.id != data.policy_id:
        raise service.AccountingError("Учётная политика изменилась. Повторите расчёт")
    raw = data.model_dump(mode="json", exclude_none=True)
    for allocation in raw["allocations"]:
        allocation["expense_account"] = settings.expense_account
    for line in raw["commercial_lines"]:
        line.update(settings.model_dump(exclude={"expense_account"}))
    return shipment_preview.ShipmentPlanInput.model_validate(raw)


async def prepare(session, org_id, receipt, data, *, procurement=None):
    command = await resolve_command(session, org_id, data)
    result = await shipment_preview.prepare(session, org_id, receipt, command, procurement=procurement)
    return {**result, "resolved_command": command.model_dump(mode="json")}


async def confirm(session, org_id, receipt, data, actor, event_bus=None, *, procurement=None):
    await service.lock_organization(session, org_id)
    command = shipment_preview.ShipmentPlanInput(**data.model_dump(exclude={"expected_basis_digest"}))
    source = f"wms:physical-shipment:{org_id}:{receipt['source_key']}"
    saved = await session.scalar(select(ShipmentAccountingReceipt).where(
        ShipmentAccountingReceipt.organization_id == org_id, ShipmentAccountingReceipt.source == source,
    ).with_for_update())
    if saved is None:
        resolved = await resolve_command(session, org_id, automatic_input(command))
        if resolved.model_dump() != command.model_dump():
            raise service.AccountingError("Правила счетов реализации изменились. Повторите расчёт")
    # Source authorization is performed by the route even for receipt-first replay.
    return await shipment_commands.confirm(session, org_id, receipt, command,
        data.expected_basis_digest, actor, event_bus, procurement=procurement)
