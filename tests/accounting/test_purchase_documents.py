from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from modules.accounting import models, reports


@pytest_asyncio.fixture
async def purchase_book(db, book):
    for code, quantity in [("41.1", True), ("18", False)]:
        db.add(models.Account(organization_id=book[0], code=code, title=code,
                              category="asset", valid_from=date(2026, 1, 1),
                              required_dimensions=["counterparty", "contract", "settlement_document"],
                              currency_tracking=False, quantity_tracking=quantity, cash=False,
                              normative_ref="synthetic"))
    await db.commit()
    return book


def purchase(book):
    return dict(source="invoice1", source_version=1, document_date="2026-09-01",
                operation_date="2026-09-02", posting_date="2026-09-03", policy_id=book[1],
                invoice_reference="invoice1", counterparty="supplier1", contract="contract1",
                warehouse="warehouse1", settlement_account="60", vat_account="18",
                explanation="Synthetic owned goods receipt", items=[
                    dict(account="41.1", sku="sku1", lot="lot1", quantity="2",
                         net_amount="100.00", vat_rate="20", vat_amount="20.00", vat_basis="synthetic20"),
                    dict(account="41.1", sku="sku2", lot="lot2", quantity="3",
                         net_amount="50.00", vat_rate="10", vat_amount="5.00", vat_basis="synthetic10"),
                ])


async def test_receipt_has_inventory_and_input_vat_without_expense_or_deduction(client, db, purchase_book):
    prefix = f"/accounting/organizations/{purchase_book[0]}/purchases"
    data = purchase(purchase_book)
    assert (await client.post(prefix + "/preview", json={**data, "counterparty_id": 1})).status_code == 422
    response = await client.post(prefix + "/preview", json=data)
    assert response.status_code == 200, response.text
    assert response.json()["vat_deducted"] is False
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 0
    assert [(r["account"], r["side"], r["amount"]) for r in response.json()["lines"]] == [
        ("41.1", "debit", "100.00"), ("18", "debit", "20.00"),
        ("41.1", "debit", "50.00"), ("18", "debit", "5.00"), ("60", "credit", "175.00"),
    ]
    first = await client.post(prefix + "/confirm", json=data)
    repeat = await client.post(prefix + "/confirm", json=data)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert (await db.get(models.Entry, first.json()["id"])).rule_version == "purchase-byn-v1"
    result = await reports.report(db, purchase_book[0], date(2026, 9, 1), date(2026, 9, 30))
    assert result["pnl"]["profit"] == "0.00"
    assert result["cashflow"]["closing"] == "0.00"
    assert result["balance"]["assets"] == result["balance"]["liabilities"] == "175.00"
    detail = await client.get(f"/accounting/organizations/{purchase_book[0]}/entries/{first.json()['id']}")
    stock = [r for r in detail.json()["lines"] if r["account_code"] == "41.1"]
    assert {r["dimensions"]["lot"] for r in stock} == {"lot1", "lot2"}
    assert all("counterparty_id" not in row["dimensions"] for row in detail.json()["lines"])
    data["items"][0]["vat_basis"] = "changed basis"
    assert (await client.post(prefix + "/confirm", json=data)).status_code == 422


@pytest.mark.parametrize("field,value", [("vat_rate", None), ("vat_amount", "19.99"),
                                         ("net_amount", 1.1), ("net_amount", "0"),
                                         ("vat_basis", ""), ("quantity", "0"),
                                         ("account", "90.4"), ("account", "51"),
                                         ("vat_rate", "101")])
async def test_purchase_invalid_line_is_atomic(client, db, purchase_book, field, value):
    data = purchase(purchase_book)
    data["items"][0][field] = value
    response = await client.post(f"/accounting/organizations/{purchase_book[0]}/purchases/confirm", json=data)
    assert response.status_code == 422
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 0


async def test_zero_tax_has_explicit_basis_and_no_vat_movement(client, purchase_book):
    data = purchase(purchase_book)
    data["items"] = [{**data["items"][0], "vat_rate": "0", "vat_amount": "0", "vat_basis": "synthetic exemption"}]
    data["vat_account"] = None
    prefix = f"/accounting/organizations/{purchase_book[0]}/purchases/preview"
    response = await client.post(prefix, json=data)
    assert response.status_code == 200
    assert len(response.json()["lines"]) == 2
    assert response.json()["lines"][-1]["amount"] == "100.00"
    for field, value in [("settlement_account", "62"), ("vat_account", "68"), ("counterparty", "")]:
        assert (await client.post(prefix, json={**data, field: value})).status_code == 422


async def test_zero_vat_rejects_unrecorded_account_change_on_replay(client, purchase_book):
    data = purchase(purchase_book)
    data["items"] = [{**data["items"][0], "vat_rate": "0", "vat_amount": "0"}]
    data["vat_account"] = None
    prefix = f"/accounting/organizations/{purchase_book[0]}/purchases"
    first = await client.post(prefix + "/confirm", json=data)
    assert first.status_code == 201
    for account in ["18", "18.999"]:
        changed = {**data, "vat_account": account}
        for action in ["preview", "confirm"]:
            assert (await client.post(prefix + "/" + action, json=changed)).status_code == 422
    assert (await client.post(prefix + "/confirm", json=data)).json()["id"] == first.json()["id"]
    taxable = purchase(purchase_book)
    taxable["vat_account"] = None
    assert (await client.post(prefix + "/preview", json=taxable)).status_code == 422
