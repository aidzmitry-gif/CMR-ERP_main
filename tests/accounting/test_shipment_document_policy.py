from copy import deepcopy

import pytest
from sqlalchemy import select

from modules.accounting.models import Policy


def scenario(kind="ttn"):
    return {
        "kind": kind,
        "exchange_mode": "electronic",
        "form_version": f"Synthetic {kind} form v1",
        "numbering_rule": "Synthetic reviewed numbering rule",
        "signing_rule": "Synthetic approved signing rule",
        "exchange_rule": "Synthetic external exchange route",
        "evidence": "Synthetic reviewed policy evidence",
    }


def body():
    return {
        "effective_from": "2026-10-01",
        "reference": "Synthetic shipment-document policy",
        "inventory_method": "specific",
        "allocation_basis": "direct_cost",
        "depreciation_method": "straight_line",
        "normative_reference": "Synthetic local policy evidence",
        "shipment_documents": {"scenarios": [scenario()]},
    }


async def test_shipment_document_policy_is_versioned_explicit_and_immutable(client, db, book):
    path = f"/accounting/organizations/{book[0]}/policies"
    response = await client.post(path, json=body())
    assert response.status_code == 201, response.text
    assert response.json()["shipment_documents"] == body()["shipment_documents"]
    row = await db.get(Policy, response.json()["id"])
    row.shipment_documents = {"scenarios": [scenario("tn")]}
    with pytest.raises(ValueError, match="immutable"):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize("scenarios", [
    [],
    [scenario("tn"), scenario("tn")],
    [{key: value for key, value in scenario().items() if key != "evidence"}],
    [{**scenario(), "exchange_mode": "automatic"}],
])
async def test_invalid_shipment_document_policy_creates_no_version(client, db, book, scenarios):
    data = deepcopy(body())
    data["shipment_documents"] = {"scenarios": scenarios}
    response = await client.post(f"/accounting/organizations/{book[0]}/policies", json=data)
    assert response.status_code == 422, response.text
    assert len((await db.scalars(select(Policy).where(Policy.organization_id == book[0]))).all()) == 1
