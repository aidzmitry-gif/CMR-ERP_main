from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Organization
from modules.sales import document_register as register
from modules.sales.access import DealAccess, get_deal_access
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.models import Deal, DealDocument


async def seed(db, book, client):
    client.test_app.include_router(register.router, prefix="/sales")
    client.test_app.state.core.roles = {}
    deals = [Deal(number=f"REGISTER-{i}", title="Synthetic", counterparty="Same name",
                  owner_id=i) for i in (7, 8, 9)]
    db.add_all(deals)
    await db.flush()
    org = Organization(name="Other synthetic book", unp="888888888")
    db.add(org)
    await db.flush()
    db.add(AccessGrant(organization_id=org.id, subject="tester", role="reader"))
    for deal, org_id in zip(deals, [book[0], book[0], org.id], strict=True):
        db.add(DealOwnership(deal_id=deal.id, organization_id=org_id,
                             snapshot={}, evidence="test only", actor="tester"))
    now = datetime.now(timezone.utc)
    rows = []
    for i, (deal, kind, status) in enumerate([
        (deals[0], "invoice", "posted"), (deals[0], "invoice", "posted"),
        (deals[0], "contract", "pending_approval"), (deals[0], "order", "draft"),
        (deals[0], "invoice", "posted"), (deals[1], "invoice", "posted"),
        (deals[2], "invoice", "posted"),
    ]):
        html = f"<html><body>Saved version {i}</body></html>"
        legacy = i == 4
        row = DealDocument(deal_id=deal.id, kind=kind, number=f"DOC-{i}", status=status,
            amount="1200.01", version=2 if i == 1 else 1, reserve_status="consumed",
            original_html=html if not legacy and status != "draft" else None,
            snapshot_json={"amount": "1200.01", "currency": "BYN"} if not legacy and status != "draft" else None,
            content_sha256=digest(html) if not legacy and status != "draft" else None,
            issued_at=now if not legacy and status == "posted" else None)
        db.add(row)
        rows.append(row)
    await db.flush()
    ids = [row.id for row in rows]
    # Set the initial historical link without updating immutable original facts.
    await db.execute(update(DealDocument).where(DealDocument.id == ids[0]).values(superseded_by_id=ids[1]))
    await db.execute(update(DealDocument).where(DealDocument.id == ids[1]).values(supersedes_id=ids[0]))
    await db.commit()
    return [deal.id for deal in deals], ids, org.id


def base(org, deal):
    return f"/sales/organizations/{org}/deals/{deal}"


async def test_ledger_original_reference_is_book_and_deal_scoped(db, book, client):
    _, ids, _ = await seed(db, book, client)
    url = f"/sales/organizations/{book[0]}/documents"
    response = await client.get(f"{url}/{ids[0]}/original")
    assert response.status_code == 200 and response.text == "<html><body>Saved version 0</body></html>"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"] == f'"{digest(response.text)}"'
    assert not db.in_transaction()
    for foreign in [ids[-1], 99999]:
        response = await client.get(f"{url}/{foreign}/original")
        assert response.status_code == 404 and "Saved version" not in response.text
    for unavailable in ids[3:5]:
        assert (await client.get(f"{url}/{unavailable}/original")).status_code == 409
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 8)
    assert (await client.get(f"{url}/{ids[0]}/original")).status_code == 404
    assert (await client.get(f"{url}/{ids[-2]}/original")).status_code == 200
    assert not db.in_transaction()


async def test_ledger_original_rejects_missing_authority_and_corruption(db, book, client):
    _, ids, _ = await seed(db, book, client)
    url = f"/sales/organizations/{book[0]}/documents/{ids[0]}/original"
    await db.execute(update(DealDocument).where(DealDocument.id == ids[0]).values(original_html="tampered"))
    await db.commit()
    assert (await client.get(url)).status_code == 409
    gateway = client.test_app.state.core.services.accounting
    gateway.source_member = AsyncMock(wraps=gateway.source_member)
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", [])
    assert (await client.get(url)).status_code == 403
    gateway.source_member.assert_not_called()
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("no-grant", ["director"])
    assert (await client.get(url)).status_code == 403
    client.test_app.state.core.services.accounting = None
    assert (await client.get(url)).status_code == 503


