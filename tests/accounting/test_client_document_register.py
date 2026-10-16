from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, update

from core.domain.models import Counterparty
from modules.accounting.models import AccessGrant, Organization
from modules.sales import client_document_register as client_register
from modules.sales import document_register
from modules.sales.access import DealAccess, get_deal_access
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument


def deal_base(org, deal):
    return f"/sales/organizations/{org}/deals/{deal}"


def client_base(org, cp):
    return f"/sales/organizations/{org}/counterparties/{cp}"


async def seed(db, book, client):
    client.test_app.include_router(client_register.router, prefix="/sales")
    client.test_app.include_router(document_register.router, prefix="/sales")
    client.test_app.state.core.roles = {}
    cps = [Counterparty(name="Same legal name", unp=unp) for unp in ["111111111", "222222222"]]
    db.add_all(cps)
    other = Organization(name="Other book", unp="888888888")
    db.add(other)
    await db.flush()
    db.add(AccessGrant(organization_id=other.id, subject="tester", role="chief"))
    deals = [Deal(number=f"CLIENT-{i}", title="Test", counterparty="Same legal name",
                  owner_id=8 if i == 1 else 7) for i in range(6)]
    db.add_all(deals)
    await db.flush()
    for i, deal in enumerate(deals[:5]):
        db.add(DealOwnership(deal_id=deal.id, organization_id=other.id if i == 4 else book[0],
                             snapshot={}, evidence="Test org identity", actor="tester"))
    docs = []
    for i, deal in enumerate(deals):
        html = f"<p>Historical client document {i}</p>"
        doc = DealDocument(deal_id=deal.id, kind="invoice", number=f"C-DOC-{i}", amount="1200.01",
                           status="posted", snapshot_json={"amount": "1200.01", "currency": "BYN"},
                           original_html=html, content_sha256=digest(html),
                           issued_at=datetime.now(timezone.utc))
        db.add(doc)
        docs.append(doc)
    await db.commit()
    return [cp.id for cp in cps], [deal.id for deal in deals], [doc.id for doc in docs], other.id


async def claim(client, org, deal, cp):
    base = deal_base(org, deal)
    preview = await client.get(base + f"/client-binding-preview?counterparty_id={cp}")
    assert preview.status_code == 200, preview.text
    payload = {"counterparty_id": cp, "expected_snapshot": preview.json()["snapshot"],
               "evidence": "Exact ID checked against primary documents"}
    response = await client.post(base + "/client-binding", json=payload)
    assert response.status_code == 201, response.text
    return payload, response.json()


async def test_client_picker_returns_distinct_active_directory_ids_in_owned_deal(db, book, client):
    cps, deals, _, other_org = await seed(db, book, client)
    base = deal_base(book[0], deals[0])
    found = await client.get(base + "/client-options", params={"q": "Same legal name"})
    assert found.status_code == 200, found.text
    assert [row["id"] for row in found.json()["items"]] == cps
    assert [row["unp"] for row in found.json()["items"]] == ["111111111", "222222222"]
    by_unp = await client.get(base + "/client-options", params={"q": "222222222"})
    assert [row["id"] for row in by_unp.json()["items"]] == [cps[1]]
    deal = await db.get(Deal, deals[0])
    deal.counterparty_id = cps[1]
    await db.commit()
    linked = await client.get(base + "/client-options", params={"q": "Same"})
    assert [row["id"] for row in linked.json()["items"]] == [cps[1]]
    assert (await client.get(deal_base(other_org, deals[0]) + "/client-options", params={"q": "Same"})).status_code == 404
    assert await db.scalar(select(func.count()).select_from(client_register.DealClientBinding)) == 0


