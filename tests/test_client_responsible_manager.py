"""Confirmed manager assignments never grant access or borrow a deal owner."""
from sqlalchemy import func, select

from core.domain.models import AuditLog, Counterparty, User
from modules.sales.clients import MANAGER_FIELD
from modules.sales.models import Deal

OWN = {'X-User': 'responsible-own', 'X-User-Roles': 'sales'}


async def seed(session):
    session.add(User(username='responsible-own', full_name='Confirmed manager', employee_id=491,
                     department='Продажи', role='sales', status='active', deal_visibility='own'))
    client = Counterparty(name='Real company', unp='123456789', requisites={'legal_address': 'Preserve address'})
    session.add(client)
    await session.commit()
    return client


async def test_list_and_crm_card_show_confirmed_names_without_inference(api, session):
    client = await seed(session)
    created = await api.post('/sales/clients', headers=OWN, json={'name': 'CRM company', 'request_key': 'manager-test-1'})
    assert created.status_code == 201
    crm = created.json()
    assert crm['responsible_manager'] == {'employee_id': 491, 'name': 'Confirmed manager', 'active': True}
    card = await api.get(f"/sales/clients/{crm['id']}", headers=OWN)
    assert card.json()['responsible_manager'] == crm['responsible_manager']
    rows = (await api.get('/sales/clients')).json()['rows']
    assert next(row for row in rows if row.get('source') == 'crm')['responsible_manager'] == crm['responsible_manager']
    assert next(row for row in rows if row.get('source') is None and row['id'] == client.id)['responsible_manager'] is None


async def test_assign_preserves_requisites_and_audits_numeric_employee(api, session):
    client = await seed(session)
    url = f'/sales/counterparties/{client.id}/responsible'
    before = (await api.get(url)).json()
    assert before['responsible_manager'] is None and before['can_edit'] is True
    assigned = await api.put(url, json={'employee_id': 491, 'expected_revision': before['revision']})
    assert assigned.status_code == 200
    value = assigned.json()
    assert value['responsible_manager']['name'] == 'Confirmed manager' and value['revision'] > before['revision']
    await session.refresh(client)
    assert client.requisites == {'legal_address': 'Preserve address', MANAGER_FIELD: 491}
    event = await session.scalar(select(AuditLog).where(AuditLog.action == 'counterparty.responsible_manager.changed'))
    assert event.detail == {'previous_employee_id': None, 'employee_id': 491}
    assert (await api.get('/sales/clients')).json()['rows'][0]['responsible_manager']['employee_id'] == 491


async def test_stale_revision_does_not_overwrite_new_assignment(api, session):
    client = await seed(session)
    url = f'/sales/counterparties/{client.id}/responsible'
    assert (await api.put(url, json={'employee_id': 491, 'expected_revision': client.revision})).status_code == 200
    before = await session.scalar(select(func.count()).select_from(AuditLog))
    rejected = await api.put(url, json={'employee_id': None, 'expected_revision': 1})
    assert rejected.status_code == 409 and 'изменилась' in rejected.json()['detail']
    assert (await api.get(url)).json()['responsible_manager']['employee_id'] == 491
    assert await session.scalar(select(func.count()).select_from(AuditLog)) == before


async def test_own_scope_cannot_assign_and_foreign_get_is_hidden(api, session):
    client = await seed(session)
    url = f'/sales/counterparties/{client.id}/responsible'
    assert (await api.get(url, headers=OWN)).status_code == 404
    assert (await api.put(url, headers=OWN, json={'employee_id': 491, 'expected_revision': 1})).status_code == 403
    session.add(Deal(number='EXACT-OWN', title='Visible', counterparty=client.name, owner_id=491))
    await session.commit()
    visible = await api.get(url, headers=OWN)
    assert visible.status_code == 200 and visible.json()['can_edit'] is False
    assert (await api.put(url, headers={'X-User-Roles': 'hr'}, json={'employee_id': 491, 'expected_revision': 1})).status_code == 403


async def test_inactive_manager_rejected_and_explicit_clear_preserves_access(api, session):
    client = await seed(session)
    session.add(User(username='inactive-responsible', full_name='Inactive', employee_id=492,
                     department='Продажи', role='sales', status='inactive', deal_visibility='own'))
    await session.commit()
    url = f'/sales/counterparties/{client.id}/responsible'
    assert (await api.put(url, json={'employee_id': 492, 'expected_revision': 1})).status_code == 422
    assigned = (await api.put(url, json={'employee_id': 491, 'expected_revision': 1})).json()
    cleared = await api.put(url, json={'employee_id': None, 'expected_revision': assigned['revision']})
    assert cleared.status_code == 200 and cleared.json()['responsible_manager'] is None
    user = await session.scalar(select(User).where(User.username == 'responsible-own'))
    assert user.role == 'sales' and user.deal_visibility == 'own' and user.employee_id == 491
    assert (await api.get('/sales/clients', headers=OWN)).json()['total'] == 0
