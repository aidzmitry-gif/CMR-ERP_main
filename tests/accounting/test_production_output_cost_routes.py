from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from modules.accounting import routes
from modules.accounting.production_output_cost_workflow import ProductionOutputCostConfirmInput


async def test_output_cost_confirm_requires_accounting_write_role():
    data = ProductionOutputCostConfirmInput(original_entry_id=7, posting_date="2026-10-31",
        request_evidence="Reviewed source", request_key="00000000-0000-0000-0000-000000000001", basis_digest="a" * 64)
    with pytest.raises(HTTPException) as denied:
        await routes.production_output_cost_confirm(1, "2026-10", data, Response(),
            ctx=(object(), "reader", "viewer"), core=object())
    assert denied.value.status_code == 403


async def test_output_cost_confirm_uses_authorized_organization_and_actor(monkeypatch):
    from modules.accounting import production_output_cost_workflow as workflow

    calls = []

    async def confirm(session, org, month, data, actor, bus, *, procurement=None):
        calls.append((session, org, month, actor, bus, procurement))
        return SimpleNamespace(id=9, entry_id=None, sequence=2)

    monkeypatch.setattr(workflow, "confirm_output_cost_correction", confirm)
    session, bus = object(), object()
    data = ProductionOutputCostConfirmInput(original_entry_id=7, posting_date="2026-10-31",
        request_evidence="Reviewed source", request_key="00000000-0000-0000-0000-000000000001", basis_digest="a" * 64)
    response = Response()
    result = await routes.production_output_cost_confirm(12, "2026-10", data, response,
        expected_principal="bookkeeper",
        ctx=(session, "bookkeeper", "accountant"), core=SimpleNamespace(services=SimpleNamespace(event_bus=bus)))
    assert calls == [(session, 12, "2026-10", "bookkeeper", bus, None)]
    assert result["revision_id"] == 9 and result["entry_id"] is None
    assert result["final_cost_certified"] is False
    assert response.headers["Cache-Control"] == "private, no-store"
    assert result["actor"] == "bookkeeper" and result["month"] == "2026-10"
    assert result["request_key"] == str(data.request_key) and result["basis_digest"] == data.basis_digest
    assert result["original_entry_id"] == data.original_entry_id


async def test_output_cost_confirm_rejects_changed_principal_before_posting():
    data = ProductionOutputCostConfirmInput(original_entry_id=7, posting_date="2026-10-31",
        request_evidence="Reviewed source", request_key="00000000-0000-0000-0000-000000000001", basis_digest="a" * 64)
    with pytest.raises(HTTPException) as denied:
        await routes.production_output_cost_confirm(1, "2026-10", data, Response(),
            expected_principal="old-user", ctx=(object(), "new-user", "accountant"), core=object())
    assert denied.value.status_code == 409