async def test_preview_refreshes_cached_document_before_confirmation(db, book, client):
    from sqlalchemy import update

    cps, deals, docs, _ = await seed(db, book, client)
    cached = await db.get(DealDocument, docs[0])
    old_number = cached.number
    await db.execute(update(DealDocument).where(DealDocument.id == docs[0])
                     .values(number="CURRENT-STORED-NUMBER")
                     .execution_options(synchronize_session=False))
    assert cached.number == old_number
    deal = await db.get(Deal, deals[0])
    preview = await client_register.preview_snapshot(db, book[0], deal, cps[0])
    assert preview["documents"][0]["number"] == "CURRENT-STORED-NUMBER"


async def test_explicit_claim_repeat_and_identity_projection(db, book, client):
    cps, deals, _, _ = await seed(db, book, client)
    url = deal_base(book[0], deals[0])
    before = (await client.get(url + "/document-register")).json()
    assert before["client_identity"] == {"status": "unresolved", "counterparty_id": None}
    payload, bound = await claim(client, book[0], deals[0], cps[0])
    assert bound["snapshot"]["client"] == {"id": cps[0], "unp": "111111111", "name": "Same legal name",
                                          "revision": 1, "is_active": True, "merged_into_id": None}
    assert bound["actor"] == "tester" and bound["created_at"]
    replay = await client.post(url + "/client-binding", json=payload)
    assert replay.status_code == 201 and replay.json() == bound
    assert await db.scalar(select(func.count()).select_from(client_register.DealClientBinding)) == 1
    after = (await client.get(url + "/document-register")).json()
    assert after["client_identity"]["status"] == "confirmed"
    assert after["client_identity"]["counterparty_id"] == cps[0]
    assert (await client.post(url + "/client-binding", json={**payload, "counterparty_id": cps[1]})).status_code == 409
    assert (await client.post(url + "/client-binding", json={**payload, "evidence": "Different"})).status_code == 409
    assert (await client.patch(url + "/client-binding", json=payload)).status_code == 405
    assert (await client.delete(url + "/client-binding")).status_code == 405


async def test_same_names_unbound_cross_org_and_private_deals_excluded(db, book, client):
    cps, deals, docs, other_org = await seed(db, book, client)
    for index, cp in [(0, cps[0]), (1, cps[0]), (2, cps[1])]:
        await claim(client, book[0], deals[index], cp)
    await claim(client, other_org, deals[4], cps[0])
    path = client_base(book[0], cps[0])
    all_rows = (await client.get(path + "/document-register")).json()
    assert [r["id"] for r in all_rows["items"]] == docs[:2]
    assert all_rows["coverage"]["sales_documents"] == "confirmed_bindings_only"
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 7)
    scoped = (await client.get(path + "/document-register")).json()
    assert [r["id"] for r in scoped["items"]] == docs[:1]
    assert scoped["next_after_id"] is None
    assert (await client.get(path + f"/document-register/{docs[1]}")).status_code == 404
    assert (await client.get(path + f"/documents/{docs[1]}/original")).status_code == 404
    for index in [2, 3, 4, 5]:
        assert (await client.get(path + f"/document-register/{docs[index]}")).status_code == 404
        assert (await client.get(path + f"/documents/{docs[index]}/original")).status_code == 404
    other_client = (await client.get(client_base(book[0], cps[1]) + "/document-register")).json()
    assert [r["id"] for r in other_client["items"]] == [docs[2]]


async def test_client_result_becomes_available_after_binding_with_keyset_and_original(db, book, client):
    cps, deals, docs, _ = await seed(db, book, client)
    path = client_base(book[0], cps[0])
    empty = await client.get(path + "/document-register")
    assert empty.status_code == 200 and empty.json()["items"] == []
    for deal in deals[:2]:
        await claim(client, book[0], deal, cps[0])
    first = (await client.get(path + "/document-register?limit=1&kind=invoice")).json()
    assert first["items"][0]["id"] == docs[0] and first["next_after_id"] == docs[0]
    assert first["items"][0]["amount"] == "1200.01"
    second = (await client.get(path + f"/document-register?limit=1&after_id={docs[0]}")).json()
    assert second["items"][0]["id"] == docs[1] and second["next_after_id"] is None
    exact = (await client.get(path + f"/document-register/{docs[1]}")).json()
    assert exact["original_url"] == deal_base(book[0], deals[1]) + f"/documents/{docs[1]}/original"
    original = await client.get(exact["client_original_url"])
    assert original.status_code == 200 and original.text == "<p>Historical client document 1</p>"
    assert original.headers["cache-control"] == "private, no-store"
    assert (await client.get(path + "/document-register?kind=contract")).json()["items"] == []


