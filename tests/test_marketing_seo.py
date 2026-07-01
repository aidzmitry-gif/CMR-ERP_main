"""Тесты SEO-интеграции MAR-8 (Phase A)."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_seo_webhook_project_linked(session, api):
    body = {
        "event_type": "marketing.seo.project.linked",
        "version": 1,
        "payload": {
            "external_project_id": "proj-lithium-batteries",
            "name": "Литиевые элементы питания",
            "domain": "battery-supply.ru",
            "region": "Москва",
            "status": "active",
        },
    }
    raw = json.dumps(body).encode()
    r = await api.post(
        "/marketing/seo/webhook",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["handled"] is True

    listed = await api.get("/marketing/seo/projects")
    assert listed.status_code == 200
    projects = listed.json()
    assert len(projects) == 1
    assert projects[0]["external_project_id"] == "proj-lithium-batteries"
    assert projects[0]["name"] == "Литиевые элементы питания"


@pytest.mark.asyncio
async def test_seo_webhook_snapshot_updated(session, api):
    link_body = {
        "event_type": "marketing.seo.project.linked",
        "version": 1,
        "payload": {
            "external_project_id": "proj-demo",
            "name": "Demo",
            "domain": "demo.ru",
        },
    }
    await api.post(
        "/marketing/seo/webhook",
        content=json.dumps(link_body).encode(),
        headers={"Content-Type": "application/json"},
    )

    snap_body = {
        "event_type": "marketing.seo.snapshot.updated",
        "version": 1,
        "payload": {
            "external_project_id": "proj-demo",
            "date": "2026-06-30",
            "visibility": 34.2,
            "total_keywords": 1248,
            "top10_count": 312,
            "critical_tasks": 12,
            "quick_wins": 28,
            "payload": {"task_count": 47},
        },
    }
    r = await api.post(
        "/marketing/seo/webhook",
        content=json.dumps(snap_body).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200

    projects = (await api.get("/marketing/seo/projects")).json()
    assert projects[0]["keywordCount"] == 1248
    assert projects[0]["visibility"] == pytest.approx(34.2)
    assert projects[0]["taskCount"] == 47


@pytest.mark.asyncio
async def test_seo_webhook_hmac_enforced(session, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from config.settings import get_settings
    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    monkeypatch.setenv("AIOS_SEO_WEBHOOK_SECRET", "s3cret-seo")
    get_settings.cache_clear()

    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)

    body = {
        "event_type": "marketing.seo.project.linked",
        "version": 1,
        "payload": {"external_project_id": "x", "name": "X", "domain": "x.ru"},
    }
    raw = json.dumps(body).encode()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/marketing/seo/webhook", content=raw)).status_code == 403
            sig = _sign(raw, "s3cret-seo")
            r = await client.post(
                "/marketing/seo/webhook",
                content=raw,
                headers={"Content-Type": "application/json", "X-SEO-Signature": sig},
            )
            assert r.status_code == 200
    finally:
        monkeypatch.delenv("AIOS_SEO_WEBHOOK_SECRET", raising=False)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_seo_project_get_by_id(session, api):
    await api.post(
        "/marketing/seo/projects/link",
        json={
            "external_project_id": "proj-get-by-id",
            "name": "Get By Id",
            "domain": "getbyid.ru",
        },
    )
    listed = (await api.get("/marketing/seo/projects")).json()
    pid = listed[0]["id"]
    r = await api.get(f"/marketing/seo/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get By Id"
    assert (await api.get("/marketing/seo/projects/999999")).status_code == 404


@pytest.mark.asyncio
async def test_seo_projects_link(session, api):
    r = await api.post(
        "/marketing/seo/projects/link",
        json={
            "external_project_id": "proj-er-series",
            "name": "Элементы ER14505",
            "domain": "er-batteries.ru",
            "region": "Москва",
            "status": "paused",
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "paused"
    assert r.json()["domain"] == "er-batteries.ru"

    summary = await api.get("/marketing/seo/projects/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["totalProjects"] >= 1


@pytest.mark.asyncio
async def test_seo_task_webhook_and_list(session, api):
    await api.post(
        "/marketing/seo/projects/link",
        json={
            "external_project_id": "proj-tasks",
            "name": "Tasks Project",
            "domain": "tasks.ru",
        },
    )
    listed = (await api.get("/marketing/seo/projects")).json()
    pid = next(p["id"] for p in listed if p["external_project_id"] == "proj-tasks")

    task_body = {
        "event_type": "marketing.seo.task.created",
        "version": 1,
        "payload": {
            "external_project_id": "proj-tasks",
            "external_task_id": "task-001",
            "title": "Исправить meta description",
            "type": "on_page",
            "priority": "critical",
            "status": "new",
            "url": "https://tasks.ru/page",
            "cluster": "Батарейки",
        },
    }
    r = await api.post(
        "/marketing/seo/webhook",
        content=json.dumps(task_body).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200

    tasks = (await api.get(f"/marketing/seo/projects/{pid}/tasks")).json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Исправить meta description"

    attention = (await api.get("/marketing/seo/attention")).json()
    assert any(a["title"] == "Исправить meta description" for a in attention)


@pytest.mark.asyncio
async def test_seo_deep_link_and_dashboard(session, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from config.settings import get_settings
    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    monkeypatch.setenv("AIOS_SEO_UI_BASE_URL", "https://seo.example.com")
    get_settings.cache_clear()
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
        ) as api:
            await api.post(
                "/marketing/seo/projects/link",
                json={
                    "external_project_id": "proj-dash",
                    "name": "Dash",
                    "domain": "dash.ru",
                },
            )
            listed = (await api.get("/marketing/seo/projects")).json()
            pid = listed[0]["id"]

            snap_body = {
                "event_type": "marketing.seo.snapshot.updated",
                "version": 1,
                "payload": {
                    "external_project_id": "proj-dash",
                    "date": "2026-07-01",
                    "visibility": 42.0,
                    "total_keywords": 100,
                    "top10_count": 25,
                    "critical_tasks": 3,
                    "payload": {
                        "visibility_history": [
                            {"date": "2026-06-01", "visibility": 38},
                            {"date": "2026-07-01", "visibility": 42},
                        ],
                        "quick_wins": [{"keyword": "test kw", "potential": "high"}],
                    },
                },
            }
            await api.post(
                "/marketing/seo/webhook",
                content=json.dumps(snap_body).encode(),
                headers={"Content-Type": "application/json"},
            )

            dash = (await api.get(f"/marketing/seo/projects/{pid}/dashboard")).json()
            assert dash["project"]["name"] == "Dash"
            assert len(dash["visibilityHistory"]) >= 1

            link = (await api.get(f"/marketing/seo/projects/{pid}/deep-link")).json()
            assert link["url"].startswith("https://seo.example.com/projects/")
    finally:
        monkeypatch.delenv("AIOS_SEO_UI_BASE_URL", raising=False)
        get_settings.cache_clear()
