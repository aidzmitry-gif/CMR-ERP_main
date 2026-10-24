"""Whole-act read-only planner. Confirm requires a separate verified receipt gate."""

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from modules.accounting import inventory_cost, sales, service
from modules.accounting.models import SourceControl
from modules.accounting.schemas import (
    Code,
    Input,
    InventoryIssuePreviewInput,
    LineInput,
    PostingInput,
    Quantity,
)


class Allocation(Input):
    line_source: str = Field(min_length=1, max_length=200)
    account: Code
    lot: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    expense_account: Code
    expense_dimensions: dict[str, str] = Field(default_factory=dict)


class CommercialLine(sales.SaleTerms):
    line_no: int = Field(gt=0, strict=True)


class ShipmentPlanInput(Input):
    expected_act_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_id: int = Field(gt=0)
    document_date: date
    posting_date: date
    explanation: str = Field(min_length=1, max_length=700)
    recognition: Literal["sale_on_shipment"]
    recognition_basis: str = Field(min_length=1, max_length=200)
    unit_basis: str = Field(min_length=1, max_length=200)
    cost_allocation: Literal["cumulative_floor_last"]
    vat_rounding: Literal["commercial_line_half_up"]
    allocations: list[Allocation] = Field(min_length=1, max_length=10000)
    commercial_lines: list[CommercialLine] = Field(min_length=1, max_length=1000)


