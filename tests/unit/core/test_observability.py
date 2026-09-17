from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.runtime import app as app_runtime
from core.runtime import system_routes


class Session:
    def __init__(self, error=None):
        self.error = error
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if self.error:
            raise self.error
        return SimpleNamespace()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_readiness_reports_database_ok():
    session = Session()

    assert await system_routes.readiness(session) == {
        "status": "ready",
        "checks": {"database": "ok"},
    }
    assert session.statements == ["SELECT 1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_readiness_returns_503_without_leaking_database_error():
    with pytest.raises(HTTPException) as raised:
        await system_routes.readiness(Session(RuntimeError("password=secret")))

    assert raised.value.status_code == 503
    assert raised.value.detail == {
        "status": "not_ready",
        "checks": {"database": "error"},
    }
    assert "secret" not in str(raised.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_background_failure_is_sent_to_notifier():
    errors = []

    class Notifier:
        async def emit(self, source, error):
            errors.append((source, error))

    error = RuntimeError("boom")
    await app_runtime._report_background_failure(SimpleNamespace(incident_alerts=Notifier()), error)
    assert errors == [("background_loop", error)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_background_failure_does_not_require_notifier_and_contains_notifier_errors(caplog):
    await app_runtime._report_background_failure(SimpleNamespace(), RuntimeError("boom"))

    class BrokenNotifier:
        async def emit(self, source, error):
            raise RuntimeError("alert transport down")

    await app_runtime._report_background_failure(
        SimpleNamespace(incident_alerts=BrokenNotifier()), RuntimeError("boom")
    )
    assert "incident notifier failed" in caplog.text
