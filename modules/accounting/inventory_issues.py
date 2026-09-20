"""Explicit accountant issue document; warehouse movement remains separate."""
import hashlib
import json
from decimal import Decimal

from sqlalchemy import select, text

from modules.accounting import inventory_cost, service
from modules.accounting.models import Entry, InventoryIssueReceipt, Line, Policy
from modules.accounting.schemas import (
    InventoryIssueDocument,
    InventoryIssuePreviewInput,
    LineInput,
    PostingInput,
)
from modules.accounting.zero_value_disposals import InventoryDispositionAllocation


def rule_version(document, basis_digest, *, allocation_version=None):
    raw = json.dumps({"document": document.model_dump(mode="json"), "basis": basis_digest}, sort_keys=True, ensure_ascii=False)
    if allocation_version is None:
        return "inventory-issue-v2:" + hashlib.sha256(raw.encode()).hexdigest()
    if type(allocation_version) is not int or allocation_version != 1:
        raise service.AccountingError("Explicit allocation version must be integer 1")
    return "inventory-issue-v2:" + hashlib.sha256(raw.encode()).hexdigest() + ":a1"


def explicit_allocation(document, cost):
    """Validate the complete opt-in packet before filtering zero money lines."""
    if "source_allocation_version" not in cost:
        return None
    version = cost["source_allocation_version"]
    if type(version) is not int or version != 1 or cost.get("method") not in {"fifo", "weighted_average"}:
        raise service.AccountingError("Explicit allocation marker or method is invalid")
    try:
        allocation = InventoryDispositionAllocation.model_validate({
            "allocation_version": version, "valuation_method": cost["method"],
            "quantity": cost["issue_quantity"], "amount_byn": cost["issue_cost_byn"],
            "layers": [{"source_entry_id": layer["source_entry_id"], "source_line_id": layer["source_line_id"],
                        "inventory_account": document.account, "inventory_dimensions": layer["dimensions"],
                        "quantity": layer["quantity"], "amount_byn": layer["amount_byn"]}
                       for layer in cost["inventory_layers"]],
        })
    except (KeyError, TypeError, ValueError) as error:
        raise service.AccountingError("Explicit allocation packet is invalid") from error
    if allocation.quantity != document.quantity or allocation.amount_byn <= 0:
        raise service.AccountingError("Explicit allocation quantity or cost is invalid")
    for layer in allocation.layers:
        dimensions = layer.inventory_dimensions
        if (layer.inventory_account != document.account or dimensions.get("warehouse") != document.warehouse
                or dimensions.get("sku") != document.sku or document.lot and dimensions.get("lot") != document.lot
                or layer.amount_byn < 0):
            raise service.AccountingError("Explicit allocation inventory identity is invalid")
    return allocation