async def test_client_register_exposes_only_internal_shipment_evidence(db, book, client):
    cps, deals, docs, _ = await seed(db, book, client)
    await claim(client, book[0], deals[0], cps[0])

    class ShipmentRegister:
        async def invoice_shipments_register(self, session, organization_id, document_ids):
            assert organization_id == book[0] and document_ids == [docs[0]]
            return {"status": "internal_acts_only", "tn_ttn_status": "not_certified", "items": [{
                "act_id": 72, "document_id": docs[0], "document_version": 1,
                "content_sha256": "b" * 64, "source_key": "12345678-1234-4234-8234-123456789012",
                "operation_date": "2026-09-13", "actor": "tester", "evidence": "client register test",
                "line_count": 1, "status": "verified_internal_act", "tn_ttn_status": "not_certified",
                "document_url": f"/api/wms/organizations/{book[0]}/physical-shipments/by-key/12345678-1234-4234-8234-123456789012/document",
            }]}

    client.test_app.state.core.services.wms_reservations = ShipmentRegister()
    response = await client.get(client_base(book[0], cps[0]) + "/document-register")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["coverage"]["shipments"] == "internal_acts_only"
    assert data["coverage"]["tn_ttn"] == "not_certified"
    assert data["shipment_documents"][0]["document_id"] == docs[0]


async def test_rename_keeps_historical_snapshot_and_merge_never_follows_survivor(db, book, client):
    cps, deals, docs, _ = await seed(db, book, client)
    payload, bound = await claim(client, book[0], deals[0], cps[0])
    cp = await db.get(Counterparty, cps[0])
    cp.name = "Renamed client"
    await db.commit()
    page = (await client.get(client_base(book[0], cps[0]) + "/document-register")).json()
    assert page["client_current"]["name"] == "Renamed client"
    assert page["items"][0]["client_snapshot"]["name"] == "Same legal name"
    replay = await client.post(deal_base(book[0], deals[0]) + "/client-binding", json=payload)
    assert replay.status_code == 201 and replay.json() == bound
    cp = await db.get(Counterparty, cps[0])
    cp.is_active, cp.merged_into_id = False, cps[1]
    await db.commit()
    old = (await client.get(client_base(book[0], cps[0]) + "/document-register")).json()
    assert old["client_current"]["merged_into_id"] == cps[1]
    assert [r["id"] for r in old["items"]] == docs[:1]
    assert (await client.get(client_base(book[0], cps[1]) + "/document-register")).json()["items"] == []
    assert (await client.get(deal_base(book[0], deals[1]) + f"/client-binding-preview?counterparty_id={cps[0]}")).status_code == 409


@pytest.mark.parametrize("change", ["client", "deal", "document"])
async def test_preview_rejects_changed_identity_or_document_facts(db, book, client, change):
    cps, deals, docs, _ = await seed(db, book, client)
    url = deal_base(book[0], deals[0])
    preview = (await client.get(url + f"/client-binding-preview?counterparty_id={cps[0]}")).json()
    if change == "client":
        obj = await db.get(Counterparty, cps[0])
        obj.name = "Changed after preview"
    elif change == "deal":
        obj = await db.get(Deal, deals[0])
        obj.counterparty = "Changed after preview"
    else:
        await db.execute(update(DealDocument).where(DealDocument.id == docs[0]).values(superseded_by_id=docs[1]))
    await db.commit()
    response = await client.post(url + "/client-binding", json={"counterparty_id": cps[0], "expected_snapshot": preview["snapshot"], "evidence": "Test"})
    assert response.status_code == 409
    assert await db.scalar(select(func.count()).select_from(client_register.DealClientBinding)) == 0


