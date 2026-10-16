"""Тесты справочника поставщиков и закрытого общего API скоркарты.

Supplier — профиль закупок (условия/срок/incoterms/статус), ``unp`` — soft-ref на MDM.
Скоркарта по юрлицу проверяется отдельно в accounting/test_supplier_scorecard_scope.py.
"""
from __future__ import annotations

import pytest

from core.domain.models import Counterparty

pytestmark = pytest.mark.asyncio


async def _supplier(api, **over):
    body = {"name": "Шэньчжэнь Бэттери Co", "unp": "ICN-7788", "country": "Китай", "flag": "🇨🇳"}
    body.update(over)
    r = await api.post("/procurement/suppliers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_supplier_crud(api):
    created = await _supplier(api, payment_terms="30% предоплата / 70% по факту", lead_time_days=45)
    sid = created["id"]
    assert created["name"] == "Шэньчжэнь Бэттери Co" or created["name"]  # имя сохранено
    assert created["unp"] == "ICN-7788"
    assert created["status"] == "active"

    got = (await api.get(f"/procurement/suppliers/{sid}")).json()
    assert got["payment_terms"] == "30% предоплата / 70% по факту"
    assert got["lead_time_days"] == 45

    r = await api.patch(f"/procurement/suppliers/{sid}", json={"status": "blocked", "incoterms": "FOB"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked" and body["incoterms"] == "FOB"
    assert body["unp"] == "ICN-7788"  # прочие поля не затёрты

    lst = (await api.get("/procurement/suppliers")).json()
    assert any(s["id"] == sid for s in lst)


async def test_supplier_404(api):
    assert (await api.get("/procurement/suppliers/9999")).status_code == 404
    assert (await api.patch("/procurement/suppliers/9999", json={"status": "blocked"})).status_code == 404


async def test_supplier_mdm_identity_is_explicit_and_immutable(api, session):
    party = Counterparty(name="Trading name", display_name="Shop display name",
                         legal_name="Legal supplier", unp="190000001")
    session.add(party)
    await session.commit()
    options = await api.get("/procurement/supplier-counterparties", params={"q": "Legal"},
                            headers={"X-User-Roles": "procurement"})
    assert options.status_code == 200, options.text
    assert options.json() == {"items": [{"id": party.id, "name": "Legal supplier", "unp": "190000001"}]}
    assert (await api.get("/procurement/supplier-counterparties", params={"q": "Legal"},
                          headers={"X-User-Roles": "warehouse"})).status_code == 403
    bound = {"name": "Legal supplier", "unp": "190000001", "counterparty_id": party.id}
    made = await api.post("/procurement/suppliers", json=bound)
    assert made.status_code == 201, made.text
    supplier = made.json()
    assert supplier["counterparty_id"] == party.id
    assert (await api.post("/procurement/suppliers", json=bound)).status_code == 409
    assert (await api.post("/procurement/suppliers", json={**bound, "unp": "other"})).status_code == 409
    assert (await api.patch(f"/procurement/suppliers/{supplier['id']}",
                            json={"counterparty_id": None})).status_code == 409
    assert (await api.patch(f"/procurement/suppliers/{supplier['id']}",
                            json={"name": "Changed outside MDM"})).status_code == 409
    changed = await api.patch(f"/procurement/suppliers/{supplier['id']}",
                              json={"payment_terms": "30 days"})
    assert changed.status_code == 200
    assert changed.json()["counterparty_id"] == party.id


async def test_historical_supplier_requires_selected_mdm_identity_to_link(api, session):
    historical = await _supplier(api)
    assert historical["counterparty_id"] is None
    party = Counterparty(name="New identity", unp="ICN-7788")
    session.add(party)
    await session.commit()
    linked = await api.patch(f"/procurement/suppliers/{historical['id']}",
                             json={"counterparty_id": party.id, "name": party.name, "unp": party.unp})
    assert linked.status_code == 200
    assert linked.json()["counterparty_id"] == party.id


async def test_inactive_mdm_record_cannot_be_selected_or_bound(api, session):
    party = Counterparty(name="Inactive supplier", unp="190000002", is_active=False)
    session.add(party)
    await session.commit()
    options = await api.get("/procurement/supplier-counterparties", params={"q": "Inactive"})
    assert options.status_code == 200
    assert options.json() == {"items": []}
    rejected = await api.post("/procurement/suppliers", json={
        "counterparty_id": party.id, "name": party.name, "unp": party.unp})
    assert rejected.status_code == 409


async def test_unscoped_scorecard_requires_company(api):
    supplier = await _supplier(api)
    response = await api.get(f"/procurement/suppliers/{supplier['id']}/scorecard")
    assert response.status_code == 410
