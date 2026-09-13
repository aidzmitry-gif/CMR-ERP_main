from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from modules.accounting import models, service, shipment_preview
from tests.accounting.test_inventory_cost import move
from tests.accounting.test_sales import setup_sale


async def fixture(db, book, posting):
    sale = await setup_sale(db, book, posting)
    receipt = {
        "digest": "a" * 64,
        "source_key": "b5b089ab-0000-4000-8000-000000000001",
        "snapshot": {
            "organization_id": book[0],
            "document_id": 27,
            "operation_date": "2026-09-01",
            "lines": [
                {
                    "source": "physical-1",
                    "line_no": 1,
                    "warehouse": "W",
                    "sku_code": "SKU",
                    "qty": "1.00",
                },
                {
                    "source": "physical-2",
                    "line_no": 2,
                    "warehouse": "W",
                    "sku_code": "SKU",
                    "qty": "2.00",
                },
            ],
        },
    }
    db.add(
        models.SourceControl(
            organization_id=book[0],
            source=f"wms:physical-shipment:{book[0]}:{receipt['source_key']}",
            version=1,
            month="2026-09",
        )
    )
    await db.commit()
    terms = {
        key: value
        for key, value in sale.items()
        if key in shipment_preview.CommercialLine.model_fields
    }
    terms["buyer_dimensions"]["settlement_document"] = "sales:document:27"
    data = {
        "expected_act_digest": receipt["digest"],
        "policy_id": book[1],
        "document_date": "2026-09-01",
        "posting_date": "2026-09-01",
        "explanation": "Synthetic whole shipment",
        "recognition": "sale_on_shipment",
        "recognition_basis": "Synthetic accountant decision",
        "unit_basis": "Same unit confirmed",
        "cost_allocation": "cumulative_floor_last",
        "vat_rounding": "commercial_line_half_up",
        "allocations": [
            {
                "line_source": row["source"],
                "account": "41.2",
                "lot": "lot1",
                "quantity": row["qty"],
                "expense_account": "90.4",
                "expense_dimensions": {"department": str(row["line_no"])},
            }
            for row in receipt["snapshot"]["lines"]
        ],
        "commercial_lines": [{**deepcopy(terms), "line_no": 1}, {**deepcopy(terms), "line_no": 2}],
    }
    return receipt, data


async def test_shared_lot_whole_act_costs_and_tax_exactly_once_no_writes(db, book, posting):
    receipt, data = await fixture(db, book, posting)
    result = await shipment_preview.prepare(
        db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
    )
    assert len(result["costs"]) == 1
    assert result["costs"][0]["issue_cost_byn"] == "10.00"
    assert [row["cost_byn"] for row in result["mapping"]] == ["3.33", "6.67"]
    assert (result["net_byn"], result["vat_byn"], result["gross_byn"]) == ("40.00", "8.00", "48.00")
    lines = result["postings"][0]["posting"]["lines"]
    assert sum(Decimal(row["quantity"]) for row in lines if row["account"] == "41.2") == 3
    assert sum(Decimal(row["amount"]) for row in lines if row["account"] == "90.4") == 10
    assert sum(Decimal(row["amount"]) * (1 if row["side"] == "debit" else -1) for row in lines) == 0
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
    assert await db.scalar(select(models.SourceControl.entry_id)) is None
    assert result["confirmation_available"] is True


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "foreign",
        "short",
        "duplicate",
        "commercial_missing",
        "commercial_duplicate",
        "wrong_invoice",
        "stale",
        "aggregate_overdraw",
    ],
)
async def test_full_mapping_and_commercial_coverage_required(db, book, posting, case):
    receipt, data = await fixture(db, book, posting)
    if case == "missing":
        data["allocations"].pop()
    if case == "foreign":
        data["allocations"][0]["line_source"] = "foreign"
    if case == "short":
        data["allocations"][0]["quantity"] = "0.50"
    if case == "duplicate":
        data["allocations"].append(deepcopy(data["allocations"][0]))
    if case == "commercial_missing":
        data["commercial_lines"].pop()
    if case == "commercial_duplicate":
        data["commercial_lines"].append(deepcopy(data["commercial_lines"][0]))
    if case == "wrong_invoice":
        data["commercial_lines"][0]["buyer_dimensions"]["settlement_document"] = "sales:document:99"
    if case == "stale":
        data["expected_act_digest"] = "b" * 64
    if case == "aggregate_overdraw":
        for row in receipt["snapshot"]["lines"]:
            row["qty"] = "3.00"
        for row in data["allocations"]:
            row["quantity"] = "3.00"
    with pytest.raises(service.AccountingError):
        await shipment_preview.prepare(
            db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
        )
    assert await db.scalar(select(models.SourceControl.entry_id)) is None


