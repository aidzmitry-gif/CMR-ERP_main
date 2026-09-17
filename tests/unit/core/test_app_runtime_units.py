from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.runtime import app as app_runtime


@pytest.mark.asyncio
async def test_run_hooks_supports_sync_and_async_callbacks():
    seen = []

    def sync_hook():
        seen.append("sync")

    async def async_hook():
        seen.append("async")

    await app_runtime._run_hooks([sync_hook, async_hook])
    assert seen == ["sync", "async"]


def test_register_dev_fixtures_has_environment_and_flag_guards(monkeypatch):
    prod = SimpleNamespace(config=SimpleNamespace(environment="prod"), price_cost=None)
    app_runtime._register_dev_fixtures(prod)
    assert prod.price_cost is None

    dev = SimpleNamespace(config=SimpleNamespace(environment="dev"), price_cost=None)
    monkeypatch.delenv("AIOS_DEMO_PRICE_COST", raising=False)
    app_runtime._register_dev_fixtures(dev)
    assert dev.price_cost is None

    monkeypatch.setenv("AIOS_DEMO_PRICE_COST", "1")
    app_runtime._register_dev_fixtures(dev)
    assert dev.price_cost.__class__.__name__ == "DemoPriceCostSource"

    existing = SimpleNamespace(config=SimpleNamespace(environment="dev"), price_cost=object())
    app_runtime._register_dev_fixtures(existing)
    assert existing.price_cost.__class__ is object


class ContextManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


def services_for_loop(relay_once, notifier=None):
    session = SimpleNamespace(commit=AsyncMock())
    services = SimpleNamespace(
        db=SimpleNamespace(session_factory=lambda: ContextManager(session)),
        event_bus=SimpleNamespace(relay_once=relay_once),
        approvals=SimpleNamespace(escalate_once=AsyncMock()),
        incident_alerts=notifier,
    )
    return services, session


@pytest.mark.asyncio
async def test_background_loop_runs_relay_escalation_and_tick_then_cancels(monkeypatch):
    sleeps = 0

    async def sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    relay = AsyncMock()
    services, session = services_for_loop(relay)
    hook = AsyncMock()
    monkeypatch.setattr(app_runtime.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await app_runtime._background_loop(services, [hook])

    relay.assert_awaited_once()
    services.approvals.escalate_once.assert_awaited_once()
    hook.assert_awaited_once_with(session, services)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_background_loop_reports_runtime_failure_and_keeps_cancellation_boundary(monkeypatch):
    sleeps = 0

    async def sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    relay = AsyncMock(side_effect=RuntimeError("relay failed"))
    emitted = []

    class Notifier:
        async def emit(self, source, error):
            emitted.append((source, error))

    services, _session = services_for_loop(relay, Notifier())
    monkeypatch.setattr(app_runtime.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await app_runtime._background_loop(services)
    assert emitted[0][0] == "background_loop"
    assert isinstance(emitted[0][1], RuntimeError)
