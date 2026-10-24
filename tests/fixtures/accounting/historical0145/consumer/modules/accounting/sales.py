"""Pilot BYN goods sale preview; recognition and VAT basis are accountant inputs."""
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated

from pydantic import BeforeValidator, Field
from sqlalchemy import select, text

from modules.accounting import inventory_cost, inventory_issues, service
from modules.accounting.models import Entry, InventorySaleReceipt
from modules.accounting.schemas import (
    Code,
    Input,
    InventoryIssueDocument,
    InventoryIssuePreviewInput,
    LineInput,
    Money,
    PostingInput,
    exact,
)


class SaleTerms(Input):
    net_amount: Money
    vat_rate: Annotated[Decimal, BeforeValidator(exact), Field(ge=0, le=100, decimal_places=4)]
    vat_basis: str = Field(min_length=1, max_length=200)
    buyer_account: Code
    revenue_account: Code
    vat_revenue_account: Code
    vat_payable_account: Code
    buyer_dimensions: dict[str, str]
    revenue_dimensions: dict[str, str] = Field(default_factory=dict)
    vat_dimensions: dict[str, str] = Field(default_factory=dict)


class SaleDocument(InventoryIssueDocument, SaleTerms):
    pass


class SaleConfirm(SaleDocument):
    basis_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def rule_version(document, basis_digest, *, allocation_version=None):
    issue_rule = inventory_issues.rule_version(document, basis_digest, allocation_version=allocation_version)
    return "sale-v1:" + issue_rule.removeprefix("inventory-issue-v2:")


def belongs(code, root):
    return code == root or code.startswith(root + ".")


