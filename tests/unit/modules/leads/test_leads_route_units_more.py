from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from core.services import mdm
from modules.leads import routes
from modules.leads.models import Lead, LeadAttachment, LeadItem
from modules.leads.schemas import (
    AttemptIn,
    LeadAttachmentIn,
    LeadItemIn,
    LinkContactIn,
    RejectIn,
    RouteIn,
)


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.scalar_value


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.added_many = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added) + len(self.added_many)
        self.added.append(value)

    def add_all(self, values):
        for value in values:
            self.add(value)
            self.added_many.append(value)

    async def flush(self):
        for value in [*self.added, *self.added_many]:
            if getattr(value, "id", None) is None:
                value.id = 100

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def refresh(self, value):
        self.refreshed.append(value)

    async def delete(self, value):
        self.deleted.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def core_with(bus: Bus, *, llm_enabled=False):
    return SimpleNamespace(
        event_bus=bus,
        services=SimpleNamespace(llm=SimpleNamespace(enabled=llm_enabled, model="gpt-test")),
    )


def lead(lead_id=1, status="new"):
    return Lead(
        id=lead_id,
        source="site",
        name="Иван",
        company="ООО Альфа",
        phone="+375291234567",
        email="ivan@example.com",
        region="Минск",
        product="АКБ",
        message="нужен аккумулятор",
        status=status,
        score=70,
        qualification="target",
        reason="телефон",
        assigned_to="",
        funnel="",
        reject_reason="",
        next_step_note="",
        created_at=datetime(2026, 9, 17, 8, 0),
        first_action_at=None,
        counterparty_id=9,
        customer_kind="existing",
        attempt_count=0,
        utm_source="ads",
        utm_campaign="autumn",
    )


@pytest.mark.asyncio
async def test_lead_reporting_and_point_reads_cover_wake_manager_stats_and_attempt_paths(monkeypatch):
    assert await routes.ping() == {"module": "leads", "status": "ok"}

    manager_rows = Result([(routes.MANAGERS[0]["name"], 3)])
    managers = await routes.list_managers(Session(manager_rows))
    assert managers[0].load == 3

    source_rows = Result([("site", "autumn", 10, 4, 2, 1, Decimal("71.25"), Decimal("1200"))])
    source = await routes.source_stats(30, Session(source_rows))
    assert source[0].model_dump() == {
        "source": "site", "utm_campaign": "autumn", "total": 10, "target": 4,
        "converted": 2, "rejected": 1, "avg_score": 71.2, "target_pct": 40.0,
        "conversion_pct": 20.0, "pipeline": 1200.0,
    }

    handoff_rows = Result([("Анна", 4, 2, Decimal("1000"), 2, Decimal("400"), 1)])
    handoff = await routes.handoff_stats(30, Session(handoff_rows))
    assert (handoff[0].manager, handoff[0].pending, handoff[0].stale) == ("Анна", 2, 1)

    now = datetime(2026, 9, 17, 10, 0)
    woke = lead(4, "rejected")
    woke.reject_reason = "не сейчас"
    woke.snooze_until = now - timedelta(minutes=1)
    woke.assigned_to = "Старый менеджер"
    woke.funnel = "old"
    wake_session = Session(Result([woke]), Result([]), objects={(Lead, 4): woke})
    monkeypatch.setattr(routes, "_utcnow", lambda: now)
    found = await routes.get_lead(4, wake_session)
    assert found.status == "new" and found.assigned_to == ""
    assert wake_session.commits == 1

    attempt = lead(5, "new")
    attempt_session = Session(Result([]), objects={(Lead, 5): attempt})
    out = await routes.log_attempt(5, AttemptIn(callback_at=now), attempt_session)
    assert out.callback_at == now and attempt_session.commits == 1
    with pytest.raises(HTTPException, match="до передачи"):
        await routes.log_attempt(5, None, Session(objects={(Lead, 5): Lead(id=5, status="routed")}))


