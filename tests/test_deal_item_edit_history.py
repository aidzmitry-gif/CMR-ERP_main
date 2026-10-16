"""A deal line stays conflict-safe and traceable while an invoice is prepared."""

from uuid import uuid4

from sqlalchemy import func, select

from core.domain.models import AuditLog, Sku
from modules.sales.models import Deal


async def test_item_changes_are_version_checked_and_visible_in_deal_history(api, session):
    deal = Deal(number="ITEM-HISTORY", title="Поставка", counterparty="Покупатель")
    sku = Sku(code="ITEM-HISTORY-SKU", title="Товар", unit="шт")
    session.add_all([deal, sku])
    await session.commit()
    path = f"/sales/deals/{deal.id}/items"
    key = str(uuid4())
    command = {"sku_id": sku.id, "qty": "2.00", "unit_price": "10.00", "request_key": key}
    added = await api.post(path, json=command)
    assert added.status_code == 201, added.text
    original = added.json()
    assert len(original["edit_token"]) == 64
    assert (await api.post(path, json=command)).json() == original
    assert (await api.post(path, json={**command, "unit_price": "11.00"})).status_code == 409

    item_url = f"/sales/deal-items/{original['id']}"
    changed = await api.patch(item_url, json={
        "qty": 3, "unit_price": "12.00", "expected_edit_token": original["edit_token"],
    })
    assert changed.status_code == 200, changed.text
    current = changed.json()
    assert current["edit_token"] != original["edit_token"]
    assert (await api.patch(item_url, json={
        "qty": 4, "expected_edit_token": original["edit_token"],
    })).status_code == 409
    assert (await api.delete(item_url, headers={"If-Match": original["edit_token"]})).status_code == 409

    assert (await api.delete(item_url, headers={"If-Match": current["edit_token"]})).status_code == 204
    history = (await api.get(f"/sales/deals/{deal.id}/field-history")).json()
    assert history["deal_id"] == deal.id
    assert [row["event_type"] for row in history["items"]] == ["sales.deal.item_changed"] * 3
    assert [row["item_action"] for row in history["items"]] == ["deleted", "updated", "added"]
    assert [row["item_id"] for row in history["items"]] == [original["id"]] * 3
    assert all(row["actor"] and row["changed_at"] and row["deal_number"] == deal.number
               for row in history["items"])
    assert history["items"][0]["changes"]["unit_price"] == {"before": "12.00", "after": None}
    assert history["items"][1]["changes"]["qty"] == {"before": "2.00", "after": "3.00"}
    assert history["items"][2]["changes"]["sku_id"] == {"before": None, "after": sku.id}
    assert await session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "sales.deal.item_changed")) == 3


async def test_invalid_quantity_does_not_change_item_or_history(api, session):
    deal = Deal(number="ITEM-VALIDATION", title="Поставка", counterparty="Покупатель")
    sku = Sku(code="ITEM-VALIDATION-SKU", title="Товар", unit="шт")
    session.add_all([deal, sku])
    await session.commit()
    created = await api.post(f"/sales/deals/{deal.id}/items", json={"sku_id": sku.id, "qty": 2})
    assert created.status_code == 201, created.text
    item = created.json()
    for quantity in (None, 0, -1, 0.001):
        response = await api.patch(f"/sales/deal-items/{item['id']}", json={
            "qty": quantity, "expected_edit_token": item["edit_token"],
        })
        assert response.status_code == 422, (quantity, response.text)
    rows = (await api.get(f"/sales/deals/{deal.id}/items")).json()
    assert rows[0]["qty"] == 2
    assert rows[0]["edit_token"] == item["edit_token"]
    history = (await api.get(f"/sales/deals/{deal.id}/field-history")).json()
    assert [row["item_action"] for row in history["items"]] == ["added"]