@pytest.mark.parametrize("role", ["reader", "accountant"])
async def test_nonchief_cannot_preview_or_claim_but_can_read(db, book, client, role):
    cps, deals, _, _ = await seed(db, book, client)
    payload, _ = await claim(client, book[0], deals[0], cps[0])
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role=role))
    await db.commit()
    url = deal_base(book[0], deals[0])
    assert (await client.get(url + f"/client-binding-preview?counterparty_id={cps[0]}")).status_code == 403
    assert (await client.post(url + "/client-binding", json=payload)).status_code == 403
    assert (await client.get(client_base(book[0], cps[0]) + "/document-register")).status_code == 200


async def test_unowned_wrong_book_private_claim_and_unknown_client(db, book, client):
    cps, deals, _, other = await seed(db, book, client)
    for org, deal in [(book[0], deals[5]), (other, deals[0])]:
        assert (await client.get(deal_base(org, deal) + f"/client-binding-preview?counterparty_id={cps[0]}")).status_code == 404
    assert (await client.get(deal_base(book[0], deals[0]) + "/client-binding-preview?counterparty_id=99999")).status_code == 404
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 8)
    assert (await client.get(deal_base(book[0], deals[0]) + f"/client-binding-preview?counterparty_id={cps[0]}")).status_code == 404
    assert (await client.post(deal_base(book[0], deals[0]) + "/client-binding", json={"counterparty_id": cps[0], "expected_snapshot": {}, "evidence": "test"})).status_code == 404


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_orm_binding_is_immutable(db, book, client, action):
    cps, deals, _, _ = await seed(db, book, client)
    await claim(client, book[0], deals[0], cps[0])
    row = await db.get(client_register.DealClientBinding, deals[0])
    if action == "update":
        row.counterparty_id = cps[1]
    else:
        await db.delete(row)
    with pytest.raises(ValueError, match="cannot be changed or deleted"):
        await db.flush()
    await db.rollback()


async def test_foreign_version_links_fail_without_leaking_even_with_same_client(db, book, client):
    cps, deals, docs, _ = await seed(db, book, client)
    await claim(client, book[0], deals[0], cps[0])
    await claim(client, book[0], deals[1], cps[0])
    await db.execute(update(DealDocument).where(DealDocument.id == docs[0]).values(superseded_by_id=docs[1]))
    await db.commit()
    path = client_base(book[0], cps[0])
    for suffix in ["/document-register", f"/document-register/{docs[0]}", f"/documents/{docs[0]}/original"]:
        response = await client.get(path + suffix)
        assert response.status_code == 409
        assert "C-DOC-1" not in response.text and "items" not in response.json()


async def test_org_authority_precedes_deal_lock_and_claim_is_atomic(db, book, client, monkeypatch):
    cps, deals, _, _ = await seed(db, book, client)
    service = client.test_app.state.core.services.accounting
    original = service.source_owner_authority
    events = []

    async def authority(*args):
        result = await original(*args)
        events.append("org_locked")
        return result

    real_scalar = db.scalar

    async def scalar(query, *args, **kwargs):
        if "FROM sales.deal \n" in str(query):
            assert events[-1] == "org_locked"
            events.append("deal_locked")
        return await real_scalar(query, *args, **kwargs)

    monkeypatch.setattr(service, "source_owner_authority", authority)
    monkeypatch.setattr(db, "scalar", scalar)
    await claim(client, book[0], deals[0], cps[0])
    assert events == ["org_locked", "deal_locked", "org_locked", "deal_locked"]
    assert not db.in_transaction()


@pytest.mark.parametrize("query", ["after_id=-1", "limit=101", "kind=unknown"])
async def test_invalid_register_parameters_fail(db, book, client, query):
    cps, _, _, _ = await seed(db, book, client)
    assert (await client.get(client_base(book[0], cps[0]) + "/document-register?" + query)).status_code == 422