@pytest.mark.asyncio
async def test_manual_route_express_bulk_and_convert_publish_auditable_events(monkeypatch):
    bus = Bus()
    routed = lead(10, "new")
    monkeypatch.setattr(routes, "_resolve_manager", AsyncMock(return_value=("Анна", "customer", "ручной тест")))
    monkeypatch.setattr(routes, "_utcnow", lambda: datetime(2026, 9, 17, 11, 0))
    routed_out = await routes.route(
        10,
        RouteIn(assigned_to="Анна", next_step_note="Позвонить"),
        core_with(bus),
        Session(objects={(Lead, 10): routed}),
    )
    assert (routed_out.assigned_to, routed.status) == ("Анна", "routed")
    assert bus.calls[-1][1] == "leads.lead.routed"

    target = lead(11, "new")
    non_target = lead(12, "new")
    monkeypatch.setattr(routes, "_compute_score", AsyncMock(side_effect=[(80, "target", "цель"), (20, "non_target", "мимо")]))
    monkeypatch.setattr(routes, "_resolve_manager", AsyncMock(return_value=("Анна", "customer", "авто")))
    bulk = await routes.express_bulk(
        core_with(bus), Session(Result([target, non_target]))
    )
    assert bulk.model_dump() == {"expressed": [11], "skipped_non_target": 1}
    assert target.status == "routed" and target.next_step_note == "Позвонить"

    converted = lead(13, "routed")
    converted.assigned_to = "Анна"
    item = LeadItem(
        id=1, lead_id=13, sku_id=7, sku_code="SKU-1", name="Товар", qty=Decimal("2"),
        price=Decimal("10"), discount_pct=Decimal("5"), created_at=None,
    )
    convert_bus = Bus()
    result = await routes.convert_lead(
        13, convert_bus and core_with(convert_bus), Session(Result([item]), objects={(Lead, 13): converted})
    )
    assert result.status == "converted"
    assert convert_bus.calls[0][2]["items"][0]["price"] == 10.0
    assert convert_bus.calls[0][1] == "leads.lead.converted"


@pytest.mark.asyncio
async def test_lead_item_contact_and_attachment_routes_keep_storage_and_mdm_at_explicit_boundaries(monkeypatch):
    current = lead(20, "new")
    item = LeadItem(
        id=1, lead_id=20, sku_id=7, sku_code="SKU-1", name="Товар", qty=Decimal("2"),
        price=Decimal("10"), discount_pct=Decimal("0"), created_at=None,
    )
    assert await routes.list_items(20, Session(Result([item]))) == [item]

    replacement = await routes.replace_items(
        20,
        [LeadItemIn(sku_id=8, sku_code="SKU-2", name="Новый", qty=1, price=20)],
        Session(Result(), Result([item]), objects={(Lead, 20): current}),
    )
    assert replacement == [item]

    counterparty = SimpleNamespace(id=9)
    contact = SimpleNamespace(id=33, full_name="Иван Петров")
    link = AsyncMock(return_value=(contact, True))
    monkeypatch.setattr(mdm, "link_contact", link)
    linked = await routes.link_contact(
        20,
        LinkContactIn(is_primary=True),
        Session(objects={(Lead, 20): current, (routes.Counterparty, 9): counterparty}),
    )
    assert linked.model_dump() == {"contact_id": 33, "counterparty_id": 9, "created": True, "full_name": "Иван Петров"}
    link.assert_awaited_once()

    attachment = LeadAttachment(
        id=4, lead_id=20, filename="заявка.txt", content_type="text/plain", size_bytes=3,
        source="manual", storage_path="leads/20/file.txt", created_at=datetime(2026, 9, 17),
    )
    monkeypatch.setattr(routes, "save_attachment", lambda *args: ("leads/20/file.txt", 3))
    uploaded = await routes.upload_attachment(
        20,
        LeadAttachmentIn(filename="заявка.txt", data_url="data:text/plain;base64,WFla"),
        Session(objects={(Lead, 20): current}),
    )
    assert uploaded.filename == "заявка.txt"

    monkeypatch.setattr(routes, "read_attachment", lambda path: b"XYZ")
    download = await routes.download_attachment(20, 4, Session(objects={(LeadAttachment, 4): attachment}))
    assert download.body == b"XYZ" and "filename*=" in download.headers["content-disposition"]
    monkeypatch.setattr(routes, "delete_attachment", lambda path: None)
    delete_session = Session(objects={(LeadAttachment, 4): attachment})
    response = await routes.remove_attachment(20, 4, delete_session)
    assert response.status_code == 204 and delete_session.deleted == [attachment]


@pytest.mark.asyncio
async def test_lead_route_reject_and_link_failures_are_explicit():
    bus = Bus()
    with pytest.raises(HTTPException, match="Неизвестный менеджер"):
        await routes.route(
            1, RouteIn(assigned_to="Нет такого"), core_with(bus), Session(objects={(Lead, 1): lead(1)})
        )

    already = lead(2, "converted")
    with pytest.raises(HTTPException, match="терминальном"):
        await routes.reject_lead(2, RejectIn(reason="нет бюджета"), core_with(bus), Session(objects={(Lead, 2): already}))

    current = lead(3)
    current.counterparty_id = None
    with pytest.raises(HTTPException, match="не привязан"):
        await routes.link_contact(3, None, Session(objects={(Lead, 3): current}))
