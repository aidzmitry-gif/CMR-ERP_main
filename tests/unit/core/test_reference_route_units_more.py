from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.domain.reference import CurrencyRate, Unit, VatRate
from core.runtime import reference_routes
from core.services.auth import CurrentUser


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added)
        self.added.append(value)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, value):
        self.refreshed.append(value)

    async def delete(self, value):
        self.deleted.append(value)


def request():
    bus = SimpleNamespace(emit=lambda *args: None)
    services = SimpleNamespace(approvals=None)
    app = SimpleNamespace(state=SimpleNamespace(core=SimpleNamespace(event_bus=bus, services=services)))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "app": app})


def endpoint(router, path, method):
    return next(r.endpoint for r in router.routes if r.path == path and method in r.methods)


@pytest.mark.asyncio
async def test_simple_reference_router_supports_list_create_patch_archive_and_bulk_idempotency():
    router = reference_routes.build_simple_ref_router(
        Unit, fields=("code", "title", "is_active"), editable=("code", "title", "is_active"), required=("code", "title")
    )
    actor = CurrentUser("director", ["director"])
    unit = Unit(id=1, code="шт", title="Штука", is_active=True)
    listed = await endpoint(router, "", "GET")(False, Session(Result([unit])))
    assert listed == [{"code": "шт", "title": "Штука", "is_active": True}]
    with pytest.raises(HTTPException, match="не хватает"):
        await endpoint(router, "", "POST")(request(), {}, Session(), actor)

    session = Session()
    created = await endpoint(router, "", "POST")(request(), {"code": "кг", "title": "Килограмм"}, session, actor)
    assert created["code"] == "кг" and session.commits == 1

    existing = Unit(id=2, code="кг", title="Старое", is_active=True)
    updated = await endpoint(router, "/{code}", "PATCH")("кг", request(), {"title": "Новое"}, Session(Result([existing])), actor)
    assert updated["title"] == "Новое"
    archived = await endpoint(router, "/{code}", "DELETE")("кг", request(), Session(Result([existing])), actor)
    assert archived == {"archived": "кг"} and existing.is_active is False

    bulk = endpoint(router, "/bulk", "POST")
    current = Unit(id=3, code="шт", title="Штука", is_active=True)
    dry = await bulk(
        request(),
        {"dry_run": True, "rows": [{"code": "шт", "title": "Изменено"}, {"code": "шт", "title": "дубль"}, {"title": "нет кода"}, {"code": "кг"}]},
        Session(Result([current])), actor,
    )
    assert len(dry["would_update"]) == 1 and len(dry["conflicts"]) == 3

    real_session = Session(Result([current]))
    result = await bulk(request(), {"rows": [{"code": "шт", "title": "Изменено"}, {"code": "л", "title": "Литр"}]}, real_session, actor)
    assert result == {"created": 1, "updated": 1, "conflicts": []}


@pytest.mark.asyncio
async def test_versioned_reference_router_supports_read_asof_add_and_sensitive_moderation(monkeypatch):
    router = reference_routes.build_versioned_ref_router(
        CurrencyRate,
        key_field="currency_code",
        value_fields=("rate",),
        list_fields=("id", "currency_code", "rate", "start_date", "end_date"),
    )
    actor = CurrentUser("director", ["director"])
    row = CurrencyRate(id=1, currency_code="USD", rate=Decimal("3.2"), start_date=date(2026, 1, 1), end_date=None)
    assert (await endpoint(router, "", "GET")(key="USD", session=Session(Result([row]))))[0]["currency_code"] == "USD"
    monkeypatch.setattr(reference_routes.scd2, "current_version", AsyncMock(return_value=row))
    monkeypatch.setattr(reference_routes.scd2, "version_as_of", AsyncMock(return_value=row))
    assert (await endpoint(router, "/current", "GET")("USD", Session()))["rate"] == Decimal("3.2")
    assert (await endpoint(router, "/as-of", "GET")("USD", date(2026, 9, 1), Session()))["start_date"] == date(2026, 1, 1)

    added = CurrencyRate(id=2, currency_code="USD", rate=Decimal("3.3"), start_date=date(2026, 9, 1), end_date=None)
    monkeypatch.setattr(reference_routes.scd2, "add_version", AsyncMock(return_value=added))
    result = await endpoint(router, "/versions", "POST")(
        request(), {"currency_code": "USD", "start_date": "2026-09-01", "rate": 3.3}, Session(), actor
    )
    assert result["rate"] == Decimal("3.3")

    sensitive_router = reference_routes.build_versioned_ref_router(
        VatRate,
        key_field="code",
        value_fields=("title", "rate"),
        list_fields=("id", "code", "title", "rate", "start_date", "end_date"),
    )
    approvals = SimpleNamespace(request=AsyncMock(return_value=SimpleNamespace(id=77, route="director")))
    moderation_request = request()
    moderation_request.app.state.core.services.approvals = approvals
    pending = await endpoint(sensitive_router, "/versions", "POST")(
        moderation_request,
        {"code": "НДС20", "start_date": "2026-09-01", "title": "НДС 20", "rate": 20},
        Session(), actor,
    )
    assert pending == {"status": "pending_approval", "approval_id": 77, "route": "director"}

    with pytest.raises(HTTPException, match="нужны поля"):
        await endpoint(router, "/versions", "POST")(request(), {"rate": 3}, Session(), actor)
    with pytest.raises(HTTPException, match="YYYY-MM-DD"):
        await endpoint(router, "/versions", "POST")(request(), {"currency_code": "USD", "start_date": "bad"}, Session(), actor)
