"""Bounded MDM relationship reads keep exact IDs and CRM ownership scopes."""
from datetime import datetime

from core.domain.models import Contact, Counterparty, User
from modules.sales.models import CallLog, CrmClient, CrmClientContact, Deal

OWN = {"X-User": "crm-relationships-owner", "X-User-Roles": "sales"}
FOREIGN = {"X-User": "crm-relationships-foreign", "X-User-Roles": "sales"}


async def seed_users(session):
    session.add_all([
        User(username="crm-relationships-owner", full_name="Synthetic Owner", employee_id=651,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="crm-relationships-foreign", full_name="Synthetic Foreign", employee_id=652,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
    ])
    await session.flush()


def crm_client(owner_id: int, counterparty_id: int | None, slug: str) -> CrmClient:
    return CrmClient(
        name=f"Synthetic CRM {slug}", name_key=f"synthetic-crm-{slug}", unp=None,
        owner_id=owner_id, counterparty_id=counterparty_id,
        request_key=f"request-{slug}", request_hash=f"hash-{slug}", created_by="synthetic-test",
    )


def deal(number: str, owner_id: int | None, counterparty: str, *, counterparty_id=None, crm_client_id=None) -> Deal:
    return Deal(
        number=number, title=f"Synthetic {number}", counterparty=counterparty,
        owner="Synthetic owner", owner_id=owner_id, counterparty_id=counterparty_id, crm_client_id=crm_client_id,
        amount=0, stage="new", funnel="new_clients",
    )


async def visible_company(session, name="Synthetic Visible Company"):
    cp = Counterparty(name=name)
    session.add(cp)
    await session.flush()
    # Existing own-only counterparty visibility is intentionally kept as-is.
    session.add(deal(f"VISIBILITY-{cp.id}", 651, cp.name, counterparty_id=cp.id))
    await session.flush()
    return cp


async def test_relationships_validates_kind_and_bounds_paging(api, session):
    cp = Counterparty(name="Synthetic Public Company")
    session.add(cp)
    await session.commit()
    path = f"/sales/counterparties/{cp.id}/relationships"
    assert (await api.get(path, params={"kind": "other"})).status_code == 422
    assert (await api.get(path, params={"kind": "contacts", "limit": 0})).status_code == 422
    assert (await api.get(path, params={"kind": "deals", "limit": 51})).status_code == 422
    assert (await api.get(path, params={"kind": "contacts", "offset": -1})).status_code == 422
    assert (await api.get(path, params={"kind": "calls", "contact_id": 3})).status_code == 422
    result = await api.get(path, params={"kind": "contacts", "limit": 20})
    assert result.status_code == 200, result.text
    assert result.json() == {
        "kind": "contacts", "counterparty_id": cp.id, "offset": 0, "limit": 20, "total": 0, "items": [],
    }


async def test_relationships_requires_visible_active_counterparty(api, session):
    await seed_users(session)
    visible = await visible_company(session)
    hidden = Counterparty(name="Synthetic Hidden Company")
    inactive = Counterparty(name="Synthetic Inactive Company", is_active=False)
    merged = Counterparty(name="Synthetic Merged Company", merged_into_id=visible.id)
    session.add_all([hidden, inactive, merged])
    await session.commit()
    assert (await api.get(f"/sales/counterparties/{visible.id}/relationships?kind=contacts", headers=OWN)).status_code == 200
    for counterparty_id in (hidden.id, inactive.id, merged.id):
        assert (await api.get(f"/sales/counterparties/{counterparty_id}/relationships?kind=contacts", headers=OWN)).status_code == 404
    assert (await api.get(f"/sales/counterparties/{visible.id}/relationships?kind=contacts", headers=FOREIGN)).status_code == 404


async def test_relationships_contacts_use_shared_counterparty_fk(api, session):
    await seed_users(session)
    cp = await visible_company(session)
    other_cp = Counterparty(name="Synthetic Other Company")
    session.add(other_cp)
    await session.flush()
    shared = Contact(counterparty_id=cp.id, full_name="Synthetic Shared Contact",
                     phone="TEST-PHONE-000", email="shared@example.invalid", is_primary=True)
    other_contact = Contact(counterparty_id=other_cp.id, full_name="Synthetic Other Contact",
                            phone=None, email=None, is_primary=False)
    client = crm_client(651, cp.id, "same-id")
    session.add_all([shared, other_contact, client])
    await session.flush()
    session.add(CrmClientContact(
        id=shared.id, crm_client_id=client.id, full_name="Synthetic CRM Contact",
        phone="TEST-PHONE-111", email="crm@example.invalid", is_primary=True,
        contact_key="same-ns-test", request_key="crm-contact-test", request_hash="crm-contact-hash",
    ))
    await session.commit()
    path = f"/sales/counterparties/{cp.id}/relationships"
    response = await api.get(path, params={"kind": "contacts"}, headers=OWN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"] == [{
        "id": shared.id, "counterparty_id": cp.id, "full_name": "Synthetic Shared Contact",
        "phone": "TEST-PHONE-000", "email": "shared@example.invalid", "is_primary": True,
    }]
    exact = await api.get(path, params={"kind": "contacts", "contact_id": shared.id}, headers=OWN)
    assert exact.status_code == 200 and exact.json()["items"][0]["id"] == shared.id
    foreign = await api.get(path, params={"kind": "contacts", "contact_id": other_contact.id}, headers=OWN)
    assert foreign.status_code == 200 and foreign.json()["items"] == []


