from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.accounting.test_shipment_preview import fixture


@pytest.mark.parametrize("change,field", [
    ({"policy_id": None}, "policy_id"),
    ({"expected_act_digest": "invalid"}, "expected_act_digest"),
    ({"allocations": []}, "allocations"),
    ({"receipt": {"snapshot": {}}}, "receipt"),
])
async def test_invalid_plan_rejected_before_warehouse_access(
    client, db, book, posting, change, field,
):
    act, raw = await fixture(db, book, posting)
    gateway = AsyncMock()
    client.test_app.state.core.services.wms_reservations = gateway
    client.test_app.state.core.services.sales_source = SimpleNamespace()
    body = {**deepcopy(raw), **change}
    response = await client.post(
        f"/accounting/organizations/{book[0]}/shipments/{act['source_key']}/preview",
        json=body,
    )
    assert response.status_code == 422, response.text
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    gateway.accounting_shipment_source.assert_not_awaited()


async def test_valid_plan_uses_server_act_and_remains_preview(client, db, book, posting):
    act, body = await fixture(db, book, posting)
    gateway = AsyncMock()
    gateway.accounting_shipment_source.return_value = {"receipt": act}
    client.test_app.state.core.services.wms_reservations = gateway
    client.test_app.state.core.services.sales_source = SimpleNamespace()
    response = await client.post(
        f"/accounting/organizations/{book[0]}/shipments/{act['source_key']}/preview",
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["posted"] is False
    assert response.json()["confirmation_available"] is True
    gateway.accounting_shipment_source.assert_awaited_once()