class ShipmentConfirmInput(ShipmentPlanInput):
    expected_basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def prepare(session, org_id, receipt, data: ShipmentPlanInput, *, procurement=None):
    """receipt must come from WMS act_result after source authorization, never HTTP JSON."""
    await service.lock_organization(session, org_id)
    snap = receipt["snapshot"]
    if receipt["digest"] != data.expected_act_digest or snap["organization_id"] != org_id:
        raise service.AccountingError("Physical shipment identity changed")
    source = f"wms:physical-shipment:{org_id}:{receipt['source_key']}"
    control = await session.scalar(
        select(SourceControl).where(
            SourceControl.organization_id == org_id,
            SourceControl.source == source,
        )
    )
    operation_date = date.fromisoformat(snap["operation_date"])
    if (
        control is None
        or control.version != 1
        or control.entry_id is not None
        or control.month != operation_date.strftime("%Y-%m")
    ):
        raise service.AccountingError("A matching pending whole-act source is required")
    if data.posting_date.strftime("%Y-%m") != control.month:
        raise service.AccountingError(
            "Cross-period shipment posting requires a separate correction rule"
        )
    physical = {row["source"]: row for row in snap["lines"]}
    if len(physical) != len(snap["lines"]) or not physical:
        raise service.AccountingError("Physical shipment has duplicate or missing lines")
    commercial = {row.line_no: row for row in data.commercial_lines}
    if len(commercial) != len(data.commercial_lines) or set(commercial) != {
        r["line_no"] for r in physical.values()
    }:
        raise service.AccountingError(
            "Commercial treatment must cover every invoice line exactly once"
        )
    allocations = sorted(data.allocations, key=lambda row: canonical(row.model_dump(mode="json")))
    if len(
        {canonical(row.model_dump(mode="json", exclude={"quantity"})) for row in allocations}
    ) != len(allocations):
        raise service.AccountingError("Duplicate lot allocation")
    buckets = defaultdict(list)
    by_source = defaultdict(Decimal)
    effective_accounts = await service.accounts_on(session, org_id, data.posting_date)
    with localcontext() as context:
        context.prec = 64
        for allocation in allocations:
            # Validate all mappings, including shares that later round to zero.
            # This schema object is not included in any posting.
            expense_line = LineInput(
                account=allocation.expense_account,
                side="debit",
                amount="0.00",
                dimensions=allocation.expense_dimensions,
            )
            expense = effective_accounts.get(allocation.expense_account)
            if (
                expense is None
                or expense.category != "expense"
                or expense.cash
                or expense.quantity_tracking
            ):
                raise service.AccountingError(
                    "Every shipment cost allocation requires an effective expense account"
                )
            if set(expense.required_dimensions) - expense_line.dimensions.keys():
                raise service.AccountingError(
                    "Shipment cost allocation is missing required analytics"
                )
            row = physical.get(allocation.line_source)
            if row is None:
                raise service.AccountingError("Allocation references a foreign physical line")
            if not sales.belongs(allocation.account, "41") or not sales.belongs(
                allocation.expense_account, "90.4"
            ):
                raise service.AccountingError("Shipment sale requires owned goods 41 and cost 90.4")
            by_source[allocation.line_source] += allocation.quantity
            buckets[(allocation.account, row["warehouse"], row["sku_code"], allocation.lot)].append(
                allocation
            )
        if set(by_source) != set(physical) or any(
            by_source[key] != Decimal(row["qty"]) for key, row in physical.items()
        ):
            raise service.AccountingError(
                "Lot allocations must exactly cover every physical quantity"
            )
        blocks, costs, mapping = [], [], []
        for (account, warehouse, sku, lot), items in sorted(buckets.items()):
            quantity = sum((a.quantity for a in items), Decimal(0))
            cost = await inventory_cost.preview_issue(
                session,
                org_id,
                InventoryIssuePreviewInput(
                    policy_id=data.policy_id,
                    posting_date=data.posting_date,
                    account=account,
                    warehouse=warehouse,
                    sku=sku,
                    lot=lot,
                    quantity=quantity,
                ),
                procurement=procurement,
            )
            cents = int(Decimal(cost["issue_cost_byn"]) * 100)
            if cents <= 0:
                raise service.AccountingError(
                    "Zero-cost shipment bucket requires a separate accounting rule"
                )
            total_units = int(quantity * 1000000)
            cumulative, assigned = 0, 0
            groups = {}
            for allocation in items:
                cumulative += int(allocation.quantity * 1000000)
                target = cents * cumulative // total_units
                share = target - assigned
                assigned = target
                mapping.append(
                    {
                        **allocation.model_dump(mode="json"),
                        "cost_byn": format(Decimal(share) / 100, ".2f"),
                    }
                )
                key = (allocation.expense_account, canonical(allocation.expense_dimensions))
                group = groups.setdefault(
                    key,
                    {
                        "cents": 0,
                        "quantity": Decimal(0),
                        "dimensions": allocation.expense_dimensions,
                    },
                )
                group["cents"] += share
                group["quantity"] += allocation.quantity
            positive = [(key, group) for key, group in sorted(groups.items()) if group["cents"]]
            zero_quantity = sum(
                (group["quantity"] for group in groups.values() if not group["cents"]), Decimal(0)
            )
            # All physical quantities leave the same book bucket. Zero-cent
            # analytical shares stay in the manifest; no zero-money line is posted.
            positive[0][1]["quantity"] += zero_quantity
            for (expense, _), group in positive:
                value = Decimal(group["cents"]) / 100
                blocks.append(
                    [
                        LineInput(
                            account=expense,
                            side="debit",
                            amount=value,
                            dimensions=group["dimensions"],
                        ),
                        LineInput(
                            account=account,
                            side="credit",
                            amount=value,
                            quantity=group["quantity"],
                            dimensions=cost["inventory_dimensions"],
                        ),
                    ]
                )
            costs.append(cost)
        net, vat_total, gross_total = Decimal(0), Decimal(0), Decimal(0)
        commercial_evidence = []
        for line_no, row in sorted(commercial.items()):
            if (
                row.buyer_dimensions.get("settlement_document")
                != f"sales:document:{snap['document_id']}"
            ):
                raise service.AccountingError(
                    "Buyer settlement must reference the exact shipment invoice"
                )
            lines, vat, gross = sales.commercial_lines(row)
            blocks.append(lines)
            net += row.net_amount
            vat_total += vat
            gross_total += gross
            commercial_evidence.append(
                {
                    "line_no": line_no,
                    "net_byn": format(row.net_amount, ".2f"),
                    "vat_byn": format(vat, ".2f"),
                    "gross_byn": format(gross, ".2f"),
                }
            )
        pages, page = [], []
        for block in blocks:
            if len(page) + len(block) > 1000:
                pages.append(page)
                page = []
            page.extend(block)
        if page:
            pages.append(page)
        basis = {
            "act_digest": receipt["digest"],
            "inputs": data.model_dump(mode="json"),
            "costs": costs,
            "mapping": mapping,
            "commercial": commercial_evidence,
        }
        # Dates in cost evidence are serialized explicitly; amounts remain strings.
        basis_text = json.dumps(
            basis, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
        )
        digest = hashlib.sha256(basis_text.encode()).hexdigest()
        postings = []
        roles = {allocation.expense_account: "expense" for allocation in allocations}
        for row in commercial.values():
            roles.update(
                {
                    row.buyer_account: "asset",
                    row.revenue_account: "income",
                    row.vat_revenue_account: "income",
                    row.vat_payable_account: "liability",
                }
            )
        for index, lines in enumerate(pages):
            posting = PostingInput(
                source=source if index == 0 else f"{source}:part:{index + 1}",
                source_version=1,
                operation="inventory_sale",
                document_date=data.document_date,
                operation_date=operation_date,
                posting_date=data.posting_date,
                policy_id=data.policy_id,
                rule_version=f"shipment-sale-v1:{digest}",
                explanation=data.explanation,
                lines=lines,
            )
            accounts, _ = await service.validate_posting(
                session, org_id, posting, inventory_sale=True
            )
            for line in lines:
                account = accounts[line.account]
                if line.quantity is not None:
                    if account.category != "asset" or account.cash or not account.quantity_tracking:
                        raise service.AccountingError(
                            "Shipment inventory account must track owned quantities"
                        )
                elif (
                    account.category != roles[line.account]
                    or account.cash
                    or account.quantity_tracking
                ):
                    raise service.AccountingError(
                        "Shipment commercial/cost account has an incompatible role"
                    )
            postings.append(
                {"posting": posting.model_dump(mode="json"), "digest": service.digest(posting)}
            )
        return {
            "organization_id": org_id,
            "source": source,
            "basis_digest": digest,
            "mapping": mapping,
            "costs": costs,
            "commercial": commercial_evidence,
            "postings": postings,
            "net_byn": format(net, ".2f"),
            "vat_byn": format(vat_total, ".2f"),
            "gross_byn": format(gross_total, ".2f"),
            "status": "preview",
            "posted": False,
            "confirmation_available": True,
            "statutory_certified": False,
            "vat_treatment_verified": False,
        }