def commercial_lines(document):
    if document.net_amount <= 0 or not document.vat_basis.strip():
        raise service.AccountingError("Positive sale amount and an explicit VAT basis are required")
    for key in ("counterparty", "contract", "settlement_document"):
        if not document.buyer_dimensions.get(key, "").strip():
            raise service.AccountingError("Buyer, contract and settlement document are required")
    roots = {"buyer_account": "62",
             "revenue_account": "90.1", "vat_revenue_account": "90.2", "vat_payable_account": "68"}
    if any(not belongs(getattr(document, field), root) for field, root in roots.items()):
        raise service.AccountingError("Pilot sale requires goods 41, buyer 62, revenue 90.1, VAT 90.2/68 and cost 90.4")
    with localcontext() as context:
        context.prec = 64
        vat = (document.net_amount * document.vat_rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        gross = document.net_amount + vat
    vat_dimensions = dict(document.vat_dimensions)
    revenue_dimensions = dict(document.revenue_dimensions)
    for key, value in {"vat_rate": format(document.vat_rate, "f"), "vat_basis": document.vat_basis}.items():
        for dimensions in (vat_dimensions, revenue_dimensions):
            if key in dimensions and dimensions[key] != value:
                raise service.AccountingError("Conflicting VAT metadata")
            dimensions[key] = value
    lines = [LineInput(account=document.buyer_account, side="debit", amount=gross, dimensions=document.buyer_dimensions),
             LineInput(account=document.revenue_account, side="credit", amount=gross, dimensions=revenue_dimensions)]
    # Preserve readable VAT evidence on revenue even when tax rounds to zero.
    if vat:
        lines += [LineInput(account=document.vat_revenue_account, side="debit", amount=vat, dimensions=vat_dimensions),
                  LineInput(account=document.vat_payable_account, side="credit", amount=vat, dimensions=vat_dimensions)]
    return lines, vat, gross


def posting_for(document, cost):
    lines, _, _ = commercial_lines(document)
    if not belongs(document.expense_account, "90.4"):
        raise service.AccountingError("Pilot sale requires cost account 90.4")
    issue = InventoryIssueDocument(**document.model_dump(include=set(InventoryIssueDocument.model_fields)))
    if Decimal(cost["issue_cost_byn"]) == 0:
        inventory_issues.explicit_allocation(issue, cost)
        return PostingInput(**issue.model_dump(include={"source", "source_version", "document_date",
            "operation_date", "posting_date", "policy_id", "explanation"}), operation="inventory_sale",
            rule_version=rule_version(document, cost["basis_digest"]), lines=lines)
    issue_posting = inventory_issues.posting_for(issue, cost)
    lines += issue_posting.lines
    return PostingInput(**{**issue_posting.model_dump(exclude={"lines", "operation", "rule_version"}),
                              "operation": "inventory_sale", "rule_version": rule_version(document, cost["basis_digest"],
                                  allocation_version=cost.get("source_allocation_version")),
                              "lines": lines})


async def prepare(session, org_id, document, *, procurement=None, source_allocations=False):
    _, vat, gross = commercial_lines(document)
    issue = InventoryIssueDocument(**document.model_dump(include=set(InventoryIssueDocument.model_fields)))
    cost_request = InventoryIssuePreviewInput(**issue.model_dump(include=set(InventoryIssuePreviewInput.model_fields)))
    cost = await inventory_cost.preview_issue(session, org_id, cost_request, procurement=procurement)
    zero_command = None
    if Decimal(cost["issue_cost_byn"]) == 0:
        zero_command = await prepare_zero_command(session, org_id, document, procurement=procurement)
    else:
        cost, _ = await inventory_issues.prepare(session, org_id, issue, procurement=procurement,
                                                source_allocations=source_allocations)
    posting = posting_for(document, cost)
    accounts, _ = await service.validate_posting(session, org_id, posting, inventory_sale=True)
    roles = {document.buyer_account: "asset", document.revenue_account: "income"}
    if vat:
        roles.update({document.vat_revenue_account: "income", document.vat_payable_account: "liability"})
    for code, category in roles.items():
        account = accounts[code]
        if account.category != category or account.cash or account.quantity_tracking:
            raise service.AccountingError("Sale accounts need noncash, nonquantitative roles; VAT 90.2 must reduce income")
    result = {"cost": cost, "posting": posting.model_dump(mode="json"), "digest": service.digest(posting),
            "net_amount_byn": format(document.net_amount, ".2f"), "vat_amount_byn": format(vat, ".2f"),
            "gross_amount_byn": format(gross, ".2f"), "posted": False, "statutory_certified": False,
            "vat_treatment_verified": False}
    if zero_command is not None:
        result["zero_value_command"] = zero_command.model_dump(mode="json")
    return result


async def prepare_zero_command(session, org_id, document, *, procurement=None):
    from modules.accounting.specific_zero_value_issue import implicit_document, preview
    from modules.accounting.zero_value_disposals import ZeroValueSaleCommand, canonical_json

    if not await session.scalar(text("SELECT to_regprocedure('accounting.validate_zero_sale_link(integer)') IS NOT NULL")):
        raise service.AccountingError("Zero-value sale requires migration 0143")
    issue = InventoryIssueDocument(**document.model_dump(include=set(InventoryIssueDocument.model_fields)))
    explicit = await implicit_document(session, org_id, issue, procurement=procurement)
    if explicit is None:
        raise service.AccountingError("Zero-value sale requires a zero-cost source")
    # Reuse source, destination and policy authentication without creating an issue.
    checked = await preview(session, org_id, explicit, "sale-preview")
    command = ZeroValueSaleCommand.model_validate({**checked["command"], "command_version": 3,
        "operation": "inventory_sale", "sale_document": document.model_dump(mode="json")})
    basis = await session.scalar(text("SELECT accounting.zero_value_disposal_basis(:org,CAST(:command AS jsonb),2147483647)"),
                                 {"org": org_id, "command": canonical_json(command.model_dump(mode="json"))})
    return command.model_copy(update={"basis_digest": basis})


async def verify_receipt(session, organization_id, entry_id, *, procurement=None):
    from modules.accounting.closing_commands import actual_posting

    await service.lock_organization(session, organization_id)
    receipt = await session.get(InventorySaleReceipt, entry_id)
    entry = await session.get(Entry, entry_id)
    if receipt is None or entry is None or receipt.organization_id != organization_id or entry.organization_id != organization_id:
        raise service.AccountingError("Inventory sale has no matching source receipt")
    document = SaleDocument.model_validate(receipt.command)
    allocation = inventory_issues.explicit_allocation(document, receipt.cost)
    cost = await inventory_issues.historical_cost(session, organization_id, entry_id, document, procurement=procurement,
                                                 allocation_version=allocation.allocation_version if allocation else None)
    if Decimal(cost["issue_cost_byn"]) == 0:
        await session.execute(text("SELECT accounting.validate_zero_sale_link(:entry)"), {"entry": entry_id})
    expected = posting_for(document, cost)
    if (json.loads(json.dumps(cost, default=str)) != receipt.cost
        or PostingInput.model_validate(receipt.posting).model_dump() != expected.model_dump()
        or receipt.digest != service.digest(expected) or entry.digest != receipt.digest or entry.actor != receipt.actor
        or (await actual_posting(session, entry)).model_dump() != expected.model_dump()):
        raise service.AccountingError("Inventory sale source, calculation or ledger package changed")
    return expected


async def confirm(session, org_id, document, basis_digest, digest, actor, event_bus=None, *, procurement=None,
                  source_allocations=False):
    await service.lock_organization(session, org_id)
    existing = await session.scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.source == document.source,
        Entry.source_version == document.source_version, Entry.operation == "inventory_sale",
    ))
    # Exact replay must succeed even after the stock was consumed or period closed.
    if existing is not None:
        saved = await session.get(InventorySaleReceipt, existing.id)
        if saved is None:
            raise service.AccountingError("Inventory sale has no matching source receipt")
        allocation = inventory_issues.explicit_allocation(SaleDocument.model_validate(saved.command), saved.cost)
        if existing.rule_version != rule_version(document, basis_digest,
                allocation_version=allocation.allocation_version if allocation else None) or existing.digest != digest:
            raise service.AccountingError("Sale already posted with different content")
        await verify_receipt(session, org_id, existing.id, procurement=procurement)
        return existing
    prepared = await prepare(session, org_id, document, procurement=procurement, source_allocations=source_allocations)
    if prepared["cost"]["basis_digest"] != basis_digest or prepared["digest"] != digest:
        raise service.AccountingError("Sale or inventory cost basis changed; preview again")
    entry = await service.post(session, org_id, PostingInput(**prepared["posting"]), actor, event_bus, inventory_sale=True)
    session.add(InventorySaleReceipt(entry_id=entry.id, organization_id=org_id,
        command=document.model_dump(mode="json"), cost=json.loads(json.dumps(prepared["cost"], default=str)),
        posting=prepared["posting"], digest=digest, actor=actor))
    if "zero_value_command" in prepared:
        from modules.accounting.models import ZeroValueInventoryDisposalReceipt
        from modules.accounting.zero_value_disposals import ZeroValueSaleCommand, receipt_digest

        command = ZeroValueSaleCommand.model_validate(prepared["zero_value_command"])
        session.add(ZeroValueInventoryDisposalReceipt(organization_id=org_id, entry_id=entry.id,
            source=command.source, source_version=command.source_version, operation="inventory_sale",
            posting_date=command.posting_date, policy_id=command.policy_id, command=command.model_dump(mode="json"),
            basis_digest=command.basis_digest, digest=receipt_digest(org_id, actor, command), actor=actor))
    await session.flush()
    if "source_allocation_version" in prepared["cost"]:
        from modules.accounting.inventory_allocation_loader import (
            load_authenticated_inventory_dispositions,
        )

        await load_authenticated_inventory_dispositions(session, org_id, procurement=procurement,
                                                        inventory_account=document.account)
    return entry
