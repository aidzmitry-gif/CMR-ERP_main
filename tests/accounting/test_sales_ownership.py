import pytest
from sqlalchemy import func, select

from modules.sales import accounting_ownership as ownership
from modules.sales.access import DealAccess, get_deal_access
from modules.sales.models import Deal, DealDocument


async def seed(client, db):
    client.test_app.include_router(ownership.router, prefix="/sales")
    deal = Deal(number="SYN-1", title="Synthetic", counterparty="Synthetic buyer", owner_id=7)
    db.add(deal)
    await db.flush()
    db.add(DealDocument(deal_id=deal.id, kind="invoice", number="SYN-DOC", amount="24.00", version=1))
    await db.commit()
    return deal.id


async def test_explicit_ownership_snapshot_replay_and_immutable(db, book, client):
    deal_id = await seed(client, db)
    base = f"/sales/organizations/{book[0]}/deals/{deal_id}"
    preview = await client.get(base + "/ownership-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["assigned"] is False
    payload = {"expected_snapshot": preview.json()["snapshot"], "evidence": "Synthetic accountant verification"}
    first = await client.post(base + "/ownership", json=payload)
    assert first.status_code == 201, first.text
    repeat = await client.post(base + "/ownership", json=payload)
    assert repeat.status_code == 201 and repeat.json() == first.json()
    assert (await client.post(base + "/ownership", json={**payload, "evidence": "Changed"})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(ownership.DealOwnership)) == 1
    row = await db.get(ownership.DealOwnership, deal_id)
    row.organization_id = 999
    with pytest.raises(ValueError, match="cannot be changed"):
        await db.flush()
    await db.rollback()


async def test_ownership_rejects_changed_document_and_foreign_visibility(db, book, client):
    deal_id = await seed(client, db)
    base = f"/sales/organizations/{book[0]}/deals/{deal_id}"
    preview = (await client.get(base + "/ownership-preview")).json()
    row = await db.scalar(select(DealDocument))
    row.amount = "25.00"
    await db.commit()
    response = await client.post(base + "/ownership", json={"expected_snapshot": preview["snapshot"], "evidence": "Verified"})
    assert response.status_code == 409, response.text
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 99)
    assert (await client.get(base + "/ownership-preview")).status_code == 404
    assert await db.scalar(select(func.count()).select_from(ownership.DealOwnership)) == 0


async def test_ownership_requires_book_chief_even_for_director(db, book, client):
    from modules.accounting.models import AccessGrant

    deal_id = await seed(client, db)
    grant = await db.scalar(select(AccessGrant))
    grant.role = "accountant"
    await db.commit()
    assert (await client.get(f"/sales/organizations/{book[0]}/deals/{deal_id}/ownership-preview")).status_code == 403
    assert (await client.get(f"/sales/organizations/999/deals/{deal_id}/ownership-preview")).status_code == 403


async def test_payment_does_not_consume_warehouse_reservation(db, client):
    from types import SimpleNamespace

    from modules.sales.events import on_payment_paid

    await seed(client, db)
    document = await db.scalar(select(DealDocument))
    document.status, document.reserve_status = "posted", "reserved"
    await db.commit()
    await on_payment_paid({"document_id": document.id}, SimpleNamespace(session=db))
    await db.commit()
    assert document.status == "paid"
    assert document.reserve_status == "reserved"
    await on_payment_paid({"document_id": document.id}, SimpleNamespace(session=db))
    assert document.reserve_status == "reserved"
    document.status = "cancelled"
    with pytest.raises(ValueError, match="подтверждённого возврата"):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize("paid", [False, True])
async def test_expiry_never_releases_paid_or_unconfirmed_reservation(db, client, paid):
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import Mock

    from modules.sales.reserve import tick_invoice_reserve

    await seed(client, db)
    document = await db.scalar(select(DealDocument))
    document.status = "paid" if paid else "posted"
    document.reserve_status = "reserved"
    document.valid_until = date(2000, 1, 1)
    document.snapshot_json = {"items": [{"sku_code": "TEST", "qty": "1"}]}
    await db.commit()
    bus = Mock()
    await tick_invoice_reserve(db, SimpleNamespace(stock=None, event_bus=bus))
    await db.commit()
    assert document.status == ("paid" if paid else "posted")
    assert document.reserve_status == "reserved" and document.cancelled_at is None
    bus.emit.assert_not_called()
