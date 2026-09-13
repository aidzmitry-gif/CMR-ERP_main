import pytest
from sqlalchemy import func, select

from modules.accounting import models
from tests.accounting.test_inventory_cost import move, request


def query(book, **changes):
    return {key: value for key, value in request(book, **changes).items() if key not in {"quantity", "lot"}}


async def test_lot_choices_exact_remaining_values_and_no_mutation(client, db, book, posting):
    await move(db, book, posting, "receipt", "3", "10.00")
    await move(db, book, posting, "issue", "1", "3.33", issue=True)
    count = await db.scalar(select(func.count()).select_from(models.Entry))
    path = f"/accounting/organizations/{book[0]}/inventory/lots"
    response = await client.get(path, params=query(book))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert result["lots"] == [{"lot": "lot1", "book_quantity": "2.000000", "book_value_byn": "6.67", "selectable": True, "reason": None}]
    assert result["stock_reserved"] is False and result["final_cost_certified"] is False
    assert await db.scalar(select(func.count()).select_from(models.Entry)) == count
    assert (await client.get(path, params=query(book, warehouse="other"))).json()["lots"] == []
    assert (await client.get(path, params=query(book, search="LOT"))).json()["lots"] == result["lots"]
    assert (await client.get(path, params=query(book, search="missing"))).json()["lots"] == []
    assert (await client.get("/accounting/organizations/999/inventory/lots", params=query(book))).status_code == 403


@pytest.mark.parametrize("case", ["future", "mixed_cost", "currency", "exhausted"])
async def test_unsuitable_lots_remain_visible_but_cannot_be_selected(client, db, book, posting, case):
    await move(db, book, posting, "receipt", "3", "10.00", day="2026-09-02" if case == "future" else "2026-09-01", currency="USD" if case == "currency" else "BYN")
    if case == "mixed_cost":
        await move(db, book, posting, "other_cost", "3", "11.00")
    if case == "exhausted":
        await move(db, book, posting, "issue", "3", "10.00", issue=True)
    response = await client.get(f"/accounting/organizations/{book[0]}/inventory/lots", params=query(book))
    assert response.status_code == 200, response.text
    row = response.json()["lots"][0]
    assert row["selectable"] is False and row["reason"]
    assert row["book_quantity"] == ("0.000000" if case == "exhausted" else None)


async def test_incomplete_account_analytics_block_discovery(client, db, book, posting):
    await move(db, book, posting, "unassigned", "3", "10.00", dimensions=False)
    response = await client.get(f"/accounting/organizations/{book[0]}/inventory/lots", params=query(book))
    assert response.status_code == 422
    assert "reconcile first" in response.json()["detail"]
