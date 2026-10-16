"""Resolve sale accounts only; the native whole-act planner owns all arithmetic."""
from pydantic import Field
from sqlalchemy import select

from modules.accounting import sales, service, shipment_commands, shipment_preview
from modules.accounting.models import Entry, Line, Policy, ShipmentAccountingReceipt
from modules.accounting.production_output_inventory import is_finished_goods_account
from modules.accounting.schemas import Code, DocumentPostingPolicyInput


class AutomaticAllocation(shipment_preview.Allocation):
    account: Code | None = None
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
    return {"organization_id": org_id, "policy_id": policy.id, "accounts": settings.model_dump(),
            "inventory_accounts": await inventory_accounts(session, org_id, policy, on)}


async def inventory_accounts(session, org_id, policy, on):
    accounts = await service.accounts_on(session, org_id, on)
    return sorted(code for code, account in accounts.items()
                  if account.category == "asset" and account.quantity_tracking and not account.cash
                  and (sales.belongs(code, "41") or
                       (sales.belongs(code, "43") and is_finished_goods_account(policy, code))))


def automatic_input(command):
    raw = command.model_dump(mode="json")
    for allocation in raw["allocations"]:
        allocation.pop("expense_account")
        allocation.pop("account")
    for line in raw["commercial_lines"]:
        for field in ("buyer_account", "revenue_account", "vat_revenue_account", "vat_payable_account"):
            line.pop(field)
    return ShipmentAutomaticInput.model_validate(raw)


async def resolve_command(session, org_id, data, receipt):
    await service.lock_organization(session, org_id)
    policy, settings = await effective_settings(session, org_id, data.posting_date)
    if policy.id != data.policy_id:
        raise service.AccountingError("Учётная политика изменилась. Повторите расчёт")
    snapshot = receipt["snapshot"]
    if snapshot["organization_id"] != org_id or receipt["digest"] != data.expected_act_digest:
        raise service.AccountingError("Physical shipment identity changed")
    physical = {row["source"]: row for row in snapshot["lines"]}
    if len(physical) != len(snapshot["lines"]):
        raise service.AccountingError("Physical shipment has duplicate lines")
    codes = await inventory_accounts(session, org_id, policy, data.posting_date)
    raw = data.model_dump(mode="json", exclude_none=True)
    resolved = {}
    for allocation in raw["allocations"]:
        row = physical.get(allocation["line_source"])
        if row is None:
            raise service.AccountingError("Allocation references a foreign physical line")
        key = (row["warehouse"], row["sku_code"], allocation["lot"])
        if key not in resolved:
            # Discover only the account. The native planner still authenticates
            # the cost layer and quantities before making a posting available.
            candidates = (await session.scalars(select(Line.account_code).join(Entry, Line.entry_id == Entry.id).where(
                Entry.organization_id == org_id, Entry.posting_date <= data.posting_date,
                Line.account_code.in_(codes), Line.dimensions["warehouse"].as_string() == key[0],
                Line.dimensions["sku"].as_string() == key[1], Line.dimensions["lot"].as_string() == key[2],
            ).distinct().limit(2))).all()
            if len(candidates) != 1:
                raise service.AccountingError("Не удалось однозначно определить счёт запасов по складу, товару и партии. Сверьте историю партии")
            resolved[key] = candidates[0]
        account = resolved[key]
        if allocation.get("account", account) != account:
            raise service.AccountingError("Переданный счёт запасов не соответствует учтённой партии")
        allocation["account"] = account
        allocation["expense_account"] = settings.expense_account
    for line in raw["commercial_lines"]:
        line.update(settings.model_dump(exclude={"expense_account"}))
    return shipment_preview.ShipmentPlanInput.model_validate(raw)


async def prepare(session, org_id, receipt, data, *, procurement=None):
    command = await resolve_command(session, org_id, data, receipt)
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
        resolved = await resolve_command(session, org_id, automatic_input(command), receipt)
        if resolved.model_dump() != command.model_dump():
            raise service.AccountingError("Правила счетов реализации изменились. Повторите расчёт")
    # Source authorization is performed by the route even for receipt-first replay.
    return await shipment_commands.confirm(session, org_id, receipt, command,
        data.expected_basis_digest, actor, event_bus, procurement=procurement)
