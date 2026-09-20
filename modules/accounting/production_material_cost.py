"""Reviewed material-to-WIP basis for a production order.

The accounting inventory cost layer remains the source of monetary value and
WMS remains the source of the physical issue.  This module joins exact facts
for accountant review; it never turns a warehouse movement or a lot estimate
into a posting by itself.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from pydantic import Field
from sqlalchemy import select, text

from modules.accounting import inventory_cost, inventory_issues, service
from modules.accounting.models import Policy
from modules.accounting.production_cost_policy import validate_accounts
from modules.accounting.schemas import (
    Code,
    Input,
    InventoryIssueDocument,
    InventoryIssuePreviewInput,
    ProductionCostPolicyInput,
    Quantity,
)
from modules.accounting.service import AccountingError, lock_organization
from modules.wms.models import StockMovement
from modules.wms.production_material_issues import ProductionMaterialIssue


class ProductionMaterialIssuePreviewInput(Input):
    policy_id: int = Field(gt=0, strict=True)
    order_id: int = Field(gt=0, strict=True)
    order_analytics: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=200)
    wms_movement_id: int = Field(gt=0, strict=True)
    posting_date: date
    account: Code
    warehouse: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=200)
    lot: str = Field(min_length=1, max_length=200)
    quantity: Quantity


class ProductionMaterialIssuePostingInput(ProductionMaterialIssuePreviewInput):

    pass


class ProductionMaterialIssuePostingConfirmInput(ProductionMaterialIssuePostingInput):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _line(account: str, side: str, amount: str, dimensions: dict[str, str], quantity=None):
    result = {"account": account, "side": side, "amount_byn": amount, "dimensions": dimensions}
    if quantity is not None:
        result["quantity"] = quantity
    return result


async def prepare_material_issue_posting(session, org_id: int, month: str,
                                          data: ProductionMaterialIssuePostingInput,
                                          production, procurement=None):
    review = await preview_material_issue(session, org_id, month, data, production, procurement=procurement)
    _, _, policy, settings = await _load_policy(session, org_id, month, data, current=True)
    _, _, binding, _ = await _load_source(session, org_id, month, data)
    document = material_issue_document(org_id, data, policy, settings, binding)
    cost, posting = await inventory_issues.prepare(
        session, org_id, document, procurement=procurement, allow_production_material=True,
        source_allocations=await _material_source_allocations(session, policy))
    if cost["basis_digest"] != review["inventory_cost"]["basis_digest"]:
        raise AccountingError("Inventory cost basis changed while preparing the material posting")
    return {
        **review,
        "posting_document": document.model_dump(mode="json"),
        "posting": posting.model_dump(mode="json"),
        "basis_digest": cost["basis_digest"],
        "digest": service.digest(posting),
        "posting_available": True,
        "final_cost_certified": False,
    }


async def confirm_material_issue_posting(session, org_id: int, month: str,
                                          data: ProductionMaterialIssuePostingConfirmInput,
                                          actor, event_bus=None, procurement=None):
    _, _, policy, settings = await _load_policy(session, org_id, month, data, current=False)
    _, _, binding, _ = await _load_source(session, org_id, month, data)
    document = material_issue_document(org_id, data, policy, settings, binding)
    return await inventory_issues.confirm(
        session, org_id, document, data.basis_digest, data.digest, actor, event_bus,
        procurement=procurement, allow_production_material=True,
        # ``inventory_issues.confirm`` checks a saved receipt before preparing
        # a new one.  Keep legacy FIFO/weighted retries reachable; new postings
        # still fail closed in ``prepare`` without migration 0149.
        source_allocations=policy.inventory_method in {"fifo", "weighted_average"})


async def _material_source_allocations(session, policy: Policy) -> bool:
    if policy.inventory_method not in {"fifo", "weighted_average"}:
        return False
    present = session.get_bind().dialect.name == "postgresql" and await session.scalar(text(
        "SELECT to_regprocedure('accounting.production_material_allocation_version()') IS NOT NULL"
    )) is True
    ready = present and await session.scalar(text(
        "SELECT accounting.production_material_allocation_version()"
    )) == 1
    if not ready:
        raise AccountingError("Production material allocation requires PostgreSQL migration 0149")
    return True


async def _load_source(session, org_id: int, month: str, data: ProductionMaterialIssuePreviewInput):
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    if data.posting_date < first or data.posting_date > last:
        raise AccountingError("Material issue date must belong to the selected period")
    binding = await session.scalar(select(ProductionMaterialIssue).where(
        ProductionMaterialIssue.id > 0,
        ProductionMaterialIssue.organization_id == org_id,
        ProductionMaterialIssue.order_id == data.order_id,
        ProductionMaterialIssue.movement_id == data.wms_movement_id,
    ).with_for_update().execution_options(populate_existing=True))
    if binding is None:
        raise AccountingError("WMS material issue source binding is required")
    if binding.operation_date < first or binding.operation_date > last:
        raise AccountingError("Production material issue date must belong to the selected period")
    snapshot = binding.snapshot if isinstance(binding.snapshot, dict) else None
    command_snapshot = snapshot.get("command") if snapshot else None
    movement_snapshot = snapshot.get("movement") if snapshot else None
    if not isinstance(command_snapshot, dict) or not isinstance(movement_snapshot, dict):
        raise AccountingError("WMS material issue source binding is corrupt")
    expected_command = {
        "order_id": data.order_id,
        "operation_date": binding.operation_date.isoformat(),
        "sku_code": data.sku,
        "quantity": format(data.quantity, ".2f"),
        "warehouse": data.warehouse,
        "lot": data.lot,
    }
    if any(command_snapshot.get(key) != value for key, value in expected_command.items()):
        raise AccountingError("WMS material issue source binding does not match the review request")
    movement = await session.scalar(select(StockMovement).where(
        StockMovement.id == data.wms_movement_id,
        StockMovement.organization_id == org_id,
    ).with_for_update().execution_options(populate_existing=True))
    if movement is None:
        raise AccountingError("WMS material issue is not found in this organization")
    expected_source = f"production_material:{command_snapshot.get('request_id', '')}"
    expected_movement = {
        "id": movement.id,
        "organization_id": movement.organization_id,
        "sku_code": movement.sku_code,
        "warehouse": movement.warehouse,
        "kind": movement.kind,
        "qty": format(movement.qty, ".2f"),
        "reason": movement.reason,
        "location_id": movement.location_id,
        "lot": movement.batch_ref,
        "doc_ref": movement.doc_ref,
    }
    if any(movement_snapshot.get(key) != value for key, value in expected_movement.items()):
        raise AccountingError("WMS material issue source binding does not match the physical movement")
    if movement.doc_ref != expected_source or not command_snapshot.get("request_id"):
        raise AccountingError("WMS material issue source binding has an invalid source reference")
    if (movement.kind != "out" or movement.reason != "production_issue"
            or movement.sku_code != data.sku or movement.warehouse != data.warehouse
            or movement.batch_ref != data.lot or movement.qty != data.quantity):
        raise AccountingError("WMS movement is not an exact production material issue")
    return first, last, binding, movement


async def _load_policy(session, org_id: int, month: str, data: ProductionMaterialIssuePreviewInput,
                       *, current: bool):
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    if current:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.effective_from <= last,
        ).order_by(Policy.effective_from.desc()))
        if policy is None or policy.id != data.policy_id or policy.effective_from > first:
            raise AccountingError("Select one applicable production policy for the whole reviewed month")
    else:
        policy = await session.scalar(select(Policy).where(
            Policy.organization_id == org_id, Policy.id == data.policy_id,
        ))
        if policy is None:
            raise AccountingError("The saved production policy is not available for this source")
    if policy.production_costing is None:
        raise AccountingError("Production cost configuration is required")
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    await validate_accounts(session, org_id, last, settings)
    return first, last, policy, settings


def material_issue_document(org_id: int, data: ProductionMaterialIssuePreviewInput,
                            policy: Policy, settings: ProductionCostPolicyInput,
                            binding: ProductionMaterialIssue):
    operation_date = binding.operation_date
    dimensions = {"department": data.department.strip(), settings.order_dimension: data.order_analytics.strip()}
    return InventoryIssueDocument(
        source=f"production:material:{org_id}:{binding.request_key}", source_version=1,
        document_date=operation_date, operation_date=operation_date,
        posting_date=data.posting_date, policy_id=policy.id, account=data.account,
        warehouse=data.warehouse, sku=data.sku, lot=data.lot, quantity=data.quantity,
        expense_account=settings.wip_account, expense_dimensions=dimensions,
        explanation=f"Списание материала в НЗП по наряду {data.order_id}; {data.department.strip()}",
    )


def material_zero_binding(binding: ProductionMaterialIssue, movement: StockMovement, data: ProductionMaterialIssuePreviewInput):
    """Frozen WMS identity carried by the V5 receipt, never inferred at replay."""
    return {"binding_id": binding.id, "order_id": binding.order_id, "movement_id": movement.id,
            "request_key": binding.request_key, "warehouse": data.warehouse, "sku": data.sku,
            "lot": data.lot, "quantity": format(data.quantity, ".6f")}


async def verify_material_zero_binding(session, organization_id: int, command):
    """Re-authenticate a V5 command against immutable WMS facts for replay."""
    from modules.accounting.zero_value_disposals import ProductionMaterialZeroValueDisposalCommand
    if not isinstance(command, ProductionMaterialZeroValueDisposalCommand):
        raise AccountingError("Material zero receipt has an invalid command type")
    b = command.material_binding
    policy = await session.scalar(select(Policy).where(
        Policy.organization_id == organization_id, Policy.id == command.policy_id))
    if policy is None or policy.production_costing is None:
        raise AccountingError("Material zero receipt production policy is unavailable")
    settings = ProductionCostPolicyInput.model_validate(policy.production_costing)
    data = ProductionMaterialIssuePreviewInput(
        policy_id=command.policy_id, order_id=b["order_id"],
        order_analytics=command.destination_dimensions.get(settings.order_dimension, ""),
        department=command.destination_dimensions.get("department", ""), wms_movement_id=b["movement_id"],
        posting_date=command.posting_date, account=command.document["account"],
        warehouse=command.document["warehouse"], sku=command.document["sku"],
        lot=command.document["lot"], quantity=command.document["quantity"],
    )
    month = command.posting_date.strftime("%Y-%m")
    await _load_policy(session, organization_id, month, data, current=False)
    _, _, binding, movement = await _load_source(session, organization_id, month, data)
    expected = material_issue_document(organization_id, data, policy, settings, binding)
    if (b != material_zero_binding(binding, movement, data)
            or command.document != expected.model_dump(mode="json")):
        raise AccountingError("Material zero receipt is not bound to its reviewed WMS source")


async def preview_material_issue(session, org_id: int, month: str,
                                 data: ProductionMaterialIssuePreviewInput,
                                 production, procurement=None):
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=monthrange(first.year, first.month)[1])
    if data.posting_date < first or data.posting_date > last:
        raise AccountingError("Material issue date must belong to the selected period")
    if production is None:
        raise AccountingError("Production order verification service is unavailable")
    await lock_organization(session, org_id)
    _, last, policy, settings = await _load_policy(session, org_id, month, data, current=True)
    _, _, binding, movement = await _load_source(session, org_id, month, data)

    orders = await production.cost_orders(session, org_id, [data.order_id])
    if len(orders) != 1:
        raise AccountingError("Production order verification returned an unexpected result")
    cost_request = InventoryIssuePreviewInput(
        policy_id=data.policy_id, posting_date=data.posting_date, account=data.account,
        warehouse=data.warehouse, sku=data.sku, lot=data.lot, quantity=data.quantity,
    )
    cost = await inventory_cost.preview_issue(
        session, org_id, cost_request, procurement=procurement,
        source_allocations=await _material_source_allocations(session, policy),
    )
    amount = cost["issue_cost_byn"]
    wip_dimensions = {"department": data.department.strip(), settings.order_dimension: data.order_analytics.strip()}
    result = {
        "organization_id": org_id,
        "month": month,
        "policy_id": policy.id,
        "order": orders[0],
        "order_analytics": data.order_analytics.strip(),
        "department": data.department.strip(),
        "wms_movement": {"id": movement.id, "sku": movement.sku_code, "warehouse": movement.warehouse,
                          "lot": movement.batch_ref, "quantity": format(movement.qty, ".6f"),
                          "reason": movement.reason, "doc_ref": movement.doc_ref},
        "wms_source_binding": {"id": binding.id, "order_id": binding.order_id,
                                "movement_id": binding.movement_id,
                                "operation_date": binding.operation_date.isoformat(),
                                "request_key": binding.request_key},
        "inventory_cost": cost,
        "candidate_posting": {
            "debit": _line(settings.wip_account, "debit", amount, wip_dimensions),
            "credit": _line(data.account, "credit", amount, cost["inventory_dimensions"], format(data.quantity, ".6f")),
        },
        "status": "reviewed_material_cost",
        "explanation": "Стоимость партии подтверждена по бухгалтерскому слою, физическое списание подтверждено WMS; проводка НЗП требует отдельного подтверждения.",
        "posting_available": False,
        "final_cost_certified": False,
        "scope": "production_material_cost_basis",
    }
    return result


async def prepare_material_zero_issue(session, org_id: int, month: str, data: ProductionMaterialIssuePostingInput,
                                      production, procurement=None):
    """Prepare the typed V5 receipt; callers must not present it as an Entry."""
    from modules.accounting.zero_value_disposals import (
        ProductionMaterialZeroValueDisposalCommand,
        canonical_json,
    )
    present = session.get_bind().dialect.name == "postgresql" and await session.scalar(text(
        "SELECT to_regprocedure('accounting.production_material_zero_allocation_version()') IS NOT NULL"
    )) is True
    if not present or await session.scalar(text(
        "SELECT accounting.production_material_zero_allocation_version()"
    )) != 5:
        raise AccountingError("Zero-value production materials require PostgreSQL migration 0150")
    review = await preview_material_issue(session, org_id, month, data, production, procurement=procurement)
    if review["inventory_cost"]["issue_cost_byn"] != "0.00":
        raise AccountingError("Material zero receipt is only valid for an all-zero allocation")
    _, _, policy, settings = await _load_policy(session, org_id, month, data, current=True)
    _, _, binding, movement = await _load_source(session, org_id, month, data)
    document = material_issue_document(org_id, data, policy, settings, binding)
    cost = review["inventory_cost"]
    command = ProductionMaterialZeroValueDisposalCommand(
        command_version=5, operation="inventory_issue", source=document.source, source_version=document.source_version,
        posting_date=document.posting_date, document_date=document.document_date, operation_date=document.operation_date,
        policy_id=document.policy_id, basis_digest="0" * 64, destination_account=document.expense_account,
        destination_dimensions=document.expense_dimensions, explanation=document.explanation,
        valuation_method=policy.inventory_method, document=document.model_dump(mode="json"),
        material_binding=material_zero_binding(binding, movement, data),
        inventory_layers=[{"source_entry_id": layer["source_entry_id"], "source_line_id": layer["source_line_id"],
                           "inventory_account": document.account, "inventory_dimensions": layer["dimensions"],
                           "quantity": layer["quantity"]} for layer in cost["inventory_layers"]],
    )
    basis = await session.scalar(text("SELECT accounting.zero_value_material_allocation_basis(:org,CAST(:command AS jsonb),2147483647)"),
        {"org": org_id, "command": canonical_json(command.model_dump(mode="json"))})
    if not isinstance(basis, str) or len(basis) != 64:
        raise AccountingError("Material zero allocation basis is unavailable")
    command = command.model_copy(update={"basis_digest": basis})
    return {**review, "zero_value_receipt": command.model_dump(mode="json"), "basis_digest": basis,
            "digest": service.digest(command),
            "posting_available": False, "quantity_registered": False, "entry_id": None}


async def confirm_material_zero_issue(session, org_id: int, month: str, data: ProductionMaterialIssuePostingConfirmInput,
                                      actor, production, procurement=None):
    from modules.accounting.models import ZeroValueInventoryDisposalReceipt
    from modules.accounting.zero_value_disposals import (
        ProductionMaterialZeroValueDisposalCommand,
        register_standalone_zero_value_issue,
    )
    await lock_organization(session, org_id)
    _, _, policy, settings = await _load_policy(session, org_id, month, data, current=False)
    _, _, binding, _ = await _load_source(session, org_id, month, data)
    document = material_issue_document(org_id, data, policy, settings, binding)
    existing = await session.scalar(select(ZeroValueInventoryDisposalReceipt).where(
        ZeroValueInventoryDisposalReceipt.organization_id == org_id,
        ZeroValueInventoryDisposalReceipt.source == document.source,
        ZeroValueInventoryDisposalReceipt.source_version == document.source_version,
        ZeroValueInventoryDisposalReceipt.operation == "inventory_issue",
    ))
    if existing is not None:
        command = ProductionMaterialZeroValueDisposalCommand.model_validate(existing.command)
        if command.document != document.model_dump(mode="json"):
            raise AccountingError("Material zero source was already registered with different content")
    else:
        prepared = await prepare_material_zero_issue(session, org_id, month, data, production, procurement=procurement)
        command = ProductionMaterialZeroValueDisposalCommand.model_validate(prepared["zero_value_receipt"])
    if command.basis_digest != data.basis_digest or data.digest != service.digest(command):
        raise AccountingError("Material zero receipt confirmation differs from its review")
    receipt = await register_standalone_zero_value_issue(session, org_id, actor, command)
    return {"receipt_id": receipt.id, "entry_id": None, "posted": False, "quantity_registered": True,
            "basis_digest": receipt.basis_digest, "digest": receipt.digest}