async def prepare(session, org_id, document, *, procurement=None, allow_production_material=False,
                  source_allocations=False):
    _guard_production_material_source(document, allow_production_material)
    zero_schema = document.source.startswith("production:material:") and session.get_bind().dialect.name == "postgresql" and await session.scalar(text(
        "SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt') IS NOT NULL"
    )) is True
    if zero_schema:
        from modules.accounting.models import ZeroValueInventoryDisposalReceipt
        conflict = await session.scalar(select(ZeroValueInventoryDisposalReceipt.id).where(
            ZeroValueInventoryDisposalReceipt.organization_id == org_id,
            ZeroValueInventoryDisposalReceipt.source == document.source,
            ZeroValueInventoryDisposalReceipt.source_version == document.source_version,
            ZeroValueInventoryDisposalReceipt.operation == "inventory_issue",
        ).limit(1))
        if conflict is not None:
            raise service.AccountingError("Material source identity is already reserved by a zero-value receipt")
    if source_allocations and allow_production_material:
        material_present = session.get_bind().dialect.name == "postgresql" and await session.scalar(text(
            "SELECT to_regprocedure('accounting.production_material_allocation_version()') IS NOT NULL"
        )) is True
        material_ready = material_present and await session.scalar(text(
            "SELECT accounting.production_material_allocation_version()"
        )) == 1
        if material_ready is not True:
            raise service.AccountingError("Production material allocation requires PostgreSQL migration 0149")
    cost_request = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
    guarded_allocations = source_allocations and session.get_bind().dialect.name == "postgresql" and bool(await session.scalar(text(
        "SELECT to_regprocedure('accounting.validate_inventory_allocation_link(integer)') IS NOT NULL "
        "AND to_regprocedure('accounting.inventory_allocation_cost_stream(integer,text,text,text,date,integer)') IS NOT NULL"
    )))
    cost = await inventory_cost.preview_issue(session, org_id, cost_request, procurement=procurement,
                                              source_allocations=guarded_allocations)
    # Existing positive monetary documents retain their legacy format before
    # rollout. A zero portion must never be dropped without its guarded receipt.
    if source_allocations and not guarded_allocations and cost["method"] in {"fifo", "weighted_average"} and any(
        Decimal(layer["amount_byn"]) <= 0 for layer in cost["inventory_layers"]
    ):
        raise service.AccountingError("Explicit inventory allocation requires PostgreSQL migrations 0144 and 0145")
    posting = posting_for(document, cost)
    accounts, _ = await service.validate_posting(session, org_id, posting, inventory_issue=True)
    inventory = accounts[document.account]
    if inventory.category != "asset" or inventory.cash or not inventory.quantity_tracking:
        raise service.AccountingError("Select an effective noncash inventory asset account with quantity tracking")
    expense = accounts[document.expense_account]
    production_material = document.source.startswith("production:material:") and allow_production_material
    if production_material:
        if expense.category != "asset" or expense.cash or expense.quantity_tracking:
            raise service.AccountingError("Select a noncash WIP asset account without quantity tracking")
    elif expense.category != "expense" or expense.cash or expense.quantity_tracking:
        raise service.AccountingError("Select a noncash expense account without quantity tracking")
    return cost, posting


def posting_for(document, cost):
    credit_lines = []
    layers = cost.get("inventory_layers") or []
    allocation = explicit_allocation(document, cost)
    if layers:
        for layer in layers:
            if allocation is not None and Decimal(str(layer["amount_byn"])) == 0:
                continue
            credit_lines.append(LineInput(account=document.account, side="credit", amount=layer["amount_byn"],
                                           quantity=layer["quantity"], dimensions=layer["dimensions"]))
    else:
        credit_lines.append(LineInput(account=document.account, side="credit", amount=cost["issue_cost_byn"],
                                      quantity=document.quantity, dimensions=cost["inventory_dimensions"]))
    return PostingInput(source=document.source, source_version=document.source_version,
                           operation="inventory_issue", document_date=document.document_date,
                           operation_date=document.operation_date, posting_date=document.posting_date,
                           policy_id=document.policy_id, rule_version=rule_version(document, cost["basis_digest"],
                               allocation_version=cost.get("source_allocation_version")),
                           explanation=document.explanation, lines=[
                               LineInput(account=document.expense_account, side="debit", amount=cost["issue_cost_byn"], dimensions=document.expense_dimensions),
                               *credit_lines,
                           ])


def _guard_production_material_source(document, allow_production_material):
    if document.source.startswith("production:material:") and not allow_production_material:
        raise service.AccountingError("Production material issues require the reviewed production workflow")


async def historical_cost(session, organization_id, entry_id, document, *, procurement=None,
                          allow_production_material=False, allocation_version=None):
    """Reconstruct original inventory cost; caller must verify its receipt/package."""
    _guard_production_material_source(document, allow_production_material)
    from modules.accounting.late_cost_receipts import verified_value_lines

    policy = await session.get(Policy, document.policy_id)
    if policy is None or policy.organization_id != organization_id or policy.inventory_method not in {"specific", "fifo", "weighted_average"}:
        raise service.AccountingError("Inventory issue policy is inconsistent")
    rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
        Entry.organization_id == organization_id, Entry.id < entry_id, Line.account_code == document.account,
    ).order_by(Entry.posting_date, Entry.id, Line.id))).all()
    request = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
    verified = await verified_value_lines(session, organization_id, rows, procurement)
    from modules.accounting.production_output_inventory import (
        is_finished_goods_account,
        verified_output_lines,
    )

    finished_goods = is_finished_goods_account(policy, document.account)
    output_lines = await verified_output_lines(
        session, organization_id, policy, document.account, document.posting_date,
        {"warehouse": document.warehouse, "sku": document.sku, "lot": document.lot}, before_entry_id=entry_id,
    ) if finished_goods else frozenset()
    from modules.accounting.zero_value_disposals import available_authenticated_zero_value_disposals

    receipts = await available_authenticated_zero_value_disposals(
        session, organization_id, before_registration_token=entry_id)
    from modules.accounting.inventory_allocation_loader import (
        load_authenticated_inventory_dispositions,
    )

    if allocation_version is not None and (type(allocation_version) is not int or allocation_version != 1):
        raise service.AccountingError("Explicit allocation version must be integer 1")
    allocations = await load_authenticated_inventory_dispositions(session, organization_id, before_entry_id=entry_id,
        procurement=procurement, inventory_account=document.account)
    cost = inventory_cost.issue_result(policy, rows, organization_id, request, verified_value_lines=verified,
                                       verified_output_lines=output_lines, finished_goods=finished_goods,
                                       zero_value_disposals=receipts, before_registration_token=entry_id,
                                       authenticated_dispositions=allocations, include_source_identity=allocation_version == 1)
    if allocation_version == 1:
        cost["source_allocation_version"] = 1
    return cost


