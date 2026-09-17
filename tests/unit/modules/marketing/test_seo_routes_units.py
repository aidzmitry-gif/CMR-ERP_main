from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.marketing import seo_routes
from modules.marketing.seo_schemas import SeoProjectLinkIn, SeoProjectOut


class Request:
    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = headers or {}

    async def body(self):
        return self._body


class Result:
    def __init__(self, scalar):
        self.scalar = scalar

    def scalar_one(self):
        return self.scalar


class Session:
    def __init__(self, scalar=0):
        self.scalar = scalar
        self.commits = 0

    async def execute(self, _statement):
        return Result(self.scalar)

    async def commit(self):
        self.commits += 1


def core(secret=""):
    class Bus:
        def __init__(self):
            self.events = []

        def emit(self, *args):
            self.events.append(args)

    return SimpleNamespace(
        config=SimpleNamespace(seo_webhook_secret=secret, seo_ui_base_url="https://seo.example.test"),
        event_bus=Bus(),
    )


def project(project_id=1, status="active"):
    return SeoProjectOut(
        id=project_id,
        external_project_id=f"EXT-{project_id}",
        name=f"Project {project_id}",
        status=status,
    )


@pytest.mark.asyncio
async def test_seo_webhook_checks_signature_parses_events_and_commits(monkeypatch):
    body = b'{"eventType":"marketing.seo.task.created","payload":{"id":1}}'
    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    handler = AsyncMock()
    monkeypatch.setattr(seo_routes, "handle_seo_event", handler)
    app_core = core("secret")
    session = Session()

    result = await seo_routes.seo_webhook(
        Request(body, {"X-SEO-Signature": signature}), app_core, session
    )
    assert result.event_type == "marketing.seo.task.created"
    assert result.handled is True and session.commits == 1
    handler.assert_awaited_once()

    unsupported = b'{"eventType":"marketing.seo.unknown","payload":{}}'
    result = await seo_routes.seo_webhook(Request(unsupported), core(), Session())
    assert result.handled is False


@pytest.mark.asyncio
async def test_seo_webhook_rejects_bad_signature_body_and_handler_payload(monkeypatch):
    with pytest.raises(HTTPException) as bad_signature:
        await seo_routes.seo_webhook(Request(b"{}", {"X-SEO-Signature": "bad"}), core("secret"), Session())
    assert bad_signature.value.status_code == 403

    with pytest.raises(HTTPException) as bad_body:
        await seo_routes.seo_webhook(Request(b"not-json"), core(), Session())
    assert bad_body.value.status_code == 422

    monkeypatch.setattr(
        seo_routes,
        "handle_seo_event",
        AsyncMock(side_effect=ValueError("external_project_id обязателен")),
    )
    body = b'{"eventType":"marketing.seo.task.created","payload":{}}'
    with pytest.raises(HTTPException, match="external_project_id"):
        await seo_routes.seo_webhook(Request(body), core(), Session())


@pytest.mark.asyncio
async def test_seo_project_routes_delegate_and_return_contracts(monkeypatch):
    linked = project()
    handler = AsyncMock()
    monkeypatch.setattr(seo_routes, "handle_seo_event", handler)
    monkeypatch.setattr(seo_routes, "projects_with_snapshots", AsyncMock(return_value=[linked]))
    bus = SimpleNamespace(events=[], emit=lambda *args: bus.events.append(args))
    app_core = SimpleNamespace(event_bus=bus, config=SimpleNamespace(seo_ui_base_url="https://seo"))
    session = Session()
    payload = SeoProjectLinkIn(external_project_id="EXT-1", name="Project 1", domain="example.by")
    result = await seo_routes.link_seo_project(payload, app_core, session)
    assert result is linked and session.commits == 1
    assert bus.events
    handler.assert_awaited_once()

    monkeypatch.setattr(seo_routes, "projects_with_snapshots", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException, match="Не удалось создать"):
        await seo_routes.link_seo_project(payload, app_core, Session())

    projects = [project(1), project(2, "paused")]
    monkeypatch.setattr(seo_routes, "projects_with_snapshots", AsyncMock(return_value=projects))
    assert await seo_routes.list_seo_projects(Session()) == projects

    monkeypatch.setattr(seo_routes, "projects_with_snapshots", AsyncMock(return_value=projects))
    summary = await seo_routes.seo_projects_summary(Session(3))
    assert summary.total_projects == 2 and summary.active_projects == 1
    assert summary.total_tasks == 3
    summary_fallback = await seo_routes.seo_projects_summary(Session(0))
    assert summary_fallback.total_tasks == 0


@pytest.mark.asyncio
async def test_seo_read_routes_delegate_and_fail_closed(monkeypatch):
    projects = [project(1)]
    attention = AsyncMock(return_value=[])
    monkeypatch.setattr(seo_routes, "list_attention", attention)
    assert await seo_routes.seo_attention(7, Session()) == []
    attention.assert_awaited_once_with(attention.await_args.args[0], limit=7)

    monkeypatch.setattr(seo_routes, "projects_with_snapshots", AsyncMock(return_value=projects))
    assert await seo_routes.get_seo_project(1, Session()) is projects[0]
    with pytest.raises(HTTPException, match="SEO-проект не найден"):
        await seo_routes.get_seo_project(404, Session())

    dashboard = SimpleNamespace(project_id=1)
    tasks = [SimpleNamespace(id=1)]
    visibility = [SimpleNamespace(date="2026-09-17", visibility=10)]
    monkeypatch.setattr(seo_routes, "build_dashboard", AsyncMock(return_value=dashboard))
    monkeypatch.setattr(seo_routes, "list_project_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr(seo_routes, "list_visibility_history", AsyncMock(return_value=visibility))
    assert await seo_routes.get_seo_project_dashboard(1, Session()) is dashboard
    assert await seo_routes.get_seo_project_tasks(1, Session()) == tasks
    assert await seo_routes.get_seo_project_visibility(1, Session()) == visibility

    deep = SimpleNamespace(url="https://seo/projects/EXT-1")
    monkeypatch.setattr(seo_routes, "build_deep_link", AsyncMock(return_value=deep))
    app_core = SimpleNamespace(config=SimpleNamespace(seo_ui_base_url="https://seo"))
    assert await seo_routes.get_seo_deep_link(1, app_core, Session()) is deep
