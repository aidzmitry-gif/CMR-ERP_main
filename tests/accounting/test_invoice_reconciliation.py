from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.accounting.models import AccessGrant
from modules.sales import invoice_reconciliation as reconciliation
from modules.sales.invoice_money_basis import evaluate_invoice_money_basis
from modules.sales.models import DealDocument
from tests.accounting.test_invoice_settlements import bank, setup


async def prepare(client, db, book, status="posted"):
    doc_id, allocations = await setup(client, db, book, status=status)
    client.test_app.include_router(reconciliation.router, prefix="/sales")
    url = allocations.removesuffix("settlements") + "money-reconciliation"
    return doc_id, allocations, url


async def payload(client, url, **changes):
    preview = await client.get(url)
    assert preview.status_code == 200, preview.text
    facts = preview.json()
    return {"source_key": "review-1", "expected_basis_digest": facts["basis_digest"],
            "history_from": facts["required_history_from"],
            "history_through": facts["required_history_through"],
            "evidence": "Synthetic complete bank, cash and legacy statement comparison",
            "source_references": ["Synthetic statements register 1"],
            "all_money_sources_checked": True, **changes}


async def test_confirm_replay_current_and_new_money_invalidates(client, db, book):
    doc_id, _, url = await prepare(client, db, book)
    data = await payload(client, url)
    result = await client.post(url, json=data)
    assert result.status_code == 201, result.text
    replay = await client.post(url, json=data)
    assert replay.json() == result.json()
    assert await db.scalar(select(func.count()).select_from(reconciliation.InvoiceMoneyReconciliation)) == 1
    view = (await client.get(url)).json()
    assert view["records"][0]["current"] is True
    assert (view["organization_id"], view["document_id"]) == (book[0], doc_id)
    assert view["review_date"] == date.today().isoformat()
    doc = await db.get(DealDocument, doc_id)
    gateway = AccountingService()
    user = CurrentUser("tester", ["director"])
    await gateway.source_owner_authority(db, book[0], user)
    basis = await evaluate_invoice_money_basis(db, book[0], user, doc, gateway)
    assert (await reconciliation.require_current(db, book[0], doc, basis, result.json()["id"])).id == result.json()["id"]
    await db.commit()
    await bank(client, book, doc_id, "new-money", "10.00")
    after = (await client.get(url)).json()
    assert after["records"][0]["current"] is False
    assert after["can_confirm_money_history"] is False
    await gateway.source_owner_authority(db, book[0], user)
    basis = await evaluate_invoice_money_basis(db, book[0], user, doc, gateway)
    with pytest.raises(HTTPException) as error:
        await reconciliation.require_current(db, book[0], doc, basis, result.json()["id"])
    assert error.value.status_code == 409
    await db.rollback()
    assert (await client.post(url, json={**data, "source_key": "new-stale-key"})).status_code == 409
    assert (await client.post(url, json={**data, "evidence": "Changed facts"})).status_code == 409


async def test_full_refund_can_be_reconciled_but_partial_cannot(client, db, book):
    doc_id, allocations, url = await prepare(client, db, book, "paid")
    assert (await client.get(url)).json()["can_confirm_money_history"] is False
    receipt = await bank(client, book, doc_id, "received")
    allocated = await client.post(allocations, json={"source_key": "received", "bank_entry_id": receipt,
        "amount": "100.00", "evidence": "Synthetic"})
    for key, value, can_confirm in [("part", "40.00", False), ("rest", "60.00", True)]:
        refund = await bank(client, book, doc_id, key, value, "payment")
        assert (await client.post(allocations, json={"source_key": key, "bank_entry_id": refund,
            "amount": value, "refund_of": allocated.json()["id"], "evidence": "Synthetic"})).status_code == 201
        data = await payload(client, url, source_key=key)
        response = await client.post(url, json=data)
        assert response.status_code == (201 if can_confirm else 409), response.text
    doc = await db.get(DealDocument, doc_id)
    assert doc.status == "paid" and doc.reserve_status == "reserved"
    row = await db.scalar(select(reconciliation.InvoiceMoneyReconciliation))
    row.actor = "another"
    with pytest.raises(ValueError):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize("changes,status", [
    ({"all_money_sources_checked": False}, 422),
    ({"source_references": [" "]}, 422),
    ({"source_references": ["same", "same"]}, 422),
    ({"history_from": "2099-01-01"}, 409),
    ({"history_through": "2000-01-01"}, 409),
    ({"history_through": (date.today() + timedelta(days=1)).isoformat()}, 409),
    ({"expected_basis_digest": "a" * 64}, 409),
])
async def test_confirmation_requires_exact_facts_and_explicit_complete_history(client, db, book, changes, status):
    _, _, url = await prepare(client, db, book)
    data = await payload(client, url, **changes)
    assert (await client.post(url, json=data)).status_code == status
    assert await db.scalar(select(func.count()).select_from(reconciliation.InvoiceMoneyReconciliation)) == 0


async def test_chief_and_organization_scope_required(client, db, book):
    doc_id, _, url = await prepare(client, db, book)
    data = await payload(client, url)
    assert (await client.post(f"/sales/organizations/999/invoices/{doc_id}/money-reconciliation", json=data)).status_code == 403
    grant = await db.scalar(select(AccessGrant))
    grant.role = "reader"
    await db.commit()
    assert (await client.get(url)).status_code == 403
    assert (await client.post(url, json=data)).status_code == 403


async def test_future_money_facts_are_not_advertised_as_confirmable(client, db, book):
    doc_id, allocations, url = await prepare(client, db, book, "paid")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    incoming = await bank(client, book, doc_id, "future-in", operation_date=tomorrow, posting_date=tomorrow)
    receipt = await client.post(allocations, json={"source_key": "future-in", "bank_entry_id": incoming,
        "amount": "100.00", "evidence": "Synthetic"})
    outgoing = await bank(client, book, doc_id, "future-out", direction="payment", operation_date=tomorrow, posting_date=tomorrow)
    assert (await client.post(allocations, json={"source_key": "future-out", "bank_entry_id": outgoing,
        "amount": "100.00", "refund_of": receipt.json()["id"], "evidence": "Synthetic"})).status_code == 201
    result = (await client.get(url)).json()
    assert result["money_state"] == "fully_refunded"
    assert result["can_confirm_money_history"] is False
    assert "future_money_history_requires_review" in result["blockers"]
    assert (await client.post(url, json=await payload(client, url))).status_code == 409
