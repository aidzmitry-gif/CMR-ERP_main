from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from modules.accounting import inventory_cost, models, service
from modules.accounting.schemas import InventoryIssuePreviewInput
from modules.accounting.service import AccountingError


async def move(db, book, posting, source, quantity, amount, *, issue=False, day="2026-09-01", lot="lot1", dimensions=True, cash=False, currency="BYN", contract=None):
    account = await db.scalar(select(models.Account).where(models.Account.organization_id == book[0], models.Account.code == "41.2"))
    if account is None:
        db.add(models.Account(organization_id=book[0], code="41.2", title="Quantitative goods", category="asset", valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True, quantity_tracking=True, cash=cash, normative_ref="synthetic"))
        await db.commit()
    data = posting(source, "90.4" if issue else "41.2", "41.2" if issue else "60", amount=amount, posting_date=day)
    data.policy_id = book[1]
    line = data.lines[1 if issue else 0]
    line.quantity = Decimal(quantity)
    if dimensions:
        line.dimensions = {"warehouse": "W", "sku": "SKU", "lot": lot}
    if cash:
        line.cash_activity = "operating"
    if contract:
        line.dimensions["contract"] = contract
    if currency != "BYN":
        line.currency = currency
        line.original_amount = Decimal(amount)
        line.rate = Decimal("1")
        line.rate_scale = 1
        line.rate_date = date.fromisoformat(day)
        line.rate_source = "Synthetic test rate"
    await service.post(db, book[0], data, "tester")
    await db.commit()


def request(book, **changes):
    return {"policy_id": book[1], "posting_date": "2026-09-01", "account": "41.2", "warehouse": "W", "sku": "SKU", "lot": "lot1", "quantity": "1", **changes}


@pytest.mark.parametrize("case", ["cash", "currency", "mixed_analytics", "mixed_cost"])
async def test_noninventory_or_nonhomogeneous_lot_is_rejected(client, db, book, posting, case):
    await move(db, book, posting, "receipt1", "3", "10.00", cash=case == "cash", currency="USD" if case == "currency" else "BYN")
    if case in {"mixed_analytics", "mixed_cost"}:
        await move(db, book, posting, "receipt2", "3", "11.00" if case == "mixed_cost" else "10.00", contract="different" if case == "mixed_analytics" else None)
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    response = await client.post(f"/accounting/organizations/{book[0]}/inventory/issues/preview", json=request(book))
    assert response.status_code == 422, response.text
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count


async def test_specific_cost_preview_rounding_and_full_residual(client, db, book, posting):
    await move(db, book, posting, "receipt", "3", "10.00")
    path = f"/accounting/organizations/{book[0]}/inventory/issues/preview"
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    response = await client.post(path, json=request(book))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["issue_cost_byn"] == "3.33" and result["remaining_value_byn"] == "6.67"
    assert result["evidence"][0]["source"] == "receipt"
    assert not result["posted"] and not result["stock_reserved"] and not result["final_cost_certified"]
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    await move(db, book, posting, "issue", "1", "3.33", issue=True)
    full = await client.post(path, json=request(book, quantity="2"))
    assert full.status_code == 200, full.text
    assert full.json()["issue_cost_byn"] == "6.67"
    assert full.json()["remaining_value_byn"] == "0.00"
    assert (await client.post(path, json=request(book, quantity="2.000001"))).status_code == 422
    assert (await client.post("/accounting/organizations/999/inventory/issues/preview", json=request(book))).status_code == 403


