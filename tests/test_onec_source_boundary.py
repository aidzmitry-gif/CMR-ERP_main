"""Synthetic local checks: unavailable 1C must not manufacture an import."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import func, select

from core.domain.models import Counterparty, CounterpartyAlias, OutboxEvent, Sku
from core.services.onec import OneCSourceUnavailable
from modules.integrations.client import OneCClient
from modules.integrations.models import StockItem
from modules.integrations.module import IntegrationsModule


@pytest.mark.parametrize("method", ["fetch_counterparties", "fetch_stock"])
async def test_unconfigured_client_fails_closed_by_default(method):
    with pytest.raises(OneCSourceUnavailable) as error:
        await getattr(OneCClient(base_url="  "), method)()
    assert error.value.code == "onec_unconfigured"
    assert error.value.status == 503


@pytest.mark.parametrize("environment", [None, "", "prod", "staging", "dev-preview", "dev", "development", "test"])
async def test_registration_enables_demo_only_in_explicit_test_environments(environment):
    config = SimpleNamespace(onec_base_url="", egr_base_url="", telephony_originate_url="")
    if environment is not None:
        config.environment = environment
    core = SimpleNamespace(config=config, services=SimpleNamespace(),
                           include_router=Mock(), declare_permissions=Mock(), on_tick=Mock())
    IntegrationsModule().register(core)
    for method in ("fetch_counterparties", "fetch_stock"):
        if environment in {"dev", "development", "test"}:
            assert await getattr(core.services.onec, method)()
        else:
            with pytest.raises(OneCSourceUnavailable):
                await getattr(core.services.onec, method)()


@pytest.mark.parametrize("method", ["fetch_counterparties", "fetch_stock"])
async def test_failed_configured_source_does_not_fallback_or_leak_secrets(method, monkeypatch, caplog):
    client = OneCClient("https://onec.invalid", allow_demo=True)

    def failed_read():
        raise RuntimeError("https://synthetic-user:synthetic-secret@onec.invalid/private-payload")

    monkeypatch.setattr(client, "_" + method + "_sync", failed_read)
    with pytest.raises(OneCSourceUnavailable) as error:
        await getattr(client, method)()
    assert error.value.code == "onec_read_failed"
    assert error.value.status == 502
    for secret in ("synthetic-user", "synthetic-secret", "private-payload", "onec.invalid"):
        assert secret not in str(error.value)
        assert secret not in caplog.text


@pytest.mark.parametrize("method", ["fetch_counterparties", "fetch_stock"])
async def test_configured_reads_keep_their_result_even_when_demo_allowed(method, monkeypatch):
    client = OneCClient("https://onec.invalid", allow_demo=True)
    rows = [{"synthetic_wire": method}]
    monkeypatch.setattr(client, "_" + method + "_sync", lambda: rows)
    assert await getattr(client, method)() is rows


async def _seed_existing(session):
    session.add(Counterparty(name="Synthetic existing buyer", unp="900000001"))
    session.add(Sku(code="SYNTHETIC-EXISTING", title="Synthetic existing item", unit="шт"))
    session.add(StockItem(sku_code="SYNTHETIC-EXISTING", warehouse="Synthetic warehouse",
                          qty_available=Decimal("7"), qty_reserved=Decimal("2"),
                          qty_forecast=Decimal("9"), price=Decimal("19"), cost=Decimal("11")))
    await session.commit()


async def _assert_existing_preserved(session):
    assert await session.scalar(select(func.count()).select_from(Counterparty)) == 1
    assert await session.scalar(select(Counterparty.name)) == "Synthetic existing buyer"
    assert await session.scalar(select(func.count()).select_from(Sku)) == 1
    item = (await session.execute(select(StockItem))).scalar_one()
    assert item.sku_code == "SYNTHETIC-EXISTING"
    assert item.warehouse == "Synthetic warehouse"
    assert (item.qty_available, item.qty_reserved, item.qty_forecast, item.price, item.cost) == (
        Decimal("7"), Decimal("2"), Decimal("9"), Decimal("19"), Decimal("11"))
    assert await session.scalar(select(func.count()).select_from(CounterpartyAlias)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_production_sync_without_connection_preserves_existing_data(api, session, monkeypatch):
    await _seed_existing(session)
    core = api._transport.app.state.core
    monkeypatch.setattr(core.config, "environment", "prod")
    monkeypatch.setattr(core.config, "onec_base_url", "")
    IntegrationsModule().register(core)
    for gateway in (core.services.onec, None):
        core.services.onec = gateway
        response = await api.post("/integrations/1c/sync")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "onec_unconfigured"
        assert "ok" not in response.json()
        await _assert_existing_preserved(session)


async def test_stock_read_failure_rolls_back_already_imported_counterparties(api, session, monkeypatch):
    await _seed_existing(session)
    client = OneCClient("https://onec.invalid")
    monkeypatch.setattr(client, "fetch_counterparties", AsyncMock(return_value=[{
        "id": "00000000-0000-4000-8000-000000000123", "name": "Synthetic uncommitted buyer",
        "unp": "900000002", "legal_address": "Synthetic address, local test only",
    }]))

    def failed_stock():
        raise RuntimeError("synthetic-secret must not reach API")

    monkeypatch.setattr(client, "_fetch_stock_sync", failed_stock)
    monkeypatch.setattr(api._transport.app.state.core.services, "onec", client)
    response = await api.post("/integrations/1c/sync")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "onec_read_failed"
    assert "synthetic-secret" not in response.text
    client.fetch_counterparties.assert_awaited_once()
    await _assert_existing_preserved(session)


@pytest.mark.parametrize("configured", [False, True])
async def test_import_preview_reports_source_failure_without_writing(api, session, monkeypatch, configured):
    await _seed_existing(session)
    client = OneCClient("https://onec.invalid" if configured else "")

    def failed_read():
        raise RuntimeError("synthetic-secret must not reach preview")

    monkeypatch.setattr(client, "_fetch_counterparties_sync", failed_read)
    monkeypatch.setattr(api._transport.app.state.core.services, "onec", client)
    response = await api.get("/system/mdm/import-preview")
    assert response.status_code == (502 if configured else 503)
    assert response.json()["detail"]["code"] == ("onec_read_failed" if configured else "onec_unconfigured")
    assert "synthetic-secret" not in response.text
    await _assert_existing_preserved(session)


@pytest.mark.parametrize("payload", [{}, {"value": None}, {"value": False}, {"value": ""},
                                     {"value": {}}, {"value": [None]}, []])
async def test_malformed_odata_collection_is_not_a_successful_empty_read(payload, monkeypatch):
    client = OneCClient("https://onec.invalid")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(client, "_client", lambda: httpx.Client(transport=transport))
    with pytest.raises(OneCSourceUnavailable) as error:
        await client.fetch_counterparties()
    assert error.value.code == "onec_read_failed"
    assert error.value.status == 502


async def test_genuine_empty_odata_collection_remains_a_successful_empty_read(monkeypatch):
    client = OneCClient("https://onec.invalid")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []}))
    monkeypatch.setattr(client, "_client", lambda: httpx.Client(transport=transport))
    assert await client.fetch_counterparties() == []


async def test_empty_odata_record_is_not_a_successful_empty_read(monkeypatch):
    client = OneCClient("https://onec.invalid")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"value": [{}]}))
    monkeypatch.setattr(client, "_client", lambda: httpx.Client(transport=transport))
    with pytest.raises(OneCSourceUnavailable) as error:
        await client.fetch_counterparties()
    assert error.value.status == 502
