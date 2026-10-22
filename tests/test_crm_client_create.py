"""Standalone clients never acquire legacy master-data records by name."""
import pytest
from sqlalchemy import func, select

from core.domain.models import Contact, Counterparty, Sku, User
from modules.sales.models import CrmClient, Deal, DealDocument, DealItem
from modules.sales.touch_history import SalesTouchHistory

OWN = {"X-User": "client-owner", "X-User-Roles": "sales"}
FOREIGN = {"X-User": "client-foreign", "X-User-Roles": "sales"}


async def seed(session):
    session.add_all([
        User(username="client-owner", full_name="Owner", employee_id=491,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
        User(username="client-foreign", full_name="Foreign", employee_id=492,
             department="Продажи", role="sales", status="active", deal_visibility="own"),
    ])
    await session.commit()


def payload(**changes):
    return {"name": "Independent buyer", "request_key": "client-request-1", **changes}


async def test_create_without_deal_visible_after_new_request_and_hidden_from_foreign(api, session):
    await seed(session)
    created = await api.post("/sales/clients", headers=OWN, json=payload())
    assert created.status_code == 201, created.text
    client = created.json()
    assert client['owner_id'] == 491 and client['counterparty_id'] is None
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0
    assert (await api.get(f"/sales/clients/{client['id']}", headers=OWN)).json() == client
    assert (await api.get(f"/sales/clients/{client['id']}", headers=FOREIGN)).status_code == 404
    for suffix in ("", "?q=Independent", "?owner_id=491", "?limit=1&offset=1"):
        result = await api.get(f"/sales/clients{suffix}", headers=FOREIGN)
        assert result.status_code == 200 and result.json() == {"rows": [], "total": 0}
    own = (await api.get("/sales/clients", headers=OWN)).json()
    assert own['total'] == 1 and own['rows'][0]['source'] == 'crm'
    assert own['rows'][0]['deal_id'] is None
    assert (await api.get("/sales/clients")).json()['total'] == 1


async def test_replay_payload_conflict_and_normalized_duplicates(api, session):
    await seed(session)
    first = await api.post("/sales/clients", headers=OWN, json=payload(name="  Same   buyer  ", unp="123456789"))
    assert first.status_code == 201
    again = await api.post("/sales/clients", headers=OWN, json=payload(name="Same buyer", unp="123456789"))
    assert again.status_code == 201 and again.json() == first.json()
    for data in (payload(name="Changed"), payload(name="SAME BUYER", request_key="second-key"),
                 payload(name="Other", unp="123456789", request_key="third-key")):
        assert (await api.post("/sales/clients", headers=OWN, json=data)).status_code == 409
    assert await session.scalar(select(func.count()).select_from(CrmClient)) == 1
    # A hidden other owner's relationship is independent; it must not reveal a conflict.
    assert (await api.post("/sales/clients", headers=FOREIGN, json=payload(name="Same buyer", unp="123456789"))).status_code == 201


async def test_counterparty_link_uses_active_master_record_and_reuses_per_owner(api, session):
    await seed(session)
    cp = Counterparty(name="1C master buyer", unp="123456789")
    session.add(cp)
    await session.commit()
    basic = await api.get("/sales/buyer-options", headers=OWN)
    assert basic.status_code == 200 and basic.json()["rows"] == [{"id": cp.id, "name": cp.name, "unp": cp.unp}]
    data = {"counterparty_id": cp.id, "name": "Forged name", "unp": "999999999",
            "request_key": "link-request-1"}
    first = await api.post("/sales/clients", headers=OWN, json=data)
    assert first.status_code == 201, first.text
    client = first.json()
    assert client == {"id": client["id"], "name": cp.name, "unp": cp.unp,
                      "owner_id": 491, "counterparty_id": cp.id, "source": "crm",
                      "responsible_manager": {"employee_id": 491, "name": "Owner", "active": True}}
    assert (await api.post("/sales/clients", headers=OWN, json=data)).json() == client
    reused = await api.post("/sales/clients", headers=OWN,
                            json={"counterparty_id": cp.id, "request_key": "link-request-2"})
    assert reused.status_code == 201 and reused.json() == client
    assert (await api.post("/sales/clients", headers=OWN,
                           json={"counterparty_id": cp.id + 1, "request_key": "link-request-1"})).status_code == 409
    foreign = await api.post("/sales/clients", headers=FOREIGN,
                             json={"counterparty_id": cp.id, "request_key": "link-request-1"})
    assert foreign.status_code == 201 and foreign.json()["id"] != client["id"]
    assert foreign.json()["owner_id"] == 492
    assert (await api.get(f"/sales/clients/{client['id']}", headers=FOREIGN)).status_code == 404
    assert await session.scalar(select(func.count()).select_from(CrmClient)) == 2
    await session.refresh(cp)
    assert cp.name == "1C master buyer" and cp.unp == "123456789" and cp.is_active


async def test_counterparty_link_rejects_unknown_archived_and_unlinked_name_collision(api, session):
    await seed(session)
    active = Counterparty(name="Existing name", unp="123456789")
    archived = Counterparty(name="Archived buyer", unp="987654321", is_active=False)
    session.add_all([active, archived])
    await session.flush()
    session.add(Deal(number="LINK-COLLISION", title="Existing relationship",
                     counterparty=active.name, owner_id=491))
    await session.commit()
    for value in (0, "1", active.id + archived.id + 100, archived.id):
        response = await api.post("/sales/clients", headers=OWN,
                                  json={"counterparty_id": value, "request_key": "link-request-1"})
        assert response.status_code == 422, response.text
    unlinked = await api.post("/sales/clients", headers=OWN,
                              json=payload(name=active.name, unp=active.unp))
    assert unlinked.status_code == 201
    conflict = await api.post("/sales/clients", headers=OWN,
                              json={"counterparty_id": active.id, "request_key": "link-request-2"})
    assert conflict.status_code == 409
    assert (await api.get(f"/sales/clients/{unlinked.json()['id']}", headers=OWN)).json()["counterparty_id"] is None
    assert await session.scalar(select(func.count()).select_from(CrmClient)) == 1


@pytest.mark.parametrize("changes,status", [({"owner_id":492},403), ({"counterparty_id":1},422),
    ({"name":"   "},422), ({"unp":"123"},422), ({"request_key":"bad"},422)])
async def test_invalid_or_forged_inputs(api, session, changes, status):
    await seed(session)
    assert (await api.post("/sales/clients", headers=OWN, json=payload(**changes))).status_code == status
    assert await session.scalar(select(func.count()).select_from(CrmClient)) == 0


async def test_director_assignment_requires_active_owner_and_denies_readonly_role(api, session):
    await seed(session)
    assert (await api.post("/sales/clients", json=payload())).status_code == 422
    created = await api.post("/sales/clients", json=payload(owner_id=491))
    assert created.status_code == 201
    assert (await api.get("/sales/clients/owners", headers=OWN)).json() == [{'id':491,'name':'Owner'}]
    assert (await api.post("/sales/clients", headers={"X-User-Roles":"hr"}, json=payload(owner_id=491))).status_code == 403
    owner = await session.scalar(select(User).where(User.employee_id == 491))
    owner.status = "inactive"
    await session.commit()
    assert (await api.post("/sales/clients", json=payload(owner_id=491, request_key="new-key-1"))).status_code == 422
    assert (await api.get("/sales/clients", headers=OWN)).status_code == 403


async def test_numeric_deal_link_does_not_claim_same_name_mdm(api, session):
    await seed(session)
    cp = Counterparty(name="Independent buyer", unp="999999999")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="Private legacy contact"))
    await session.commit()
    client = (await api.post("/sales/clients", headers=OWN, json=payload(unp="123456789"))).json()
    deal_payload = {"number":"CLIENT-DEAL", "title":"Owned client sale", "counterparty":"forged name",
                    "crm_client_id":client['id']}
    assert (await api.post("/sales/deals", headers=FOREIGN, json=deal_payload)).status_code == 404
    assert (await api.post("/sales/deals", headers=OWN, json=deal_payload)).status_code == 422
    selected = Counterparty(name="Confirmed buyer", unp=client["unp"])
    session.add(selected)
    await session.commit()
    deal_payload["counterparty_id"] = selected.id
    response = await api.post("/sales/deals", headers=OWN, json=deal_payload)
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal['crm_client_id'] == client['id'] and deal['counterparty'] == selected.name
    assert deal['counterparty_id'] == selected.id
    for changed in ({'owner_id':492}, {'counterparty':'Legacy company'}, {'owner':'Unconfirmed person'}):
        assert (await api.patch(f"/sales/deals/{deal['id']}", json=changed)).status_code == 422
    assert (await api.get(f"/sales/deals/{deal['id']}/contacts", headers=OWN)).json() == []
    assert (await api.get("/sales/contacts", headers=OWN)).json() == {'rows':[], 'total':0}
    rows = (await api.get("/sales/clients", headers=OWN)).json()['rows']
    assert len(rows) == 1 and rows[0]['deal_id'] == deal['id']
    invoice = await api.post(f"/sales/deals/{deal['id']}/documents", headers=OWN,
                             json={'kind':'invoice', 'reserve_mode':'on_order'})
    # Issuance requires an explicit organization, confirmed buyer and preview.
    # The former two-field request must not manufacture a buyer or a document.
    assert invoice.status_code == 422, invoice.text
    assert await session.scalar(select(func.count()).select_from(DealDocument)) == 0
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 2
    saved_deal = await session.get(Deal, deal['id'])
    assert saved_deal.counterparty_id == selected.id
    assert (await session.get(CrmClient, client['id'])).unp == '123456789'
    await session.refresh(cp)
    assert cp.unp == '999999999'
    history = SalesTouchHistory()
    assert await history.touches(session, cp.id) == []
    assert (await history.summary(session, cp.id))['total'] == 0


