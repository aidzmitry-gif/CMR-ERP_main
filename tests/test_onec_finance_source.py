"""Availability checks use synthetic local data and never call live 1C."""
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from modules.finance.reconcile import reconcile_with_onec
from modules.integrations.client import OneCClient


@pytest.mark.parametrize("availability", [False, None])
async def test_unavailable_financial_source_is_not_read_or_reported_as_available(session, availability):
    gateway = SimpleNamespace(financial_source_available=availability,
                              financial_source_reason="Synthetic unavailable source",
                              fetch_payments=AsyncMock(return_value=[{"ref": "must-not-be-read"}]))
    result = await reconcile_with_onec(session, gateway)
    assert result["source_available"] is False
    assert result["source_reason"] == "Synthetic unavailable source"
    assert result["matched"] == result["only_in_1c"] == []
    gateway.fetch_payments.assert_not_awaited()


async def test_available_empty_financial_source_remains_available(session):
    gateway = SimpleNamespace(financial_source_available=True, fetch_payments=AsyncMock(return_value=[]))
    result = await reconcile_with_onec(session, gateway)
    assert result["source_available"] is True
    assert result["source_reason"] is None
    gateway.fetch_payments.assert_awaited_once()


async def test_reconciliation_api_keeps_organization_source_guard(api, session, monkeypatch):
    core = api._transport.app.state.core
    client = OneCClient("https://onec.invalid")
    fetch = AsyncMock(return_value=[])
    member = AsyncMock()
    monkeypatch.setattr(client, "fetch_payments", fetch)
    monkeypatch.setattr(core.services, "onec", client)
    monkeypatch.setattr(core.services.accounting, "finance_member", member)
    response = await api.get("/finance/reconcile-1c?organization_id=1")
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Сверка с 1С по организации недоступна: принадлежность источника платежей ещё не подтверждена."
    )
    member.assert_awaited_once_with(session, 1, ANY, write=False)
    fetch.assert_not_awaited()
    assert "onec.invalid" not in response.text