@pytest.mark.parametrize("case", ["missing_dimensions", "future", "wrong_lot", "wrong_policy", "negative_history"])
async def test_incomplete_or_unsupported_cost_basis_is_blocked(client, db, book, posting, case):
    await move(db, book, posting, "receipt", "3", "10.00", dimensions=case != "missing_dimensions", day="2026-09-02" if case == "future" else "2026-09-01")
    if case == "negative_history":
        await move(db, book, posting, "excess_issue", "4", "11.00", issue=True)
    changes = {"lot": "unknown"} if case == "wrong_lot" else {"policy_id": 999} if case == "wrong_policy" else {}
    response = await client.post(f"/accounting/organizations/{book[0]}/inventory/issues/preview", json=request(book, **changes))
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(("method", "expected_cost"), [("fifo", "20.00"), ("weighted_average", "24.00")])
async def test_fifo_and_weighted_average_value_explicit_sku_layers(client, db, book, posting, method, expected_cost):
    policy = models.Policy(organization_id=book[0], effective_from=date(2026, 2, 1), reference=f"Synthetic {method}",
                           inventory_method=method, allocation_basis="direct_cost", depreciation_method="straight_line",
                           normative_reference="Synthetic", normative_verified=False, approved_by="tester")
    db.add(policy)
    await db.commit()
    book = (book[0], policy.id)
    await move(db, book, posting, "old-receipt", "3", "10.00", day="2026-09-01", lot="old")
    await move(db, book, posting, "new-receipt", "2", "20.00", day="2026-09-02", lot="new")
    payload = request(book, lot="", quantity="4", posting_date="2026-09-03")
    response = await client.post(f"/accounting/organizations/{book[0]}/inventory/issues/preview", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["method"] == method
    assert result["issue_cost_byn"] == expected_cost
    assert sum(Decimal(layer["quantity"]) for layer in result["inventory_layers"]) == Decimal("4")
    assert {layer["lot"] for layer in result["inventory_layers"]} == {"old", "new"}


def _layer_entry(entry_id, posting_date, operation, line_id, *, lot="old", quantity="3", amount="30.00"):
    dimensions = {"warehouse": "W", "sku": "SKU", "lot": lot}
    line = SimpleNamespace(id=line_id, dimensions=dimensions, category="asset", cash=False,
                           currency="BYN", quantity=Decimal(quantity) if quantity is not None else None,
                           amount=Decimal(amount), side="debit", account_code="41.2")
    entry = SimpleNamespace(id=entry_id, posting_date=date.fromisoformat(posting_date), operation=operation,
                            source=f"synthetic:{entry_id}", source_version=1)
    return entry, line


@pytest.mark.parametrize(("method", "expected_cost"), [("fifo", "53.00"), ("weighted_average", "58.40")])
def test_verified_late_cost_updates_only_the_matching_open_layer(method, expected_cost):
    rows = [
        _layer_entry(1, "2026-09-01", "inventory_purchase", 1),
        _layer_entry(3, "2026-09-02", "inventory_late_cost", 1, quantity=None, amount="3.00"),
        _layer_entry(2, "2026-09-02", "inventory_purchase", 1, lot="new", quantity="2", amount="40.00"),
    ]
    policy = SimpleNamespace(id=1, inventory_method=method, normative_verified=False)
    request = InventoryIssuePreviewInput(policy_id=1, posting_date=date(2026, 9, 3), account="41.2",
                                         warehouse="W", sku="SKU", lot="", quantity="4")
    result = inventory_cost.issue_result(policy, rows, 1, request, verified_value_lines={(3, 1)})
    assert result["issue_cost_byn"] == expected_cost
    assert result["evidence"][1]["late_cost"] is True
    assert result["inventory_layers"][0]["amount_byn"] == ("33.00" if method == "fifo" else "43.80")
    assert sum(Decimal(layer["amount_byn"]) for layer in result["inventory_layers"]) == Decimal(expected_cost)


def test_verified_late_cost_rejects_ambiguous_same_lot_layers():
    rows = [
        _layer_entry(1, "2026-09-01", "inventory_purchase", 1),
        _layer_entry(2, "2026-09-02", "inventory_purchase", 1),
        _layer_entry(3, "2026-09-03", "inventory_late_cost", 1, quantity=None, amount="3.00"),
    ]
    policy = SimpleNamespace(id=1, inventory_method="fifo", normative_verified=False)
    request = InventoryIssuePreviewInput(policy_id=1, posting_date=date(2026, 9, 4), account="41.2",
                                         warehouse="W", sku="SKU", lot="", quantity="1")
    with pytest.raises(AccountingError, match="exactly one open inventory layer"):
        inventory_cost.issue_result(policy, rows, 1, request, verified_value_lines={(3, 1)})


def issue_document(book, **changes):
    return {**request(book), "source": "issue-document", "source_version": 1,
            "document_date": "2026-09-01", "operation_date": "2026-09-01",
            "expense_account": "90.4", "expense_dimensions": {}, "explanation": "Synthetic accountant issue", **changes}


async def test_confirm_issue_is_atomic_idempotent_and_uses_full_analytics(client, db, book, posting):
    await move(db, book, posting, "receipt", "3", "10.00", contract="contract1")
    base = f"/accounting/organizations/{book[0]}/inventory/issues"
    document = issue_document(book)
    preview = await client.post(base + "/posting-preview", json=document)
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    payload = {**document, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    first = await client.post(base + "/confirm", json=payload)
    assert first.status_code == 201, first.text
    repeated = await client.post(base + "/confirm", json=payload)
    assert repeated.status_code == 201 and repeated.json()["id"] == first.json()["id"]
    lines = (await db.scalars(select(models.Line).where(models.Line.entry_id == first.json()["id"]).order_by(models.Line.id))).all()
    assert [(line.side, line.account_code, line.amount) for line in lines] == [("debit", "90.4", Decimal("3.33")), ("credit", "41.2", Decimal("3.33"))]
    assert lines[1].dimensions["contract"] == "contract1"
    assert lines[1].quantity == Decimal("1")
    assert (await client.post(base + "/confirm", json={**payload, "explanation": "Changed"})).status_code == 422
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 2
    remainder = await client.post(base + "/preview", json=request(book, quantity="2"))
    assert remainder.status_code == 200 and remainder.json()["issue_cost_byn"] == "6.67"


async def test_changed_cost_basis_requires_new_preview_and_manual_bypass_denied(client, db, book, posting):
    await move(db, book, posting, "receipt", "3", "10.00")
    base = f"/accounting/organizations/{book[0]}/inventory/issues"
    document = issue_document(book)
    preview = (await client.post(base + "/posting-preview", json=document)).json()
    # Same unit cost and same proposed amount, but different supporting movements.
    await move(db, book, posting, "receipt2", "3", "10.00")
    payload = {**document, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]}
    assert (await client.post(base + "/confirm", json=payload)).status_code == 422
    assert (await client.post(f"/accounting/organizations/{book[0]}/entries", json=preview["posting"])).status_code == 422
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 2
    fresh = (await client.post(base + "/posting-preview", json=document)).json()
    assert fresh["cost"]["issue_cost_byn"] == preview["cost"]["issue_cost_byn"]
    assert fresh["cost"]["basis_digest"] != preview["cost"]["basis_digest"]


async def test_issue_rejects_changed_inventory_account_role(client, db, book, posting):
    await move(db, book, posting, "receipt", "3", "10.00")
    response = await client.post(f"/accounting/organizations/{book[0]}/accounts", json={"code": "41.2", "title": "Changed role", "category": "expense", "valid_from": "2026-09-02", "quantity_tracking": True, "normative_ref": "Synthetic"})
    assert response.status_code == 201, response.text
    response = await client.post(f"/accounting/organizations/{book[0]}/inventory/issues/posting-preview", json=issue_document(book, posting_date="2026-09-02"))
    assert response.status_code == 422, response.text
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1


async def test_issue_commit_failure_rolls_back(client, db, book, posting, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    await move(db, book, posting, "receipt", "3", "10.00")
    base = f"/accounting/organizations/{book[0]}/inventory/issues"
    document = issue_document(book)
    preview = (await client.post(base + "/posting-preview", json=document)).json()

    async def fail():
        raise IntegrityError("Synthetic commit failure", None, Exception("test"))

    monkeypatch.setattr(db, "commit", fail)
    response = await client.post(base + "/confirm", json={**document, "basis_digest": preview["cost"]["basis_digest"], "digest": preview["digest"]})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == 1
