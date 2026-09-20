"""Public adapter for the deliberately narrow entryless zero-value issue."""
from decimal import Decimal

from sqlalchemy import select

from modules.accounting import inventory_cost, inventory_issues, service
from modules.accounting.models import Account, Line, Policy, ZeroValueInventoryDisposalReceipt
from modules.accounting.production_output_inventory import verified_output_lines
from modules.accounting.schemas import SpecificZeroValueIssueDocument
from modules.accounting.zero_value_disposals import (
    DatedZeroValueDisposalCommand,
    ZeroValueInventoryLayer,
    preview_standalone_zero_value_issue_basis,
    receipt_digest,
    register_standalone_zero_value_issue,
    require_public_zero_value_schema,
)


async def _command(session, organization_id, document):
    inventory_issues._guard_production_material_source(document, False)
    await require_public_zero_value_schema(session)
    policy = await session.get(Policy, document.policy_id)
    if policy is None or policy.organization_id != organization_id or policy.inventory_method != "specific":
        raise service.AccountingError("Zero-value issue supports the active specific-cost policy only")
    target = {"warehouse": document.warehouse, "sku": document.sku, "lot": document.lot}
    verified = await verified_output_lines(
        session, organization_id, policy, document.account, document.posting_date, target,
    )
    source = await session.scalar(select(Line).where(Line.id == document.source_line_id))
    if (source is None or source.entry_id != document.source_entry_id
            or (source.entry_id, source.id) not in verified
            or source.account_code != document.account or (source.dimensions or {}) != target):
        raise service.AccountingError("Zero-value issue requires one verified production-output source layer")
    cost = await inventory_cost.preview_issue(session, organization_id, document)
    if Decimal(cost["issue_cost_byn"]) != 0:
        raise service.AccountingError("Selected source layer is not a zero-cost remaining layer")
    expense = await session.scalar(select(Account).where(
        Account.organization_id == organization_id, Account.code == document.expense_account,
        Account.valid_from <= document.posting_date,
    ).order_by(Account.valid_from.desc()).limit(1))
    if expense is None or expense.cash or expense.quantity_tracking or expense.category != "expense":
        raise service.AccountingError("Select a noncash expense account without quantity tracking")
    command = DatedZeroValueDisposalCommand(
        command_version=2, operation="inventory_issue", source=document.source,
        source_version=document.source_version, posting_date=document.posting_date,
        policy_id=document.policy_id, basis_digest="0" * 64,
        destination_account=document.expense_account, destination_dimensions=document.expense_dimensions,
        inventory_layers=[ZeroValueInventoryLayer(source_entry_id=document.source_entry_id,
            source_line_id=document.source_line_id, inventory_account=document.account,
            inventory_dimensions=target, quantity=document.quantity)], explanation=document.explanation,
        document_date=document.document_date, operation_date=document.operation_date,
    )
    basis = await preview_standalone_zero_value_issue_basis(session, organization_id, command)
    return command.model_copy(update={"basis_digest": basis}), cost


async def preview(session, organization_id, document, actor):
    command, cost = await _command(session, organization_id, document)
    layer, = command.inventory_layers
    cost = {**cost, "valuation_basis_digest": cost["basis_digest"], "basis_digest": command.basis_digest}
    return {"kind": "quantity_only_receipt", "posting": None, "cost": cost,
            "basis_digest": command.basis_digest, "digest": receipt_digest(organization_id, actor, command),
            "receipt": {"source_layer": {"entry_id": layer.source_entry_id, "line_id": layer.source_line_id,
                        "quantity": format(layer.quantity, ".6f")}, "zero_byn": True},
            "command": command.model_dump(mode="json"), "confirmation_available": True, "posted": False}