@pytest.mark.parametrize('selection', [{'counterparty_id': 1}, {'branch_id': 1}])
async def test_unbound_client_rejects_unconfirmed_party_selection(api, session, selection):
    await seed(session)
    client = (await api.post('/sales/clients', headers=OWN, json=payload())).json()
    response = await api.post('/sales/deals', headers=OWN, json={
        'number': 'UNCONFIRMED', 'title': 'Unconfirmed party',
        'counterparty': client['name'], 'crm_client_id': client['id'], **selection,
    })
    assert response.status_code == 422, response.text
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_repeat_order_uses_numeric_client_not_same_name(api, session):
    await seed(session)
    sku = Sku(code='CRM-REPEAT', title='Client item', unit='шт')
    legacy = Deal(number='CRM-LEGACY', title='Same name', counterparty='Independent buyer', owner_id=491)
    session.add_all([sku, legacy])
    await session.flush()
    session.add(DealItem(deal_id=legacy.id, sku_id=sku.id, qty=7, unit_price=100))
    await session.commit()
    client = (await api.post('/sales/clients', headers=OWN, json=payload())).json()
    selected = Counterparty(name="Confirmed repeat buyer")
    session.add(selected)
    await session.commit()
    data = {'title':'New', 'counterparty':client['name'], 'crm_client_id':client['id'],
            'counterparty_id': selected.id}
    first = (await api.post('/sales/deals', headers=OWN, json={**data, 'number':'CRM-FIRST'})).json()
    assert (await api.get(f"/sales/deals/{first['id']}/repeat-last-order", headers=OWN)).json() == []
    session.add(DealItem(deal_id=first['id'], sku_id=sku.id, qty=2, unit_price=50))
    await session.commit()
    second = (await api.post('/sales/deals', headers=OWN, json={**data, 'number':'CRM-SECOND'})).json()
    rows = (await api.get(f"/sales/deals/{second['id']}/repeat-last-order", headers=OWN)).json()
    assert len(rows) == 1 and rows[0]['qty'] == 2


