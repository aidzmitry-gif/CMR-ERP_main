"""Stable identity wins over colliding or renamed display text."""
import pytest
from fastapi import HTTPException

from core.domain.models import Counterparty, CounterpartyBranch, Sku
from modules.sales.models import Deal, DealDocument, DealItem, PriceQuote
from modules.sales.party_identity import party_for_deal, prepare_party_change
from modules.sales.touch_history import SalesTouchHistory


async def test_rename_and_same_names_never_mix_history(session):
    first, second = Counterparty(name="Same"), Counterparty(name="Same")
    session.add_all([first, second])
    await session.flush()
    a = Deal(number="ID-A", title="A", counterparty="Same", counterparty_id=first.id)
    b = Deal(number="ID-B", title="B", counterparty="Same", counterparty_id=second.id)
    unknown = Deal(number="ID-U", title="Unknown", counterparty="Same")
    session.add_all([a, b, unknown])
    await session.flush()
    history = SalesTouchHistory()
    assert [t["ref"] for t in await history.touches(session, first.id)] == ["ID-A"]
    assert await party_for_deal(session, unknown) is None
    with pytest.raises(HTTPException) as conflict:
        await party_for_deal(session, unknown, create=True)
    assert conflict.value.status_code == 409
    first.name = "Renamed"
    await session.flush()
    assert (await party_for_deal(session, a)).id == first.id
    assert (await history.summary(session, first.id))["deals"] == 1
    assert (await history.summary(session, second.id))["deals"] == 1
    assert await party_for_deal(session, unknown) is None


async def test_branch_selection_validates_parent_and_clears_on_party_change(session):
    first, second = Counterparty(name="First"), Counterparty(name="Second")
    session.add_all([first, second])
    await session.flush()
    branch = CounterpartyBranch(legal_entity_id=first.id, name="Branch")
    session.add(branch)
    await session.flush()
    data = {"counterparty": "untrusted label", "counterparty_id": first.id, "branch_id": branch.id}
    await prepare_party_change(session, data)
    assert data["counterparty"] == "First"
    deal = Deal(number="ID-SELECT", title="Selected", **data)
    update = {"counterparty_id": second.id}
    await prepare_party_change(session, update, deal=deal)
    assert update["branch_id"] is None
    with pytest.raises(HTTPException) as wrong_parent:
        await prepare_party_change(session, {"counterparty_id": second.id, "branch_id": branch.id})
    assert wrong_parent.value.status_code == 422


async def test_api_create_uses_id_and_does_not_trust_label(api, session):
    cp = Counterparty(name="Canonical", display_name="Display")
    session.add(cp)
    await session.commit()
    response = await api.post("/sales/deals", json={
        "number": "PARTY-API-1", "title": "Identity", "counterparty": "Wrong label", "counterparty_id": cp.id,
    })
    assert response.status_code == 201, response.text
    assert response.json()["counterparty_id"] == cp.id
    assert response.json()["counterparty"] == "Display"


async def test_document_snapshot_keeps_parent_and_branch_after_rename(api, session):
    cp = Counterparty(name="Legacy legal", display_name="Display", legal_name="Legal company", unp="600187521")
    session.add(cp)
    await session.flush()
    branch = CounterpartyBranch(legal_entity_id=cp.id, name="Branch A", tax_mode="shared", portal_branch_code="0001")
    session.add(branch)
    await session.commit()
    response = await api.post("/sales/deals", json={
        "number": "PARTY-DOC-1", "title": "Identity", "counterparty": "Wrong label",
        "counterparty_id": cp.id, "branch_id": branch.id, "amount": 120,
    })
    assert response.status_code == 201, response.text
    created = await api.post(f"/sales/deals/{response.json()['id']}/documents", json={"kind": "order"})
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    from copy import deepcopy
    doc = await session.get(DealDocument, doc_id)
    original = deepcopy(doc.snapshot_json)
    cp.legal_name, cp.display_name, branch.name = "Renamed legal", "Renamed display", "Branch renamed"
    await session.commit()
    await session.refresh(doc)
    assert doc.snapshot_json == original
    assert doc.snapshot_json["buyer"]["name"] == "Legal company"
    party = doc.snapshot_json["party"]
    assert party["legal_entity_id"] == cp.id and party["branch_id"] == branch.id
    assert party["branch_name"] == "Branch A" and party["portal_branch_code"] == "0001"
    assert party["legal_entity_revision"] < cp.revision


