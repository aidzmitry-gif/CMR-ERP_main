"""Standalone clients never acquire legacy master-data records by name."""
import pytest
from sqlalchemy import func, select

from core.domain.models import Contact, Counterparty, Sku, User
from modules.sales.models import CrmClient, Deal, DealItem
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
    response = await api.post("/sales/deals", headers=OWN, json=deal_payload)
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal['crm_client_id'] == client['id'] and deal['counterparty'] == client['name']
    for changed in ({'owner_id':492}, {'counterparty':'Legacy company'}, {'owner':'Unconfirmed person'}):
        assert (await api.patch(f"/sales/deals/{deal['id']}", json=changed)).status_code == 422
    assert (await api.get(f"/sales/deals/{deal['id']}/contacts", headers=OWN)).json() == []
    assert (await api.get("/sales/contacts", headers=OWN)).json() == {'rows':[], 'total':0}
    rows = (await api.get("/sales/clients", headers=OWN)).json()['rows']
    assert len(rows) == 1 and rows[0]['deal_id'] == deal['id']
    invoice = await api.post(f"/sales/deals/{deal['id']}/documents", headers=OWN,
                             json={'kind':'invoice', 'reserve_mode':'on_order'})
    assert invoice.status_code == 201, invoice.text
    snapshot = (await api.get(f"/sales/documents/{invoice.json()['id']}/snapshot", headers=OWN)).json()
    assert snapshot['buyer']['unp'] == '123456789'
    assert cp.unp == '999999999'
    history = SalesTouchHistory()
    assert await history.touches(session, cp.id) == []
    assert (await history.summary(session, cp.id))['total'] == 0


async def test_repeat_order_uses_numeric_client_not_same_name(api, session):
    await seed(session)
    sku = Sku(code='CRM-REPEAT', title='Client item', unit='шт')
    legacy = Deal(number='CRM-LEGACY', title='Same name', counterparty='Independent buyer', owner_id=491)
    session.add_all([sku, legacy])
    await session.flush()
    session.add(DealItem(deal_id=legacy.id, sku_id=sku.id, qty=7, unit_price=100))
    await session.commit()
    client = (await api.post('/sales/clients', headers=OWN, json=payload())).json()
    data = {'title':'New', 'counterparty':client['name'], 'crm_client_id':client['id']}
    first = (await api.post('/sales/deals', headers=OWN, json={**data, 'number':'CRM-FIRST'})).json()
    assert (await api.get(f"/sales/deals/{first['id']}/repeat-last-order", headers=OWN)).json() == []
    session.add(DealItem(deal_id=first['id'], sku_id=sku.id, qty=2, unit_price=50))
    await session.commit()
    second = (await api.post('/sales/deals', headers=OWN, json={**data, 'number':'CRM-SECOND'})).json()
    rows = (await api.get(f"/sales/deals/{second['id']}/repeat-last-order", headers=OWN)).json()
    assert len(rows) == 1 and rows[0]['qty'] == 2