async def first_buyer_case(api, session, *, client_unp=None):
    await seed(session)
    buyer = Counterparty(name="Legal first buyer", unp="123456789")
    session.add(buyer)
    await session.commit()
    reply = await api.post("/sales/clients", headers=OWN,
                           json=payload(name="Working buyer", unp=client_unp))
    assert reply.status_code == 201, reply.text
    return buyer, reply.json()


async def first_deal(api, client, buyer_id=None, *, number="FIRST-SELECTED"):
    return await api.post("/sales/deals", headers=OWN, json={
        "number": number, "title": "Explicit first buyer", "counterparty": client["name"],
        "crm_client_id": client["id"],
        **({"counterparty_id": buyer_id} if buyer_id is not None else {}),
    })


async def test_buyer_options_basic_fields_search_and_pagination(api, session):
    buyer, client = await first_buyer_case(api, session)
    other = Counterparty(name="Zeta buyer", unp="987654321", requisites={"phone": "PRIVATE", "bank": "PRIVATE"})
    archived = Counterparty(name="Archived buyer", is_active=False)
    merged = Counterparty(name="Merged buyer", merged_into_id=buyer.id)
    session.add_all([other, archived, merged, Contact(counterparty_id=buyer.id, full_name="Private legacy")])
    await session.commit()
    page = await api.get("/sales/buyer-options?limit=1&offset=1", headers=OWN)
    assert page.status_code == 200
    assert page.json() == {"rows": [{"id": other.id, "name": other.name, "unp": other.unp}], "total": 2}
    for query in ("Legal", buyer.unp):
        result = (await api.get("/sales/buyer-options", headers=OWN, params={"q": query})).json()
        assert result == {"rows": [{"id": buyer.id, "name": buyer.name, "unp": buyer.unp}], "total": 1}
    for query in ("limit=0", "limit=101", "offset=-1"):
        assert (await api.get("/sales/buyer-options?" + query, headers=OWN)).status_code == 422
    assert (await api.get(f"/sales/counterparties/{buyer.id}/responsible", headers=OWN)).status_code == 404
    assert (await api.get("/sales/contacts", headers=OWN)).json() == {"rows": [], "total": 0}
    assert (await api.get(f"/sales/clients/{client['id']}", headers=FOREIGN)).status_code == 404
    assert (await api.get(f"/sales/clients/{client['id']}/deals", headers=FOREIGN)).status_code == 404