async def test_merge_rejects_linked_deals_and_preserves_identity(api, session):
    first, second = Counterparty(name="First"), Counterparty(name="Second")
    session.add_all([first, second])
    await session.flush()
    session.add(Deal(number="MERGE-ID", title="Keep", counterparty="First", counterparty_id=first.id))
    await session.commit()
    response = await api.post("/system/mdm/merge", json={"survivor_id": second.id, "duplicate_id": first.id})
    assert response.status_code == 422, response.text
    assert "связанные сделки" in response.json()["detail"]
    await session.refresh(first)
    assert first.is_active and first.merged_into_id is None


async def test_repeat_order_does_not_mix_same_names_or_branches(api, session):
    first, second = Counterparty(name="Same"), Counterparty(name="Same")
    sku = Sku(code="ID-REPEAT", title="Item", unit="шт")
    session.add_all([first, second, sku])
    await session.flush()
    branch = CounterpartyBranch(legal_entity_id=first.id, name="Branch")
    session.add(branch)
    await session.flush()
    previous = Deal(number="REPEAT-OWN", title="Own", counterparty="Same", counterparty_id=first.id)
    other = Deal(number="REPEAT-OTHER", title="Other", counterparty="Same", counterparty_id=second.id)
    branch_deal = Deal(number="REPEAT-BRANCH", title="Branch", counterparty="Same", counterparty_id=first.id, branch_id=branch.id)
    current = Deal(number="REPEAT-NOW", title="Current", counterparty="Same", counterparty_id=first.id)
    session.add_all([previous, other, branch_deal, current])
    await session.flush()
    session.add_all([DealItem(deal_id=d.id, sku_id=sku.id, qty=q) for d, q in [(previous, 1), (other, 2), (branch_deal, 3)]])
    await session.commit()
    response = await api.get(f"/sales/deals/{current.id}/repeat-last-order")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1 and float(response.json()[0]["qty"]) == 1


async def test_new_document_rejects_unresolved_legacy_party(api, session):
    deal = Deal(number="UNRESOLVED-DOC", title="Legacy", counterparty="Unknown", amount=120)
    session.add(deal)
    await session.commit()
    response = await api.post(f"/sales/deals/{deal.id}/documents", json={"kind": "order"})
    assert response.status_code == 409
    assert "по ID" in response.json()["detail"]


async def test_invoice_requires_confirmed_price_instead_of_legacy_history(session, monkeypatch):
    first, second = Counterparty(name="Same price name"), Counterparty(name="Same price name")
    sku = Sku(code="AMBIG-PRICE", title="Item", unit="шт")
    session.add_all([first, second, sku])
    await session.flush()
    deal = Deal(number="AMBIG-PRICE", title="Legacy quote", counterparty=first.name, counterparty_id=first.id)
    session.add(deal)
    await session.flush()
    session.add_all([DealItem(deal_id=deal.id, sku_id=sku.id, qty=1),
                     PriceQuote(sku_code=sku.code, counterparty=first.name, price=100)])
    await session.commit()
    from modules.sales.documents import capture
    from modules.sales import routes
    monkeypatch.setattr(routes, '_seller_with_facsimile', lambda core, branding: {})
    doc = DealDocument(deal_id=deal.id, kind="invoice", number="LEGACY-AMBIG", amount=100)
    session.add(doc)
    await session.flush()
    with pytest.raises(HTTPException) as conflict:
        await capture(session, None, doc)
    assert conflict.value.status_code == 422
    assert "подтвердите" in conflict.value.detail
    assert doc.snapshot_json is None


@pytest.mark.parametrize("patch", [{"counterparty_id": None}, {"counterparty": ""}, {"counterparty": "   "}])
async def test_patch_cannot_erase_resolved_identity(api, session, patch):
    cp = Counterparty(name="Keep identity")
    session.add(cp)
    await session.flush()
    deal = Deal(number="KEEP-PARTY", title="Keep", counterparty=cp.name, counterparty_id=cp.id)
    session.add(deal)
    await session.commit()
    response = await api.patch(f"/sales/deals/{deal.id}", json=patch)
    assert response.status_code == 422, response.text
    await session.refresh(deal)
    assert deal.counterparty_id == cp.id and deal.counterparty == cp.name