async def test_pages_exact_amounts_coverage_and_scoped_link_lookup(db, book, client):
    deals, ids, _ = await seed(db, book, client)
    url = base(book[0], deals[0])
    first = await client.get(url + "/document-register?limit=1&kind=invoice")
    assert first.status_code == 200, first.text
    data = first.json()
    assert [r["id"] for r in data["items"]] == ids[:1]
    assert data["items"][0]["amount"] == "1200.01"
    assert data["items"][0]["superseded_by_id"] == ids[1]
    assert data["next_after_id"] == ids[0]
    assert data["client_identity"] == {"status": "unresolved", "counterparty_id": None}
    assert data["coverage"]["shipments"] == "unavailable"
    second = (await client.get(url + f"/document-register?limit=1&kind=invoice&after_id={ids[0]}")).json()
    assert second["items"][0]["id"] == ids[1]
    lookup = await client.get(url + f"/document-register/{ids[1]}")
    assert lookup.status_code == 200 and lookup.json()["supersedes_id"] == ids[0]
    full = (await client.get(url + "/document-register")).json()
    assert [r["id"] for r in full["items"]] == ids[:5]
    assert full["next_after_id"] is None
    assert full["items"][4]["currency"] is None
    assert full["items"][4]["original_available"] is False
    assert full["items"][3]["preview_available"] is False  # order has no original route


async def test_register_exposes_verified_internal_shipment_acts_without_calling_them_tn_ttn(db, book, client):
    deals, ids, _ = await seed(db, book, client)

    class ShipmentRegister:
        async def invoice_shipments_register(self, session, organization_id, document_ids):
            assert organization_id == book[0] and document_ids == [ids[0], ids[1], ids[4]]
            return {"status": "internal_acts_only", "tn_ttn_status": "not_certified", "items": [{
                "act_id": 71, "document_id": ids[0], "document_version": 1,
                "content_sha256": "a" * 64, "source_key": "12345678-1234-4234-8234-123456789012",
                "operation_date": "2026-09-13", "actor": "tester", "evidence": "test shipment",
                "line_count": 2, "status": "verified_internal_act", "tn_ttn_status": "not_certified",
                "document_url": f"/api/wms/organizations/{book[0]}/physical-shipments/by-key/12345678-1234-4234-8234-123456789012/document",
            }]}

    client.test_app.state.core.services.wms_reservations = ShipmentRegister()
    response = await client.get(base(book[0], deals[0]) + "/document-register?kind=invoice")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["coverage"]["shipments"] == "internal_acts_only"
    assert data["coverage"]["tn_ttn"] == "not_certified"
    assert data["shipment_documents"][0]["status"] == "verified_internal_act"
    assert data["shipment_documents"][0]["tn_ttn_status"] == "not_certified"


@pytest.mark.parametrize("role", ["reader", "accountant", "chief"])
async def test_all_read_book_roles_can_read_without_chief(db, book, client, role):
    deals, _, _ = await seed(db, book, client)
    await db.execute(update(AccessGrant).where(AccessGrant.organization_id == book[0]).values(role=role))
    await db.commit()
    assert (await client.get(base(book[0], deals[0]) + "/document-register")).status_code == 200


async def test_same_name_other_deal_and_org_never_leak(db, book, client):
    deals, ids, org2 = await seed(db, book, client)
    url = base(book[0], deals[0])
    for foreign in ids[-2:]:
        assert (await client.get(url + f"/document-register/{foreign}")).status_code == 404
        assert (await client.get(url + f"/documents/{foreign}/original")).status_code == 404
    assert (await client.get(base(org2, deals[0]) + "/document-register")).status_code == 404
    client.test_app.dependency_overrides[get_deal_access] = lambda: DealAccess("own", 8)
    assert (await client.get(url + "/document-register")).status_code == 404
    assert (await client.get(url + f"/document-register/{ids[0]}")).status_code == 404
    assert (await client.get(url + f"/documents/{ids[0]}/original")).status_code == 404
    assert (await client.get(base(book[0], deals[1]) + "/document-register")).status_code == 200


async def test_unassigned_missing_book_permission_and_missing_gateway(db, book, client):
    deals, _, _ = await seed(db, book, client)
    orphan = Deal(number="UNASSIGNED", title="Unassigned", counterparty="Same name")
    db.add(orphan)
    await db.commit()
    orphan_id = orphan.id
    assert (await client.get(base(book[0], orphan_id) + "/document-register")).status_code == 404
    assert (await client.get(base(999, deals[0]) + "/document-register")).status_code == 403
    client.test_app.state.core.services.accounting = None
    response = await client.get(base(book[0], deals[0]) + "/document-register")
    assert response.status_code == 503 and "items" not in response.json()