async def verify_receipt(session, organization_id, entry_id, *, procurement=None,
                         allow_production_material=False):
    from modules.accounting.closing_commands import actual_posting

    await service.lock_organization(session, organization_id)
    receipt = await session.get(InventoryIssueReceipt, entry_id)
    entry = await session.get(Entry, entry_id)
    if receipt is None or entry is None or receipt.organization_id != organization_id or entry.organization_id != organization_id:
        raise service.AccountingError("Inventory issue has no matching source receipt")
    document = InventoryIssueDocument.model_validate(receipt.command)
    _guard_production_material_source(document, allow_production_material)
    allocation = explicit_allocation(document, receipt.cost)
    cost = await historical_cost(session, organization_id, entry_id, document, procurement=procurement,
                                 allow_production_material=allow_production_material,
                                 allocation_version=allocation.allocation_version if allocation else None)
    expected = posting_for(document, cost)
    if (json.loads(json.dumps(cost, default=str)) != receipt.cost
        or PostingInput.model_validate(receipt.posting).model_dump() != expected.model_dump()
        or receipt.digest != service.digest(expected) or entry.digest != receipt.digest or entry.actor != receipt.actor
        or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise service.AccountingError("Inventory issue source, calculation or ledger package changed")
    return expected


async def confirm(session, org_id, document, basis_digest, digest, actor, event_bus=None, *, procurement=None,
                  allow_production_material=False, source_allocations=False):
    _guard_production_material_source(document, allow_production_material)
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.source == document.source,
        Entry.source_version == document.source_version, Entry.operation == "inventory_issue",
    ))
    if existing is not None:
        saved = await session.get(InventoryIssueReceipt, existing.id)
        if saved is None:
            raise service.AccountingError("Inventory issue has no matching source receipt")
        allocation = explicit_allocation(InventoryIssueDocument.model_validate(saved.command), saved.cost)
        if existing.rule_version != rule_version(document, basis_digest,
                allocation_version=allocation.allocation_version if allocation else None) or existing.digest != digest:
            raise service.AccountingError("Issue already posted with different content")
        await verify_receipt(session, org_id, existing.id, procurement=procurement,
                             allow_production_material=allow_production_material)
        return existing
    cost, posting = await prepare(session, org_id, document, procurement=procurement,
                                  allow_production_material=allow_production_material, source_allocations=source_allocations)
    if cost["basis_digest"] != basis_digest or service.digest(posting) != digest:
        raise service.AccountingError("Inventory cost basis changed; preview again")
    entry = await service.post(session, org_id, posting, actor, event_bus, inventory_issue=True)
    session.add(InventoryIssueReceipt(entry_id=entry.id, organization_id=org_id,
        command=document.model_dump(mode="json"), cost=json.loads(json.dumps(cost, default=str)),
        posting=posting.model_dump(mode="json"), digest=digest, actor=actor))
    await session.flush()
    if "source_allocation_version" in cost:
        from modules.accounting.inventory_allocation_loader import (
            load_authenticated_inventory_dispositions,
        )

        await load_authenticated_inventory_dispositions(session, org_id, procurement=procurement,
                                                        inventory_account=document.account)
    return entry
