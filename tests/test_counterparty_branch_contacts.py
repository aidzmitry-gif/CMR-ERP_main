"""A contact belongs to exactly the selected branch, never to another party."""
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from core.domain.models import AuditLog, Contact, Counterparty, CounterpartyBranch


async def test_branch_contacts_are_separate_and_wrong_owner_is_rejected(api, session):
    cp = Counterparty(name="Legacy", legal_name="Legal", unp="600187521")
    session.add(cp)
    await session.flush()
    head = Contact(counterparty_id=cp.id, full_name="Head", is_primary=True)
    session.add(head)
    await session.commit()
    cp_id, revision, head_id = cp.id, cp.revision, head.id
    base = f"/system/mdm/counterparty/{cp_id}"
    created = await api.post(f"{base}/branches", json={
        "expected_legal_entity_revision": revision, "manual": {"name": "Branch"},
        "contacts": [{"full_name": "Branch contact", "phone": "+375291234567", "is_primary": True}],
    })
    assert created.status_code == 201, created.text
    data = (await api.get(base)).json()
    assert [c["id"] for c in data["contacts"]] == [head_id]
    branch = data["branches"][0]
    contact = branch["contacts"][0]
    assert data["contacts"][0]["is_primary"] and contact["is_primary"]
    assert contact["full_name"] == "Branch contact"
    rejected = await api.patch(f"{base}/branches/{branch['id']}", json={
        "expected_legal_entity_revision": data["revision"], "expected_revision": branch["revision"],
        "manual": {"name": "Must rollback"}, "contacts": [{"id": head_id, "full_name": "Stolen"}],
    })
    assert rejected.status_code == 422, rejected.text
    rejected_head = await api.patch(base, json={
        "expected_revision": data["revision"], "contacts": [{"id": contact["id"], "full_name": "Stolen"}],
    })
    assert rejected_head.status_code == 422
    fresh = (await api.get(base)).json()
    assert fresh["branches"][0]["name"] == "Branch"
    assert fresh["branches"][0]["contacts"][0]["full_name"] == "Branch contact"


async def test_database_rejects_branch_contact_with_wrong_parent(session):
    await session.execute(text("PRAGMA foreign_keys=ON"))
    a, b = Counterparty(name="A"), Counterparty(name="B")
    session.add_all([a, b])
    await session.flush()
    branch = CounterpartyBranch(legal_entity_id=a.id, name="Branch")
    session.add(branch)
    await session.flush()
    session.add(Contact(counterparty_id=b.id, branch_id=branch.id, full_name="Wrong"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_switch_primary_contact_is_branch_scoped_and_repeat_is_noop(api, session):
    cp = Counterparty(name="Working", legal_name="Legal", unp="600187521")
    session.add(cp)
    await session.flush()
    session.add(Contact(counterparty_id=cp.id, full_name="Head", is_primary=True))
    await session.commit()
    base = f"/system/mdm/counterparty/{cp.id}"
    response = await api.post(f"{base}/branches", json={
        "expected_legal_entity_revision": cp.revision, "manual": {"name": "Branch"},
        "contacts": [{"full_name": "First", "is_primary": True}, {"full_name": "Second"}],
    })
    assert response.status_code == 201, response.text
    data = (await api.get(base)).json()
    branch = data['branches'][0]
    second = next(c for c in branch['contacts'] if c['full_name'] == 'Second')
    body = {'expected_legal_entity_revision': data['revision'], 'expected_revision': branch['revision'],
            'manual': {}, 'contacts': [{'id': second['id'], 'is_primary': True}]}
    changed = await api.patch(f"{base}/branches/{branch['id']}", json=body)
    assert changed.status_code == 200, changed.text
    fresh = (await api.get(base)).json()
    updated = fresh['branches'][0]
    audit_query = select(func.count()).select_from(AuditLog).where(
        AuditLog.entity_ref == f'counterparty:{cp.id}',
        AuditLog.action.in_(['counterparty.branch.created', 'counterparty.branch.updated']),
    )
    audit_count = await session.scalar(audit_query)
    assert audit_count == 2  # Creation and the actual primary-contact switch.
    assert fresh['contacts'][0]['is_primary'] is True
    assert {c['full_name']: c['is_primary'] for c in updated['contacts']} == {'First': False, 'Second': True}
    body['expected_revision'] = updated['revision']
    body['expected_legal_entity_revision'] = fresh['revision']
    repeated = await api.patch(f"{base}/branches/{branch['id']}", json=body)
    assert repeated.status_code == 200, repeated.text
    assert (await api.get(base)).json()['branches'][0]['revision'] == updated['revision']
    body['contacts'] *= 2
    invalid = await api.patch(f"{base}/branches/{branch['id']}", json=body)
    assert invalid.status_code == 422
    assert (await api.get(base)).json()['branches'][0] == updated
    assert await session.scalar(audit_query) == audit_count
