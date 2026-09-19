"""CRM contacts never alias MDM IDs and remain owned before and after a deal."""
from sqlalchemy import func, select

from core.domain.models import Contact, Counterparty, User
from modules.sales.models import CrmClientContact

OWN = {"X-User": "crm-contact-owner", "X-User-Roles": "sales"}
FOREIGN = {"X-User": "crm-contact-foreign", "X-User-Roles": "sales"}


async def setup_client(api, session):
    session.add_all([User(username='crm-contact-owner', full_name='Owner', employee_id=651,
        department='Продажи', role='sales', status='active', deal_visibility='own'),
        User(username='crm-contact-foreign', full_name='Foreign', employee_id=652,
        department='Продажи', role='sales', status='active', deal_visibility='own')])
    await session.commit()
    response = await api.post('/sales/clients', headers=OWN, json={'name':'Contact buyer', 'request_key':'client-key'})
    assert response.status_code == 201, response.text
    return response.json()['id']


async def test_contact_before_deal_replay_scope_and_numeric_link(api, session):
    client_id = await setup_client(api, session)
    path = f'/sales/clients/{client_id}/contacts'
    payload = {'full_name':'  Анна   Иванова ', 'phone':'+375 (29) 111-22-33',
               'email':' ANNA@EXAMPLE.TEST ', 'is_primary':True, 'request_key':'contact-key'}
    assert (await api.post(path, headers=FOREIGN, json=payload)).status_code == 404
    first = await api.post(path, headers=OWN, json=payload)
    assert first.status_code == 201, first.text
    contact = first.json()
    assert contact['phone'] == '+375291112233' and contact['email'] == 'anna@example.test'
    assert (await api.post(path, headers=OWN, json=payload)).json() == contact
    assert (await api.post(path, headers=OWN, json={**payload, 'full_name':'Changed'})).status_code == 409
    assert (await api.post(path, headers=OWN, json={**payload, 'request_key':'duplicate-key'})).status_code == 409
    assert (await api.get(path, headers=FOREIGN)).status_code == 404
    assert (await api.get('/sales/contacts?q=Анна', headers=FOREIGN)).json() == {'rows':[], 'total':0}
    directory = (await api.get('/sales/contacts?q=Анна', headers=OWN)).json()
    assert directory['total'] == 1 and directory['rows'][0]['crm_client_id'] == client_id
    assert directory['rows'][0]['counterparty_id'] is None and directory['rows'][0]['deal_id'] is None
    deal = (await api.post('/sales/deals', headers=OWN, json={'number':'CRM-CONTACT-DEAL',
        'title':'Order', 'counterparty':'Ignored', 'crm_client_id':client_id})).json()
    assert (await api.get(f"/sales/deals/{deal['id']}/contacts", headers=OWN)).json() == [contact]
    assert (await api.get(f'/sales/clients/{client_id}/deals', headers=FOREIGN)).status_code == 404
    assert (await api.get(f'/sales/clients/{client_id}/deals', headers=OWN)).json()[0]['id'] == deal['id']
    second = await api.post(f"/sales/deals/{deal['id']}/contacts", headers=OWN,
        json={'full_name':'Борис', 'request_key':'second-contact'})
    assert second.status_code == 201 and second.json()['crm_client_id'] == client_id, second.text
    assert await session.scalar(select(func.count()).select_from(Contact)) == 0
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 0


async def test_primary_collision_and_rejected_duplicate_leave_mdm_and_primary_unchanged(api, session):
    client_id = await setup_client(api, session)
    path = f'/sales/clients/{client_id}/contacts'
    a = (await api.post(path, headers=OWN, json={'full_name':'First','is_primary':True,'request_key':'first-key'})).json()
    b = (await api.post(path, headers=OWN, json={'full_name':'Second','request_key':'second-key'})).json()
    cp = Counterparty(name='Unrelated master data')
    session.add(cp)
    await session.flush()
    legacy = Contact(id=b['id'], counterparty_id=cp.id, full_name='Legacy same ID', is_primary=False)
    session.add(legacy)
    await session.commit()
    assert (await api.patch(f"{path}/{b['id']}/primary", headers=FOREIGN)).status_code == 404
    assert (await api.post(path, headers=OWN, json={'full_name':'Second','is_primary':True,'request_key':'another-key'})).status_code == 409
    assert (await api.get(path, headers=OWN)).json()[0]['id'] == a['id']
    assert (await api.patch(f"{path}/{b['id']}/primary", headers=OWN)).status_code == 200
    assert (await api.get(path, headers=OWN)).json()[0]['id'] == b['id']
    await session.refresh(legacy)
    assert legacy.is_primary is False
    assert await session.scalar(select(func.count()).select_from(CrmClientContact).where(CrmClientContact.is_primary.is_(True))) == 1
    assert (await api.patch(f'{path}/9999/primary', headers=OWN)).status_code == 404