async def test_buyer_options_does_not_grant_capability_to_readonly_or_unknown_actor(api, session):
    await seed(session)
    assert (await api.get("/sales/buyer-options", headers={"X-User": "hr-user", "X-User-Roles": "hr"})).status_code == 403
    assert (await api.get("/sales/buyer-options", headers={"X-User": "missing", "X-User-Roles": "sales"})).status_code == 403


async def test_first_buyer_selection_rechecks_inactive_master(api, session):
    buyer, client = await first_buyer_case(api, session)
    buyer_id = buyer.id
    assert (await api.get("/sales/buyer-options", headers=OWN)).json()["rows"][0]["id"] == buyer_id
    buyer.is_active = False
    await session.commit()
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0


async def test_first_buyer_selection_rechecks_merged_master(api, session):
    buyer, client = await first_buyer_case(api, session)
    buyer_id = buyer.id
    target = Counterparty(name="Merged target")
    session.add(target)
    await session.flush()
    buyer.merged_into_id = target.id
    await session.commit()
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None


async def test_first_buyer_binding_preserves_working_client_contacts_and_request(api, session):
    buyer, client = await first_buyer_case(api, session, client_unp="123456789")
    saved = await session.get(CrmClient, client["id"])
    before = (saved.name, saved.name_key, saved.unp, saved.request_key, saved.request_hash)
    contact = await api.post(f"/sales/clients/{client['id']}/contacts", headers=OWN,
                             json={"full_name": "Own contact", "request_key": "first-contact"})
    assert contact.status_code == 201
    session.add(Contact(counterparty_id=buyer.id, full_name="Private master contact"))
    await session.commit()
    response = await first_deal(api, client, buyer.id)
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal["crm_client_id"] == client["id"] and deal["counterparty_id"] == buyer.id
    assert deal["counterparty"] == buyer.name
    await session.refresh(saved)
    assert (saved.name, saved.name_key, saved.unp, saved.request_key, saved.request_hash) == before
    assert saved.counterparty_id == buyer.id
    assert (await api.get(f"/sales/deals/{deal['id']}/contacts", headers=OWN)).json() == [contact.json()]
    assert (await api.get(f"/sales/clients/{client['id']}/contacts", headers=FOREIGN)).status_code == 404
    assert (await api.get(f"/sales/deals/{deal['id']}/history", headers=FOREIGN)).status_code == 404
    assert (await api.get("/sales/contacts", headers=OWN)).json()["total"] == 1


async def test_first_buyer_selection_is_required_even_when_names_match(api, session):
    _, client = await first_buyer_case(api, session)
    assert (await first_deal(api, client)).status_code == 422
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None
    assert await session.scalar(select(func.count()).select_from(Deal)) == 0


async def test_first_buyer_binding_rejects_mismatched_or_unconfirmed_unp(api, session):
    buyer, client = await first_buyer_case(api, session, client_unp="999999999")
    buyer_id = buyer.id
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    buyer = await session.get(Counterparty, buyer_id)
    buyer.unp = None
    await session.commit()
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    assert (await session.get(CrmClient, client["id"])).unp == "999999999"
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None


async def test_first_buyer_cannot_replace_existing_confirmed_client_binding(api, session):
    buyer, client = await first_buyer_case(api, session)
    first = await first_deal(api, client, buyer.id)
    assert first.status_code == 201
    other = Counterparty(name="Different buyer")
    session.add(other)
    await session.commit()
    assert (await first_deal(api, client, other.id, number="REBOUND")).status_code == 422
    assert (await session.get(CrmClient, client["id"])).counterparty_id == first.json()["counterparty_id"]
    repeated = await first_deal(api, client, number="SAME-BUYER")
    assert repeated.status_code == 201 and repeated.json()["counterparty_id"] == first.json()["counterparty_id"]


async def test_first_buyer_never_rebinds_unbound_client_with_prior_deal(api, session):
    buyer, client = await first_buyer_case(api, session)
    buyer_id = buyer.id
    session.add(Deal(number="PRIOR-CLIENT", title="Historical", counterparty=client["name"],
                     owner_id=492, crm_client_id=client["id"]))
    await session.commit()
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None
    assert await session.scalar(select(func.count()).select_from(Deal)) == 1


async def test_first_buyer_binding_rolls_back_on_duplicate_deal_number(api, session):
    buyer, client = await first_buyer_case(api, session)
    buyer_id = buyer.id
    session.add(Deal(number="FIRST-SELECTED", title="Existing", counterparty="Other", owner_id=491))
    await session.commit()
    assert (await first_deal(api, client, buyer_id)).status_code == 409
    assert (await session.get(CrmClient, client["id"])).counterparty_id is None
    assert await session.scalar(select(func.count()).select_from(Deal)) == 1
