"""CRM party identity and immutable accounting buyer agree across integration."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from core.domain.models import Counterparty, CounterpartyBranch
from modules.sales.client_document_register import preview_snapshot
from modules.sales.models import Deal, DealDocument
from tests.test_invoice_issuance import command, create, seed


async def test_bound_buyer_cannot_be_replaced_by_generic_party_patch(api, session):
    ids, base = await seed(api, session)
    other = Counterparty(name="Other buyer")
    session.add(other)
    await session.commit()
    response = await api.patch(f"/sales/deals/{ids['deal']}", json={"counterparty_id": other.id})
    assert response.status_code == 409, response.text
    deal = await session.get(Deal, ids["deal"])
    await session.refresh(deal)
    assert deal.counterparty_id is None
    deal.counterparty_id = other.id
    await session.commit()
    with pytest.raises(HTTPException) as conflict:
        await preview_snapshot(session, ids["org"], deal, ids["buyer"])
    assert conflict.value.status_code == 409
    response = await api.post(f"/sales/deals/{ids['deal']}/invoice-preview", json=base)
    assert response.status_code == 409, response.text


async def test_invoice_freezes_branch_identity_and_legal_name(api, session):
    ids, base = await seed(api, session)
    buyer = await session.get(Counterparty, ids["buyer"])
    buyer.legal_name = "Legal buyer"
    branch = CounterpartyBranch(legal_entity_id=buyer.id, name="Brest", portal_branch_code="0001", tax_mode="shared")
    session.add(branch)
    await session.flush()
    deal = await session.get(Deal, ids["deal"])
    deal.counterparty_id, deal.branch_id = buyer.id, branch.id
    await session.commit()
    cmd, _ = await command(api, ids, base)
    response = await create(api, ids, cmd)
    assert response.status_code == 201, response.text
    doc = await session.scalar(select(DealDocument).where(DealDocument.id == response.json()["document"]["id"]))
    original = doc.snapshot_json["buyer"]
    assert original["name"] == "Legal buyer"
    assert original["branch"]["portal_branch_code"] == "0001"
    branch.name = "Renamed"
    buyer.legal_name = "Changed legal name"
    await session.commit()
    await session.refresh(doc)
    assert doc.snapshot_json["buyer"] == original