async def test_sales_permission_denied_before_book_access(db, book, client):
    deals, _, _ = await seed(db, book, client)
    gateway = client.test_app.state.core.services.accounting
    gateway.source_member = AsyncMock(wraps=gateway.source_member)
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", [])
    response = await client.get(base(book[0], deals[0]) + "/document-register")
    assert response.status_code == 403
    gateway.source_member.assert_not_called()


@pytest.mark.parametrize("by_document", [False, True])
async def test_org_lock_precedes_deal_read_and_read_rolls_back(db, book, client, monkeypatch, by_document):
    deals, ids, _ = await seed(db, book, client)
    order = []
    gateway = client.test_app.state.core.services.accounting
    member = gateway.source_member
    visible = register.visible_deal_or_404

    async def member_spy(*args):
        result = await member(*args)
        order.append("org_locked")
        return result

    async def visible_spy(*args):
        assert order == ["org_locked"]
        order.append("deal_read")
        return await visible(*args)

    monkeypatch.setattr(gateway, "source_member", member_spy)
    monkeypatch.setattr(register, "visible_deal_or_404", visible_spy)
    url = (f"/sales/organizations/{book[0]}/documents/{ids[0]}/original" if by_document
           else base(book[0], deals[0]) + "/document-register")
    assert (await client.get(url)).status_code == 200
    assert order == ["org_locked", "deal_read"]
    assert not db.in_transaction()


@pytest.mark.parametrize("target", ["foreign", "missing"])
async def test_corrupt_crosslinks_fail_closed_without_exposing_link_ids(db, book, client, target):
    deals, ids, _ = await seed(db, book, client)
    bad_id = ids[-1] if target == "foreign" else 99999
    await db.execute(update(DealDocument).where(DealDocument.id == ids[0]).values(superseded_by_id=bad_id))
    await db.commit()
    url = base(book[0], deals[0])
    for suffix in ["/document-register", f"/document-register/{ids[0]}", f"/documents/{ids[0]}/original"]:
        response = await client.get(url + suffix)
        assert response.status_code == 409
        assert str(bad_id) not in response.text and "items" not in response.json()
    response = await client.get(f"/sales/organizations/{book[0]}/documents/{ids[0]}/original")
    assert response.status_code == 409 and str(bad_id) not in response.text


async def test_original_is_saved_bytes_with_headers_no_preview_fallback(db, book, client):
    deals, ids, _ = await seed(db, book, client)
    url = base(book[0], deals[0])
    result = await client.get(url + f"/documents/{ids[0]}/original")
    assert result.status_code == 200
    assert result.text == "<html><body>Saved version 0</body></html>"
    assert result.headers["etag"] == f'"{digest(result.text)}"'
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-document-state"] == "issued"
    approved = await client.get(url + f"/documents/{ids[2]}/original")
    assert approved.status_code == 200 and approved.headers["x-document-state"] == "approval_copy"
    for index in [3, 4]:
        assert (await client.get(url + f"/documents/{ids[index]}/original")).status_code == 409
    await db.execute(update(DealDocument).where(DealDocument.id == ids[0]).values(original_html="tampered"))
    await db.commit()
    assert (await client.get(url + f"/documents/{ids[0]}/original")).status_code == 409


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "after_id=-1", "kind=ttn"])
async def test_invalid_query_rejected(db, book, client, query):
    deals, _, _ = await seed(db, book, client)
    assert (await client.get(base(book[0], deals[0]) + "/document-register?" + query)).status_code == 422


async def test_empty_is_only_success_and_organizations_use_real_grants(db, book, client):
    deals, _, _ = await seed(db, book, client)
    empty = await client.get(base(book[0], deals[0]) + "/document-register?after_id=99999")
    assert empty.status_code == 200 and empty.json()["items"] == []
    organizations = await client.get("/sales/document-register/organizations")
    assert organizations.status_code == 200
    assert all(set(["id", "name", "unp"]) <= set(row) for row in organizations.json())
    assert len(organizations.json()) == 2
    client.test_app.dependency_overrides[get_current_user] = lambda: CurrentUser("no-grants", ["director"])
    assert (await client.get("/sales/document-register/organizations")).json() == []

async def test_document_register_exposes_persisted_expiry_reminder(db, book, client):
    deals, ids, _ = await seed(db, book, client)
    reminder = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    doc = await db.get(DealDocument, ids[1])
    doc.reminded_at = reminder
    await db.commit()
    response = await client.get(base(book[0], deals[0]) + f"/document-register/{doc.id}")
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["expiry_reminder_at"].replace("Z", "+00:00")) == reminder
    assert response.json()["status"] == "posted"
