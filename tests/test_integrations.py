"""Тесты модуля Integrations (чтение из 1С)."""

from unittest.mock import AsyncMock

import pytest

from core.services.registry import RegistryError
from modules.integrations.module import IntegrationsModule
from modules.integrations.registry import RegistryClient


async def test_1c_sync(session, api):
    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias, OutboxEvent

    r = await api.post("/integrations/1c/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["stock"] == 3
    assert body["counterparties"] == 3
    assert body["counterparty_aliases"] == 3  # на каждый контрагент 1С — alias-провенанс

    stock = (await api.get("/integrations/1c/stock")).json()
    assert len(stock) == 3
    assert any(s["sku_code"] == "AKB-60" for s in stock)

    counterparties = (await session.execute(select(Counterparty))).scalars().all()
    assert len(counterparties) >= 3

    # провенанс источника записан в golden record (Ref_Key 1С → counterparty_alias)
    onec_aliases = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(onec_aliases) == 3

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "integration.1c.synced" in types

    # повторный sync идемпотентен: ни новых контрагентов, ни дублей алиасов
    body2 = (await api.post("/integrations/1c/sync")).json()
    assert body2["new_counterparties"] == 0
    assert body2["counterparty_aliases"] == 0
    again = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(again) == 3


async def test_egr_lookup(api):
    # dev-фикстура явно выдаёт demo, не официальный реестр
    r = await api.get("/integrations/egr/191234567")
    assert r.status_code == 200
    body = r.json()
    assert body["unp"] == "191234567"
    assert "Аккумулятор" in body["name"]
    assert body["status"] == "Действующий"
    assert body["source"] == "demo" and body["source_url"] is None
    assert body["fetched_at"].endswith("Z")

    # неизвестный УНП → 404
    assert (await api.get("/integrations/egr/000000000")).status_code == 404


@pytest.mark.parametrize(("code", "status"), [
    ("bad_input", 422), ("not_found", 404), ("unconfigured", 503), ("timeout", 503),
    ("unreachable", 503), ("rate_limited", 429), ("invalid_upstream", 502),
    ("upstream_error", 502), ("upstream_access_denied", 502),
])
async def test_registry_api_preserves_error_codes(api, monkeypatch, code, status):
    failure = RegistryError(code, "Безопасное сообщение", status, 60 if status == 429 else None)
    monkeypatch.setattr(RegistryClient, "lookup_strict", AsyncMock(side_effect=failure))
    response = await api.get("/integrations/egr/100582333")
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "message": "Безопасное сообщение"}}
    assert response.headers.get("retry-after") == ("60" if status == 429 else None)


async def test_registry_permission_and_input_boundaries(api, monkeypatch):
    strict = AsyncMock()
    monkeypatch.setattr(RegistryClient, "lookup_strict", strict)
    response = await api.get("/integrations/egr/100582333", headers={"X-User-Roles": "guest"})
    assert response.status_code == 403
    strict.assert_not_awaited()


@pytest.mark.parametrize("environment", ["prod", "production", "staging", "dev-preview"])
async def test_module_does_not_enable_implicit_demo(api, monkeypatch, environment):
    core = api._transport.app.state.core
    monkeypatch.setattr(core.config, "environment", environment)
    monkeypatch.setattr(core.config, "egr_base_url", "")
    IntegrationsModule().register(core)
    response = await api.get("/integrations/egr/191234567")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "unconfigured"


async def test_registry_unconfigured_contract_keeps_manual_buyer(api):
    core = api._transport.app.state.core
    core.services.registry = RegistryClient()
    template = await api.post("/sales/contract-templates", json={
        "code": "registry-off", "name": "Без реестра", "body": "{{buyer.name}} {{buyer.unp}}",
    })
    assert template.status_code == 201
    deal = await api.post("/sales/deals", json={
        "number": "REGISTRY-OFF", "title": "Ручные реквизиты", "counterparty": "Ручная компания",
    })
    assert deal.status_code == 201
    response = await api.post(f"/sales/deals/{deal.json()['id']}/contract", json={
        "template_code": "registry-off", "unp": "191234567",
    })
    assert response.status_code == 201, response.text
    html = (await api.get(f"/sales/documents/{response.json()['id']}/render")).text
    assert "Ручная компания" in html and "191234567" in html


async def test_two_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    assert "sales" in data["loaded_modules"]
    assert "integrations" in data["loaded_modules"]
