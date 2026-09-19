"""Own leads preserve explicit numeric relationships and money across conversion."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, OutboxEvent, Sku
from modules.leads.models import Lead
from modules.sales.models import Deal, DealItem
from tests.test_crm_client_create import FOREIGN, OWN, seed


async def client(api, session):
    await seed(session)
    response = await api.post('/sales/clients', headers=OWN,
                              json={'name': 'Own lead buyer', 'request_key': 'own-lead-client'})
    assert response.status_code == 201, response.text
    return response.json()['id']


async def test_own_numeric_cycle_replay_and_no_mdm(api, session):
    client_id = await client(api, session)
    contact = await api.post(f'/sales/clients/{client_id}/contacts', headers=OWN,
                            json={'full_name': 'Buyer contact', 'phone': '+375291112233',
                                  'request_key': 'own-lead-contact'})
    assert contact.status_code == 201, contact.text
    body = {'crm_client_id': client_id, 'crm_contact_id': contact.json()['id'],
            'request_key': 'own-lead-create', 'product': 'Components', 'message': 'Need confirmed order'}
    created = await api.post('/leads', headers=OWN, json=body)
    assert created.status_code == 201, created.text
    lead = created.json()
    assert lead['owner_id'] == 491 and lead['company'] == 'Own lead buyer'
    assert lead['crm_contact_id'] == contact.json()['id']
    assert (await api.post('/leads', headers=OWN, json=body)).json()['id'] == lead['id']
    assert (await api.post('/leads', headers=OWN, json={**body, 'message': 'changed'})).status_code == 409
    session.add(Sku(code='OWN-LEAD-SKU', title='Component', unit='шт'))
    await session.commit()
    sku = await session.scalar(select(Sku).where(Sku.code == 'OWN-LEAD-SKU'))
    url = f"/leads/{lead['id']}"
    items = [{'sku_id': sku.id, 'qty': 1, 'price': p} for p in [125.5, 0]]
    assert (await api.put(url + '/items', headers=OWN, json=items)).status_code == 200
    assert (await api.post(url + '/qualify', headers=OWN)).status_code == 200
    routed = await api.post(url + '/route', headers=OWN,
                            json={'owner_id': 491, 'next_step_note': 'Confirm order',
                                  'next_step_at': '2026-09-15T10:00:00Z'})
    assert routed.status_code == 200, routed.text
    converted = await api.post(url + '/convert', headers=OWN)
    assert converted.status_code == 201, converted.text
    deal_id = converted.json()['deal_id']
    assert deal_id is not None
    assert (await api.post(url + '/convert', headers=OWN)).json() == converted.json()
    deal = await session.get(Deal, deal_id)
    assert (deal.owner_id, deal.crm_client_id, deal.crm_contact_id) == (491, client_id, contact.json()['id'])
    assert deal.next_step == 'Confirm order' and deal.next_step_at == datetime(2026, 9, 15, 10)
    assert float(deal.amount) == 125.5
    prices = (await session.scalars(select(DealItem.unit_price).where(DealItem.deal_id == deal_id).order_by(DealItem.id))).all()
    assert list(map(float, prices)) == [125.5, 0]
    invoice = await api.post(f'/sales/deals/{deal_id}/documents', headers=OWN,
                             json={'kind': 'invoice', 'reserve_mode': 'on_order'})
    assert invoice.status_code == 201, invoice.text
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == 'leads.lead.converted'))).all()
    assert len(events) == 1


@pytest.mark.parametrize('route,method', [('', 'get'), ('/qualify', 'post'), ('/route', 'post'),
                                        ('/convert', 'post'), ('/items', 'get'), ('/items', 'put')])
async def test_foreign_and_unassigned_invisible(api, session, route, method):
    client_id = await client(api, session)
    lead = (await api.post('/leads', headers=OWN, json={'crm_client_id': client_id, 'request_key': 'own-hidden-lead'})).json()
    legacy = Lead(name='Unassigned', status='rejected', reject_reason='не сейчас',
                  snooze_until=datetime.utcnow() - timedelta(days=1))
    session.add(legacy)
    await session.commit()
    for lead_id, headers in [(lead['id'], FOREIGN), (legacy.id, OWN)]:
        kwargs = {'headers': headers}
        if method == 'put':
            kwargs['json'] = []
        response = await getattr(api, method)(f'/leads/{lead_id}{route}', **kwargs)
        assert response.status_code == 404, response.text
    assert (await api.get('/leads', headers=FOREIGN)).json() == []
    await session.refresh(legacy)
    assert legacy.status == 'rejected'


@pytest.mark.parametrize('value', [None, 'omitted', -1, 1e100])
async def test_explicit_price_required_without_mutation(api, session, value):
    client_id = await client(api, session)
    lead = (await api.post('/leads', headers=OWN, json={'crm_client_id': client_id, 'request_key': 'own-price-lead'})).json()
    sku = Sku(code='BOUND-PRICE', title='Synthetic', unit='шт')
    session.add(sku)
    await session.commit()
    row = {'sku_id': sku.id, 'qty': 1}
    if value != 'omitted':
        row['price'] = value
    assert (await api.put(f"/leads/{lead['id']}/items", headers=OWN, json=[row])).status_code == 422
    assert (await api.get(f"/leads/{lead['id']}/items", headers=OWN)).json() == []


async def test_own_unsupported_and_missing_gateway(api, session):
    client_id = await client(api, session)
    for path in ['/leads/plan', '/leads/managers', '/leads/stats/sources']:
        assert (await api.get(path, headers=OWN)).status_code == 403
    assert (await api.post('/leads', headers={'X-User-Roles': 'sales'}, json={})).status_code == 403
    assert (await api.post('/leads', headers=OWN, json={})).status_code == 422
    services = api._transport.app.state.core.services
    services.crm_clients = None
    response = await api.post('/leads', headers=OWN, json={'crm_client_id': client_id, 'request_key': 'gateway-offline'})
    assert response.status_code == 503


async def test_foreign_numeric_links_and_ingress_never_claim_owned_lead(api, session):
    client_id = await client(api, session)
    foreign = await api.post('/sales/clients', headers=FOREIGN,
                             json={'name': 'Foreign buyer', 'request_key': 'foreign-client'})
    contact = await api.post(f"/sales/clients/{foreign.json()['id']}/contacts", headers=FOREIGN,
                             json={'full_name': 'Foreign person', 'phone': '+375291119999', 'request_key': 'foreign-contact'})
    for body, status in [({'crm_client_id': foreign.json()['id']}, 404),
                         ({'crm_client_id': client_id, 'crm_contact_id': contact.json()['id']}, 404),
                         ({'crm_client_id': client_id, 'owner_id': 492}, 403)]:
        response = await api.post('/leads', headers=OWN, json={**body, 'request_key': 'foreign-link-key'})
        assert response.status_code == status, response.text
    response = await api.post('/leads', headers=OWN, json={
        'crm_client_id': client_id, 'phone': '+375291119999', 'request_key': 'own-ingress-key'})
    assert response.status_code == 201, response.text
    from modules.leads.leads import find_last_rejected_by_contact, find_open_lead_by_phone
    assert await find_open_lead_by_phone(session, '+375291119999') is None
    owned = await session.get(Lead, response.json()['id'])
    owned.status = 'rejected'
    await session.commit()
    assert await find_last_rejected_by_contact(session, '+375291119999', None) is None
    assert owned.revived_from_id is None and owned.counterparty_id is None


async def test_tiny_quantity_and_long_next_step_leave_lead_unchanged(api, session):
    client_id = await client(api, session)
    created = await api.post('/leads', headers=OWN, json={'crm_client_id': client_id, 'request_key': 'limits-request'})
    url = f"/leads/{created.json()['id']}"
    sku = Sku(code='BOUND-QTY', title='Synthetic', unit='шт')
    session.add(sku)
    await session.commit()
    response = await api.put(url + '/items', headers=OWN, json=[{'sku_id': sku.id, 'qty': 0.001, 'price': 1}])
    assert response.status_code == 422, response.text
    assert (await api.get(url + '/items', headers=OWN)).json() == []
    assert (await api.post(url + '/qualify', headers=OWN)).status_code == 200
    response = await api.post(url + '/route', headers=OWN, json={'next_step_note': 'x' * 129, 'next_step_at': '2026-09-15T10:00:00Z'})
    assert response.status_code == 422, response.text
    assert (await api.get(url, headers=OWN)).json()['status'] == 'qualified'