async def test_partial_act_can_split_lots_without_duplicating_revenue(db, book, posting):
    receipt, data = await fixture(db, book, posting)
    await move(db, book, posting, "other-lot", "1", "5.00", lot="lot2")
    receipt["snapshot"]["lines"] = receipt["snapshot"]["lines"][:1]
    data["commercial_lines"] = data["commercial_lines"][:1]
    allocation = data["allocations"][0]
    data["allocations"] = [
        {**allocation, "quantity": "0.500001"},
        {**allocation, "lot": "lot2", "quantity": "0.499999"},
    ]
    result = await shipment_preview.prepare(
        db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
    )
    assert (
        len(result["costs"]) == 2 and result["net_byn"] == "20.00" and result["vat_byn"] == "4.00"
    )
    assert sum(Decimal(row["issue_quantity"]) for row in result["costs"]) == 1


async def test_zero_cent_analytical_share_preserves_all_inventory_quantity(db, book, posting):
    receipt, data = await fixture(db, book, posting)
    await move(db, book, posting, "tiny-cost", "3", "0.01", lot="tiny")
    for allocation in data["allocations"]:
        allocation["lot"] = "tiny"
    result = await shipment_preview.prepare(
        db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
    )
    assert sorted(row["cost_byn"] for row in result["mapping"]) == ["0.00", "0.01"]
    lines = [line for page in result["postings"] for line in page["posting"]["lines"]]
    assert all(Decimal(line["amount"]) > 0 for line in lines)
    assert sum(Decimal(line["quantity"]) for line in lines if line["account"] == "41.2") == 3
    assert sum(Decimal(line["amount"]) for line in lines if line["account"] == "41.2") == Decimal(
        "0.01"
    )


@pytest.mark.parametrize("bad", ["missing", "blank", "unknown_account"])
async def test_zero_cent_mapping_still_requires_valid_account_and_analytics(db, book, posting, bad):
    receipt, data = await fixture(db, book, posting)
    await move(db, book, posting, "tiny-cost", "3", "0.01", lot="tiny")
    db.add(
        models.Account(
            organization_id=book[0],
            code="90.4.9",
            title="Cost by order",
            category="expense",
            valid_from=date(2026, 1, 1),
            required_dimensions=["department", "order"],
            currency_tracking=False,
            quantity_tracking=False,
            cash=False,
            normative_ref="Synthetic",
        )
    )
    await db.commit()
    for allocation in data["allocations"]:
        allocation.update(lot="tiny", expense_account="90.4.9")
        allocation["expense_dimensions"]["order"] = "confirmed"
    first = data["allocations"][0]
    if bad == "missing":
        first["expense_dimensions"].pop("order")
    elif bad == "blank":
        first["expense_dimensions"]["order"] = " "
    else:
        first["expense_account"] = "90.4.8"
    with pytest.raises((service.AccountingError, ValueError)):
        await shipment_preview.prepare(
            db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
        )


async def test_large_act_preserves_all_balanced_pages(db, book, posting):
    receipt, data = await fixture(db, book, posting)
    # Increase the same lot at the identical acquisition ratio; no mixed-price workaround.
    await move(db, book, posting, "large-receipt", "1500", "5000.00")
    terms = data["commercial_lines"][0]
    receipt["snapshot"]["lines"] = [
        {"source": f"line-{i}", "line_no": i, "warehouse": "W", "sku_code": "SKU", "qty": "1.00"}
        for i in range(1, 502)
    ]
    data["allocations"] = [
        {
            "line_source": row["source"],
            "account": "41.2",
            "lot": "lot1",
            "quantity": "1",
            "expense_account": "90.4",
        }
        for row in receipt["snapshot"]["lines"]
    ]
    data["commercial_lines"] = [
        {**deepcopy(terms), "line_no": i, "vat_rate": "0"} for i in range(1, 502)
    ]
    result = await shipment_preview.prepare(
        db, book[0], receipt, shipment_preview.ShipmentPlanInput(**data)
    )
    assert len(result["postings"]) == 2 and len(result["mapping"]) == 501
    assert result["net_byn"] == "10020.00"
    for page in result["postings"]:
        lines = page["posting"]["lines"]
        assert len(lines) <= 1000
        assert (
            sum(Decimal(row["amount"]) * (1 if row["side"] == "debit" else -1) for row in lines)
            == 0
        )
