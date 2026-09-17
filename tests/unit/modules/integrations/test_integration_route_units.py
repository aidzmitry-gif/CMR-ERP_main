from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.integrations import routes, service


class Request:
    def __init__(self, *, method="POST", query=None, headers=None, body=b"", json_value=None):
        self.method = method
        self.query_params = query or {}
        self.headers = headers or {}
        self._body = body
        self._json = json_value

    async def body(self):
        return self._body

    async def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class Session:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.commits = 0

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))

    async def commit(self):
        self.commits += 1


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((event_type, payload))


def core(*, intake_token="", telephony_token="", registry=None, telephony=None, onec=None):
    return SimpleNamespace(
        config=SimpleNamespace(
            intake_webhook_token=intake_token,
            environment="dev",
            telephony_webhook_token=telephony_token,
        ),
        event_bus=Bus(),
        services=SimpleNamespace(registry=registry, telephony=telephony, onec=onec),
    )


@pytest.mark.asyncio
async def test_collect_params_merges_query_json_and_form_payloads():
    json_request = Request(
        method="POST", query={"phone": "1", "source": "query"},
        headers={"content-type": "application/json"}, json_value={"phone": "2", "name": "А"},
    )
    assert await routes._collect_params(json_request) == {
        "phone": "2", "source": "query", "name": "А"
    }

    form_request = Request(
        method="POST", query={"source": "query"}, body=b"name=%D0%90&phone=123&phone=456"
    )
    assert await routes._collect_params(form_request) == {
        "source": "query", "name": "А", "phone": "456"
    }

    bad_json = Request(method="POST", headers={"content-type": "application/json"}, json_value=ValueError("bad"))
    assert await routes._collect_params(bad_json) == {}


@pytest.mark.asyncio
async def test_telephony_and_intake_routes_emit_normalized_domain_events(monkeypatch):
    app_core = core(telephony_token="tok", intake_token="intake")
    session = Session()
    monkeypatch.setattr(routes.telephony, "ingest", lambda session, bus, params: {"ok": True, "call_id": params["uniqueid"]})
    telephony_request = Request(method="POST", query={"token": "tok"}, body=b"type=in&uniqueid=call-1&phone=80291234567")
    assert await routes.telephony_webhook(telephony_request, app_core, session) == {"ok": True, "call_id": "call-1"}
    assert session.commits == 1

    site_request = Request(
        query={"token": "intake", "name": "Альфа", "landing_url": "https://x.test/?utm_source=google"}
    )
    assert await routes.web_lead_intake(site_request, app_core, session) == {"ok": True, "source": "site"}
    assert app_core.event_bus.events[-1][0] == "intake.lead.received"
    assert app_core.event_bus.events[-1][1]["utm_source"] == "google"

    email_request = Request(
        query={"token": "intake", "from": '"Альфа" <sales@example.com>', "subject": "Запрос", "text": "Нужен АКБ"}
    )
    assert await routes.email_lead_intake(email_request, app_core, session) == {"ok": True, "source": "email"}
    assert app_core.event_bus.events[-1][1]["message"] == "Запрос\nНужен АКБ"


@pytest.mark.asyncio
async def test_telephony_and_intake_routes_fail_closed_on_bad_tokens():
    secured = core(intake_token="secret", telephony_token="voice")
    with pytest.raises(HTTPException) as voice:
        await routes.telephony_webhook(Request(query={"token": "bad"}), secured, Session())
    assert voice.value.status_code == 403
    with pytest.raises(HTTPException) as intake:
        await routes.web_lead_intake(Request(query={"token": "bad"}), secured, Session())
    assert intake.value.status_code == 403


@pytest.mark.asyncio
async def test_originate_and_registry_routes_translate_gateway_states():
    body = SimpleNamespace(vnut="12", number="+375291234567")
    with pytest.raises(HTTPException) as absent:
        await routes.telephony_originate(body, core(), None)
    assert absent.value.status_code == 503

    gateway = SimpleNamespace(configured=True, originate=AsyncMock(return_value={"ok": True, "id": "c1"}))
    result = await routes.telephony_originate(body, core(telephony=gateway), None)
    assert result == {"ok": True, "id": "c1"}
    gateway.originate.side_effect = RuntimeError("АТС down")
    with pytest.raises(HTTPException) as failed:
        await routes.telephony_originate(body, core(telephony=gateway), None)
    assert failed.value.status_code == 502

    with pytest.raises(HTTPException) as no_registry:
        await routes.egr_lookup("190000001", core(), None)
    assert no_registry.value.status_code == 503
    registry = SimpleNamespace(lookup=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as no_company:
        await routes.egr_lookup("190000001", core(registry=registry), None)
    assert no_company.value.status_code == 404
    registry.lookup.return_value = {"unp": "190000001", "name": "Альфа"}
    assert await routes.egr_lookup("190000001", core(registry=registry), None) == {
        "unp": "190000001", "name": "Альфа"
    }


@pytest.mark.asyncio
async def test_sync_wrappers_and_enqueue_validate_boundaries(monkeypatch):
    app_core = core(onec=SimpleNamespace())
    monkeypatch.setattr(routes, "sync_1c", AsyncMock(return_value={"stock": 2}))
    session = Session()
    assert await routes.sync(app_core, session, None) == {"ok": True, "stock": 2}
    assert session.commits == 1

    monkeypatch.setattr(routes.sync_outbound, "flush_pending", AsyncMock(return_value={"synced": 1}))
    assert await routes.sync_out(app_core, session, None) == {"ok": True, "synced": 1}

    monkeypatch.setattr(routes.sync_outbound, "enqueue", AsyncMock(return_value=SimpleNamespace(state="pending")))
    assert await routes.enqueue_out("sku", 7, app_core, session, None) == {
        "ok": True, "state": "pending", "entity_type": "sku", "entity_id": 7
    }
    with pytest.raises(HTTPException) as invalid:
        await routes.enqueue_out("deal", 7, app_core, session, None)
    assert invalid.value.status_code == 400


@pytest.mark.asyncio
async def test_sync_service_imports_stock_and_emits_summary(monkeypatch):
    class Client:
        async def fetch_counterparties(self):
            return [{"name": "Альфа", "unp": "1"}]

        async def fetch_stock(self):
            return [{
                "sku_code": "SKU-1", "title": "АКБ", "warehouse": "Главный",
                "qty_available": 5, "qty_reserved": 1, "qty_forecast": 8, "price": 20, "cost": None,
            }]

    class Scalars:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Db:
        def __init__(self):
            self.results = [Scalars([]), Scalars([])]
            self.added = []
            self.flushes = 0

        async def execute(self, _statement):
            return SimpleNamespace(scalars=lambda: self.results.pop(0))

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            self.flushes += 1

    bus = Bus()
    monkeypatch.setattr(service.reference_import, "import_counterparties", AsyncMock(return_value={"total": 1, "created": 1, "aliases_added": 0}))
    db = Db()
    result = await service.sync_1c(db, bus, Client())
    assert result == {"counterparties": 1, "new_counterparties": 1, "counterparty_aliases": 0, "stock": 1}
    assert len(db.added) == 2 and db.flushes == 1
    assert bus.events[0][0] == "integration.1c.synced"
