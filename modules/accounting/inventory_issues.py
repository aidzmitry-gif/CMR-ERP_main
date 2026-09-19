"""Explicit accountant issue document; warehouse movement remains separate."""
import hashlib
import json

from sqlalchemy import select

from modules.accounting import inventory_cost, service
from modules.accounting.models import Entry, InventoryIssueReceipt, Line, Policy
from modules.accounting.schemas import (
    InventoryIssueDocument,
    InventoryIssuePreviewInput,
    LineInput,
    PostingInput,
)


def rule_version(document, basis_digest):
    raw = json.dumps({"document": document.model_dump(mode="json"), "basis": basis_digest}, sort_keys=True, ensure_ascii=False)
    return "inventory-issue-v2:" + hashlib.sha256(raw.encode()).hexdigest()


async def prepare(session, org_id, document, *, procurement=None, allow_production_material=False):
    _guard_production_material_source(document, allow_production_material)
    cost_request = InventoryIssuePreviewInput(**document.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
    cost = await inventory_cost.preview_issue(session, org_id, cost_request, procurement=procurement)
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
    if layers:
        for layer in layers:
            credit_lines.append(LineInput(account=document.account, side="credit", amount=layer["amount_byn"],
                                           quantity=layer["quantity"], dimensions=layer["dimensions"]))
    else:
        credit_lines.append(LineInput(account=document.account, side="credit", amount=cost["issue_cost_byn"],
                                      quantity=document.quantity, dimensions=cost["inventory_dimensions"]))
    return PostingInput(source=document.source, source_version=document.source_version,
                           operation="inventory_issue", document_date=document.document_date,
                           operation_date=document.operation_date, posting_date=document.posting_date,
                           policy_id=document.policy_id, rule_version=rule_version(document, cost["basis_digest"]),
                           explanation=document.explanation, lines=[
                               LineInput(account=document.expense_account, side="debit", amount=cost["issue_cost_byn"], dimensions=document.expense_dimensions),
                               *credit_lines,
                           ])


def _guard_production_material_source(document, allow_production_material):
    if document.source.startswith("production:material:") and not allow_production_material:
        raise service.AccountingError("Production material issues require the reviewed production workflow")


async def historical_cost(session, organization_id, entry_id, document, *, procurement=None,
                          allow_production_material=False):
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
    return inventory_cost.issue_result(policy, rows, organization_id, request, verified_value_lines=verified,
                                       verified_output_lines=output_lines, finished_goods=finished_goods)


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
    cost = await historical_cost(session, organization_id, entry_id, document, procurement=procurement,
                                 allow_production_material=allow_production_material)
    expected = posting_for(document, cost)
    if (json.loads(json.dumps(cost, default=str)) != receipt.cost
        or PostingInput.model_validate(receipt.posting).model_dump() != expected.model_dump()
        or receipt.digest != service.digest(expected) or entry.digest != receipt.digest or entry.actor != receipt.actor
        or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise service.AccountingError("Inventory issue source, calculation or ledger package changed")
    return expected


async def confirm(session, org_id, document, basis_digest, digest, actor, event_bus=None, *, procurement=None,
                  allow_production_material=False):
    _guard_production_material_source(document, allow_production_material)
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.source == document.source,
        Entry.source_version == document.source_version, Entry.operation == "inventory_issue",
    ))
    if existing is not None:
        if existing.rule_version != rule_version(document, basis_digest) or existing.digest != digest:
            raise service.AccountingError("Issue already posted with different content")
        await verify_receipt(session, org_id, existing.id, procurement=procurement,
                             allow_production_material=allow_production_material)
        return existing
    cost, posting = await prepare(session, org_id, document, procurement=procurement,
                                  allow_production_material=allow_production_material)
    if cost["basis_digest"] != basis_digest or service.digest(posting) != digest:
        raise service.AccountingError("Inventory cost basis changed; preview again")
    entry = await service.post(session, org_id, posting, actor, event_bus, inventory_issue=True)
    session.add(InventoryIssueReceipt(entry_id=entry.id, organization_id=org_id,
        command=document.model_dump(mode="json"), cost=json.loads(json.dumps(cost, default=str)),
        posting=posting.model_dump(mode="json"), digest=digest, actor=actor))
    await session.flush()
    return entry
