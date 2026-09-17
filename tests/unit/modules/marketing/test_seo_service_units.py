from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.marketing import seo_service
from modules.marketing.seo_schemas import SeoProjectOut, SeoTaskOut, SeoVisibilityPointOut


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.scalar_value


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


def project(project_id=1, *, last_sync_at=None, status="active"):
    return SimpleNamespace(
        id=project_id,
        external_project_id=f"EXT-{project_id}",
        name=f"Project {project_id}",
        status=status,
        last_sync_at=last_sync_at,
    )


def snapshot(project_id=1, *, payload=None, critical_tasks=0):
    return SimpleNamespace(
        seo_project_id=project_id,
        snapshot_date=date(2026, 9, 17),
        visibility=Decimal("42.5"),
        total_keywords=120,
        top10_count=8,
        critical_tasks=critical_tasks,
        payload=payload,
    )


def task(task_id=1, priority="critical"):
    return SimpleNamespace(
        id=task_id,
        external_task_id=f"TASK-{task_id}",
        title=f"Task {task_id}",
        type="technical",
        priority=priority,
        status="new",
        url=f"https://example.test/{task_id}",
        cluster_name="cluster",
        assigned_to="owner",
    )


@pytest.mark.asyncio
async def test_projects_with_snapshots_uses_snapshot_fallbacks_and_site_metadata():
    first = project(1)
    second = project(2, last_sync_at=datetime(2026, 9, 18), status="paused")
    third = project(3)
    first_snapshot = snapshot(1, payload={"task_count": 4})
    third_snapshot = snapshot(3, payload={}, critical_tasks=2)
    site = SimpleNamespace(domain="example.by", region="Минск")

    result = await seo_service.projects_with_snapshots(
        Session(
            Result([(first, site, first_snapshot), (second, None, None), (third, site, third_snapshot)]),
            Result([(3, 7)]),
        )
    )

    assert result[0].domain == "example.by"
    assert result[0].task_count == 4
    assert result[0].last_check.isoformat().startswith("2026-09-17")
    assert result[1].keyword_count == 0 and result[1].task_count == 0
    assert result[2].task_count == 7


@pytest.mark.asyncio
async def test_project_lookup_and_task_listing_are_fail_closed(monkeypatch):
    expected = SimpleNamespace(id=4)
    monkeypatch.setattr(seo_service, "projects_with_snapshots", AsyncMock(return_value=[expected]))
    assert await seo_service.get_project_or_404(SimpleNamespace(), 4) is expected
    with pytest.raises(HTTPException, match="SEO-проект не найден"):
        await seo_service.get_project_or_404(SimpleNamespace(), 404)

    monkeypatch.setattr(seo_service, "get_project_or_404", AsyncMock(return_value=expected))
    listed = await seo_service.list_project_tasks(
        Session(Result([task(1), task(2, "medium")])), 4
    )
    assert [item.id for item in listed] == [1, 2]


@pytest.mark.asyncio
async def test_visibility_history_returns_chronological_points_or_payload_fallback(monkeypatch):
    monkeypatch.setattr(seo_service, "get_project_or_404", AsyncMock(return_value=SimpleNamespace(id=1)))
    points = await seo_service.list_visibility_history(
        Session(Result([snapshot(), SimpleNamespace(snapshot_date=date(2026, 9, 18), visibility=Decimal("50"))])),
        1,
    )
    assert [point.date for point in points] == ["2026-09-18", "2026-09-17"]

    fallback = await seo_service.list_visibility_history(
        Session(
            Result([]),
            Result(
                scalar=SimpleNamespace(
                    payload={"visibilityHistory": [{"date": "2026-09-01", "visibility": 10}]}
                )
            ),
        ),
        1,
    )
    assert fallback[0].visibility == 10

    assert await seo_service.list_visibility_history(Session(Result([]), Result(scalar=None)), 1) == []


@pytest.mark.asyncio
async def test_dashboard_attention_and_deep_link_contracts(monkeypatch):
    project_out = SeoProjectOut(
        id=1, external_project_id="EXT-1", name="Project 1", status="active"
    )
    tasks = [SeoTaskOut.model_validate(task(1)), SeoTaskOut.model_validate(task(2, "low"))]
    monkeypatch.setattr(seo_service, "get_project_or_404", AsyncMock(return_value=project_out))
    monkeypatch.setattr(seo_service, "list_project_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr(
        seo_service,
        "list_visibility_history",
        AsyncMock(return_value=[SeoVisibilityPointOut(date="2026-09-17", visibility=42.5)]),
    )
    dashboard = await seo_service.build_dashboard(
        Session(
            Result(
                scalar=SimpleNamespace(
                    payload={"quickWins": [{"title": "Добавить title"}]},
                    top10_count=8,
                    critical_tasks=2,
                )
            )
        ),
        1,
    )
    assert len(dashboard.priority_tasks) == 1
    assert dashboard.quick_wins == [{"title": "Добавить title"}]
    assert dashboard.top10_count == 8

    attention_task = task(3, "high")
    attention_project = SimpleNamespace(id=1, name="Project 1")
    attention = await seo_service.list_attention(
        Session(Result([(attention_task, attention_project)])), limit=5
    )
    assert attention[0].project_name == "Project 1"
    assert attention[0].priority == "high"

    link = await seo_service.build_deep_link(
        Session(Result(scalar=SimpleNamespace(external_project_id="EXT-1"))),
        1,
        "https://crm.example.test/",
    )
    assert link.url == "https://crm.example.test/projects/EXT-1"
    with pytest.raises(HTTPException, match="SEO-проект не найден"):
        await seo_service.build_deep_link(Session(Result(scalar=None)), 404, "https://crm.example.test")
