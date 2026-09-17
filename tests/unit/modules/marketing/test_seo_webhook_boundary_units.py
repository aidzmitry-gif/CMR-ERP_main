from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.marketing import seo_webhook
from modules.marketing.models import SeoProject, SeoSnapshot, SeoTask, Site


class ScalarResult:
    def __init__(self, value=None, rows=()):
        self.value = value
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        if self.value is None:
            raise AssertionError("expected scalar")
        return self.value

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self._next_id = 1

    async def execute(self, _statement):
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self._next_id
                self._next_id += 1


@pytest.mark.asyncio
async def test_project_linked_creates_site_project_and_sync_link():
    session = Session(ScalarResult(), ScalarResult(), ScalarResult())

    await seo_webhook._on_project_linked(
        session,
        {
            "external_project_id": "seo-1",
            "domain": "example.by",
            "name": "Example",
            "region": "Минск",
            "counterparty_id": 7,
        },
    )

    site, project, link = session.added
    assert isinstance(site, Site)
    assert (site.domain, site.region, site.counterparty_id, site.is_primary) == (
        "example.by",
        "Минск",
        7,
        True,
    )
    assert isinstance(project, SeoProject)
    assert (project.site_id, project.external_project_id, project.status) == (1, "seo-1", "active")
    assert (link.entity_type, link.entity_id, link.external_ref, link.state) == (
        "seo_project",
        2,
        "seo-1",
        "synced",
    )


@pytest.mark.asyncio
async def test_project_linked_updates_existing_rows_and_link():
    site = SimpleNamespace(id=11, domain="old.by", region="old", counterparty_id=None)
    project = SimpleNamespace(id=12, site_id=None, name="Old", status="paused", last_sync_at=None)
    link = SimpleNamespace(external_ref="old", state="error", last_synced_at=None)
    session = Session(ScalarResult(site), ScalarResult(project), ScalarResult(link))

    await seo_webhook._on_project_linked(
        session,
        {"project_id": "seo-2", "domain": "new.by", "name": "New", "status": "active"},
    )

    assert session.added == []
    assert (project.name, project.status, project.site_id) == ("New", "active", 11)
    assert (link.external_ref, link.state) == ("seo-2", "synced")


@pytest.mark.asyncio
async def test_snapshot_and_task_upsert_map_aliases_and_payload():
    project = SimpleNamespace(id=3)
    session = Session(ScalarResult(project), ScalarResult(project), ScalarResult(None))

    await seo_webhook._on_snapshot_updated(
        session,
        {
            "project_id": "seo-3",
            "snapshot_date": "2026-09-17",
            "visibility": "42.5",
            "keyword_count": 18,
            "top10_count": 4,
            "critical_tasks": 2,
            "quick_wins": [{"keyword": "x"}],
            "quickWins": [{"keyword": "alias"}],
        },
    )
    snapshot = session.added[0]
    assert isinstance(snapshot, SeoSnapshot)
    assert (snapshot.seo_project_id, snapshot.total_keywords, snapshot.quick_wins) == (3, 18, 1)
    assert snapshot.payload["quickWins"] == [{"keyword": "alias"}]

    await seo_webhook._on_task_upsert(
        session,
        {
            "project_id": "seo-3",
            "task_id": "task-1",
            "title": "Fix title",
            "priority": "high",
            "cluster": "battery",
            "assignedTo": "Ivan",
        },
    )
    task = session.added[1]
    assert isinstance(task, SeoTask)
    assert (task.external_task_id, task.title, task.cluster_name, task.assigned_to) == (
        "task-1",
        "Fix title",
        "battery",
        "Ivan",
    )


@pytest.mark.asyncio
async def test_task_status_changed_updates_existing_or_creates_missing_task():
    task = SimpleNamespace(status="new", synced_at=None)
    project = SimpleNamespace(id=4)
    existing = Session(ScalarResult(task))
    await seo_webhook._on_task_status_changed(existing, {"task_id": "task-2", "status": "implemented"})
    assert task.status == "implemented"
    assert existing.added == []

    missing = Session(ScalarResult(None), ScalarResult(project), ScalarResult(None))
    await seo_webhook._on_task_status_changed(
        missing,
        {"project_id": "seo-4", "task_id": "task-3", "status": "new"},
    )
    assert isinstance(missing.added[0], SeoTask)


@pytest.mark.asyncio
async def test_quick_win_appends_to_latest_snapshot_and_keeps_limit():
    project = SimpleNamespace(id=5)
    snapshot = SimpleNamespace(payload={"quick_wins": [{"keyword": str(i)} for i in range(20)]})
    session = Session(ScalarResult(project), ScalarResult(snapshot))

    await seo_webhook._on_quick_win(
        session,
        {"project_id": "seo-5", "keyword": "new", "position": 3, "frequency": 100, "url": "/x"},
    )

    assert len(snapshot.payload["quick_wins"]) == 20
    assert snapshot.payload["quick_wins"][-1]["keyword"] == "19"
    assert all(item["keyword"] != "new" for item in snapshot.payload["quick_wins"])
