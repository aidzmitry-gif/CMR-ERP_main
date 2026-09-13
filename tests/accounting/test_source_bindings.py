import pytest
from sqlalchemy import func, select

from core.services.auth import CurrentUser, get_current_user
from modules.accounting.models import AccessGrant, Audit, SourceBinding
from modules.finance.models import BankTransaction
from modules.logistics.models import ImportShipment

DATA = {"source_type": "wms_receipt", "source_id": 42, "ownership": "own", "evidence": "Synthetic ownership approval by chief"}


async def test_explicit_binding_replays_and_cannot_change_owner(client, db, book):
    path = f"/accounting/organizations/{book[0]}/source-bindings"
    first = await client.post(path, json=DATA)
    repeat = await client.post(path, json=DATA)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert first.json()["organization_id"] == book[0]
    assert first.json()["actor"] == "tester"
    assert len((await client.get(path)).json()) == 1
    assert (await client.post(path, json={**DATA, "ownership": "customer"})).status_code == 409
    assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "source_ownership_recorded")) == 1
    other = await client.post("/accounting/organizations", json={"name": "Other synthetic", "unp": "999999998"})
    assert other.status_code == 201
    assert (await client.post(f"/accounting/organizations/{other.json()['id']}/source-bindings", json=DATA)).status_code == 409


async def test_binding_requires_chief_and_does_not_expose_other_books(client, db, book):
    path = f"/accounting/organizations/{book[0]}/source-bindings"
    db.add(AccessGrant(organization_id=book[0], subject="reader1", role="reader"))
    db.add(AccessGrant(organization_id=book[0], subject="accountant1", role="accountant"))
    await db.commit()
    for username in ["reader1", "accountant1", "stranger"]:
        client.test_app.dependency_overrides[get_current_user] = lambda name=username: CurrentUser(name, ["director"])
        assert (await client.post(path, json=DATA)).status_code == 403
    assert (await client.get(path)).status_code == 403
    assert await db.scalar(select(func.count()).select_from(SourceBinding)) == 0


async def test_logistics_import_requires_existing_source_and_keeps_explicit_owner(client, db, book):
    missing = {"source_type": "logistics_import", "source_id": 999, "ownership": "own",
               "evidence": "Synthetic import ownership approval"}
    assert (await client.post(f"/accounting/organizations/{book[0]}/source-bindings", json=missing)).status_code == 404
    source = ImportShipment(supplier="Synthetic supplier", number="IMP-1", cargo="SKU-1", po_ref="purchase:1")
    db.add(source)
    await db.commit()
    payload = {**missing, "source_id": source.id}
    response = await client.post(f"/accounting/organizations/{book[0]}/source-bindings", json=payload)
    assert response.status_code == 201
    assert response.json()["source_type"] == "logistics_import"
    assert response.json()["organization_id"] == book[0]


async def test_bank_import_binding_requires_existing_source_and_own_company(client, db, book):
    path = f"/accounting/organizations/{book[0]}/source-bindings"
    missing = {"source_type": "finance_bank_transaction", "source_id": 999, "ownership": "own",
               "evidence": "Synthetic bank source ownership approval"}
    assert (await client.post(path, json=missing)).status_code == 404
    source = BankTransaction(ext_id="SOURCE-BANK-1", amount="10.00", currency="BYN")
    db.add(source)
    await db.commit()
    payload = {**missing, "source_id": source.id}
    assert (await client.post(path, json={**payload, "ownership": "customer"})).status_code == 422
    response = await client.post(path, json=payload)
    assert response.status_code == 201
    assert response.json()["source_type"] == "finance_bank_transaction"


@pytest.mark.parametrize("patch", [{"source_id": True}, {"source_id": "42"}, {"source_id": 0}, {"ownership": ""}, {"evidence": ""}])
async def test_no_implicit_source_or_owner(client, book, patch):
    result = await client.post(f"/accounting/organizations/{book[0]}/source-bindings", json={**DATA, **patch})
    assert result.status_code == 422
