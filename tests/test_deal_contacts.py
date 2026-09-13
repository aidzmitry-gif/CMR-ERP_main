"""Legacy deal contact endpoints cannot bypass branch contact ownership."""
from core.domain.models import Contact, Counterparty, CounterpartyBranch
from modules.sales.models import Deal


async def test_branch_phone_resolves_only_its_deal_and_shared_phone_is_ambiguous(session):
    from modules.sales.calls import resolve_owner
    cp = Counterparty(name="Shared name")
    session.add(cp)
    await session.flush()
    first = CounterpartyBranch(legal_entity_id=cp.id, name="First")
    second = CounterpartyBranch(legal_entity_id=cp.id, name="Second")
    session.add_all([first, second])
    await session.flush()
    contact = Contact(counterparty_id=cp.id, branch_id=first.id, full_name="Branch contact", phone="+375291234567")
    target = Deal(number="CALL-B1", title="First", counterparty_id=cp.id, branch_id=first.id, counterparty=cp.name, owner="First owner")
    session.add_all([contact, target,
        Deal(number="CALL-H", title="Head", counterparty_id=cp.id, counterparty=cp.name, owner="Head owner"),
        Deal(number="CALL-B2", title="Second", counterparty_id=cp.id, branch_id=second.id, counterparty=cp.name, owner="Second owner")])
    await session.flush()
    result = await resolve_owner(session, contact.phone)
    assert result["deal_id"] == target.id and result["owner"] == "First owner"
    session.add(Contact(counterparty_id=cp.id, branch_id=second.id, full_name="Shared number", phone=contact.phone))
    await session.flush()
    result = await resolve_owner(session, contact.phone)
    assert result["deal_id"] is None and result["counterparty_id"] is None and result["owner"] == ""


async def test_deal_contact_scope_and_legacy_primary_do_not_cross_branches(api, session):
    cp = Counterparty(name="Head", legal_name="Legal")
    session.add(cp)
    await session.flush()
    branch = CounterpartyBranch(legal_entity_id=cp.id, name="Branch")
    session.add(branch)
    await session.flush()
    head_contact = Contact(counterparty_id=cp.id, full_name="Head contact")
    branch_contact = Contact(counterparty_id=cp.id, branch_id=branch.id, full_name="Branch contact", is_primary=True)
    head_deal = Deal(number="CONTACT-H", title="Head", counterparty_id=cp.id, counterparty=cp.name)
    branch_deal = Deal(number="CONTACT-B", title="Branch", counterparty_id=cp.id, branch_id=branch.id, counterparty=cp.name)
    session.add_all([head_contact, branch_contact, head_deal, branch_deal])
    await session.commit()
    head_id, branch_id = head_contact.id, branch_contact.id
    for deal, expected in ((head_deal, head_id), (branch_deal, branch_id)):
        response = await api.get(f"/sales/deals/{deal.id}/contacts")
        assert response.status_code == 200, response.text
        assert [c["id"] for c in response.json()] == [expected]
    assert (await api.patch(f"/sales/contacts/{head_id}/primary")).status_code == 200
    assert (await api.patch(f"/sales/contacts/{branch_id}/primary")).status_code == 422
    response = await api.post(f"/sales/deals/{branch_deal.id}/contacts", json={"full_name": "Wrong scope", "is_primary": True})
    assert response.status_code == 422
    session.expire_all()
    assert (await session.get(Contact, branch_id)).is_primary is True
    assert (await session.get(Contact, head_id)).is_primary is True