async def test_relationships_deals_use_exact_ids_and_owner_scope(api, session):
    await seed_users(session)
    cp = await visible_company(session)
    other_cp = Counterparty(name="Synthetic Other Company")
    session.add(other_cp)
    await session.flush()
    owned_client = crm_client(651, cp.id, "owned")
    foreign_client = crm_client(652, cp.id, "foreign")
    mismatch_client = crm_client(651, other_cp.id, "mismatch")
    session.add_all([owned_client, foreign_client, mismatch_client])
    await session.flush()
    linked_deal = deal("EXACT-CRM-LINK", 651, "Legacy label is not an identity", crm_client_id=owned_client.id)
    direct_deal = deal("EXACT-MDM-LINK", 651, "Different display label", counterparty_id=cp.id)
    text_only = deal("TEXT-ONLY-NO-LINK", 651, cp.name)
    foreign_deal = deal("FOREIGN-CRM-LINK", 651, "Legacy label", crm_client_id=foreign_client.id)
    contradictory_deal = deal("CONTRADICTORY-LINK", 651, "Legacy label", counterparty_id=cp.id,
                               crm_client_id=mismatch_client.id)
    foreign_owner_deal = deal("FOREIGN-OWNER", 652, "Legacy label", counterparty_id=cp.id)
    session.add_all([linked_deal, direct_deal, text_only, foreign_deal, contradictory_deal, foreign_owner_deal])
    await session.commit()
    response = await api.get(f"/sales/counterparties/{cp.id}/relationships?kind=deals", headers=OWN)
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["number"]: row for row in body["items"]}
    assert set(rows) == {f"VISIBILITY-{cp.id}", "EXACT-CRM-LINK", "EXACT-MDM-LINK"}
    assert "TEXT-ONLY-NO-LINK" not in rows
    assert "FOREIGN-CRM-LINK" not in rows and "CONTRADICTORY-LINK" not in rows and "FOREIGN-OWNER" not in rows
    assert rows["EXACT-CRM-LINK"]["crm_client_id"] == owned_client.id
    assert rows["EXACT-CRM-LINK"]["responsible_manager"]["employee_id"] == 651
    assert rows["EXACT-MDM-LINK"]["owner_id"] == 651


async def test_relationships_calls_use_scope_calls_and_explicit_edges(api, session):
    await seed_users(session)
    cp = await visible_company(session)
    other_cp = Counterparty(name="Synthetic Other Company")
    session.add(other_cp)
    await session.flush()
    shared = Contact(counterparty_id=cp.id, full_name="Synthetic Contact",
                     phone="TEST-PHONE-222", email="call-contact@example.invalid", is_primary=False)
    wrong_contact = Contact(counterparty_id=other_cp.id, full_name="Synthetic Wrong Contact",
                            phone=None, email=None, is_primary=False)
    client = crm_client(651, cp.id, "calls")
    session.add_all([shared, wrong_contact, client])
    await session.flush()
    owned_deal = deal("CALL-LINKED-DEAL", 651, cp.name, counterparty_id=cp.id, crm_client_id=client.id)
    session.add(owned_deal)
    await session.flush()
    linked = CallLog(call_id="synthetic-call-linked", direction="in", owner="Synthetic Owner", owner_id=651,
                     counterparty_id=cp.id, contact_id=shared.id, deal_id=owned_deal.id,
                     status="ended", started_at=datetime(2026, 8, 1, 10, 0))
    unlinked = CallLog(call_id="synthetic-call-unlinked", direction="out", owner="Synthetic Owner", owner_id=651,
                       counterparty_id=cp.id, contact_id=wrong_contact.id, deal_id=None,
                       status="ended", started_at=datetime(2026, 8, 1, 11, 0))
    hidden = CallLog(call_id="synthetic-call-foreign", direction="in", owner="Synthetic Foreign", owner_id=652,
                     counterparty_id=cp.id, deal_id=None, status="ended", started_at=datetime(2026, 8, 1, 12, 0))
    session.add_all([linked, unlinked, hidden])
    await session.commit()
    path = f"/sales/counterparties/{cp.id}/relationships?kind=calls"
    response = await api.get(path, headers=OWN)
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["items"]}
    assert set(rows) == {linked.id, unlinked.id}
    assert rows[linked.id]["counterparty_id"] == cp.id
    assert rows[linked.id]["contact_id"] == shared.id
    assert rows[linked.id]["crm_client_id"] == client.id
    assert rows[linked.id]["deal_id"] == owned_deal.id
    assert rows[unlinked.id]["contact_id"] is None
    existing = await api.get(f"/sales/calls?counterparty_id={cp.id}", headers=OWN)
    assert existing.status_code == 200, existing.text
    existing_rows = {row["id"]: row for row in existing.json()}
    assert existing_rows[linked.id]["contact_id"] == shared.id
    assert existing_rows[unlinked.id]["contact_id"] is None