async def implicit_document(session, organization_id, document, *, procurement=None):
    """Select the sole verified origin; browser clients never submit ledger IDs."""
    inventory_issues._guard_production_material_source(document, False)
    cost = await inventory_cost.preview_issue(session, organization_id, document, procurement=procurement)
    if Decimal(cost["issue_cost_byn"]) != 0:
        return None
    policy = await session.get(Policy, document.policy_id)
    if policy is None or policy.inventory_method != "specific":
        raise service.AccountingError("Zero-value issue supports the active specific-cost policy only")
    target = {"warehouse": document.warehouse, "sku": document.sku, "lot": document.lot}
    verified = await verified_output_lines(session, organization_id, policy, document.account, document.posting_date, target)
    candidates = [(item["entry_id"], item["line_id"]) for item in cost["evidence"]
                  if item.get("side") == "debit" and (item["entry_id"], item["line_id"]) in verified]
    if len(candidates) != 1:
        raise service.AccountingError("Zero-value issue requires one verified production-output source layer")
    return SpecificZeroValueIssueDocument(**document.model_dump(), source_entry_id=candidates[0][0], source_line_id=candidates[0][1])


async def implicit_confirm(session, organization_id, document, basis_digest, digest, actor, *, procurement=None):
    await service.lock_organization(session, organization_id)
    existing = await session.scalar(select(ZeroValueInventoryDisposalReceipt).where(
        ZeroValueInventoryDisposalReceipt.organization_id == organization_id,
        ZeroValueInventoryDisposalReceipt.source == document.source,
        ZeroValueInventoryDisposalReceipt.source_version == document.source_version,
        ZeroValueInventoryDisposalReceipt.operation == "inventory_issue",
    ))
    if existing is not None:
        saved = DatedZeroValueDisposalCommand.model_validate(existing.command)
        layer, = saved.inventory_layers
        explicit = SpecificZeroValueIssueDocument(**document.model_dump(), source_entry_id=layer.source_entry_id,
                                                  source_line_id=layer.source_line_id)
    else:
        explicit = await implicit_document(session, organization_id, document, procurement=procurement)
        if explicit is None:
            return None
    return await confirm(session, organization_id, explicit, basis_digest, digest, actor)


async def confirm(session, organization_id, document, basis_digest, digest, actor):
    await service.lock_organization(session, organization_id)
    existing = await session.scalar(select(ZeroValueInventoryDisposalReceipt).where(
        ZeroValueInventoryDisposalReceipt.organization_id == organization_id,
        ZeroValueInventoryDisposalReceipt.source == document.source,
        ZeroValueInventoryDisposalReceipt.source_version == document.source_version,
        ZeroValueInventoryDisposalReceipt.operation == "inventory_issue",
    ))
    if existing is not None:
        saved = DatedZeroValueDisposalCommand.model_validate(existing.command)
        layer, = saved.inventory_layers
        unchanged = (
            existing.actor == actor and existing.basis_digest == basis_digest and existing.digest == digest
            and saved.document_date == document.document_date and saved.operation_date == document.operation_date
            and saved.posting_date == document.posting_date and saved.policy_id == document.policy_id
            and saved.destination_account == document.expense_account
            and saved.destination_dimensions == document.expense_dimensions and saved.explanation == document.explanation
            and layer.source_entry_id == document.source_entry_id and layer.source_line_id == document.source_line_id
            and layer.inventory_account == document.account and layer.inventory_dimensions == {
                "warehouse": document.warehouse, "sku": document.sku, "lot": document.lot,
            } and layer.quantity == document.quantity
        )
        if not unchanged:
            raise service.AccountingError("Zero-value issue already registered with different content")
        return {"kind": "quantity_only_receipt", "posting": None,
                "cost": {"issue_cost_byn": "0.00", "issue_quantity": format(document.quantity, ".6f")},
                "receipt_id": existing.id, "registration_token": existing.registration_token,
                "basis_digest": existing.basis_digest, "digest": existing.digest, "posted": True}
    command, cost = await _command(session, organization_id, document)
    expected_digest = receipt_digest(organization_id, actor, command)
    if command.basis_digest != basis_digest or expected_digest != digest:
        raise service.AccountingError("Zero-value issue basis or document changed; preview again")
    receipt = await register_standalone_zero_value_issue(session, organization_id, actor, command)
    return {"kind": "quantity_only_receipt", "posting": None, "cost": cost,
            "receipt_id": receipt.id, "registration_token": receipt.registration_token,
            "basis_digest": command.basis_digest, "digest": expected_digest, "posted": True}
