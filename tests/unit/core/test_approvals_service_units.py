from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from core.services.approvals import ApprovalService


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows=()):
        self.rows = rows
        self.added = []
        self.commits = 0

    def add(self, value):
        value.id = len(self.added) + 1
        self.added.append(value)

    async def flush(self):
        return None

    async def execute(self, _statement):
        return Result(self.rows)

    async def commit(self):
        self.commits += 1


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, session, event_type, payload):
        self.events.append((session, event_type, payload))


@pytest.mark.asyncio
async def test_approval_request_uses_specific_and_default_routes():
    bus = Bus()
    service = ApprovalService(bus)
    session = Session()

    known = await service.request(session, "deal.discount", "deal:1", "Скидка", "manager")
    unknown = await service.request(session, "unknown", "deal:2", "Другое")
    assert known.route == "РОП"
    assert unknown.route == "РОП"
    assert known.due_at < unknown.due_at
    assert [event[1] for event in bus.events] == ["approval.requested", "approval.requested"]


@pytest.mark.asyncio
async def test_approval_decision_emits_approved_and_rejected_events():
    bus = Bus()
    service = ApprovalService(bus)
    session = Session()
    approved = SimpleNamespace(id=1, kind="deal.contract", entity_ref="deal:1", status="pending")
    rejected = SimpleNamespace(id=2, kind="deal.discount", entity_ref="deal:2", status="pending")

    await service.decide(session, approved, True, "director", "ok")
    await service.decide(session, rejected, False, "director", "дорого")
    assert (approved.status, approved.decided_by, approved.reason) == ("approved", "director", "ok")
    assert (rejected.status, rejected.decided_by, rejected.reason) == ("rejected", "director", "дорого")
    assert [event[1] for event in bus.events] == ["approval.approved", "approval.rejected"]


@pytest.mark.asyncio
async def test_escalate_once_updates_expired_rows_and_is_noop_when_empty():
    expired = SimpleNamespace(
        id=3,
        escalation_level=0,
        due_at=datetime.now() - timedelta(hours=1),
        route="РОП",
    )
    bus = Bus()
    service = ApprovalService(bus)
    session = Session([expired])
    assert await service.escalate_once(session) == 1
    assert expired.escalation_level == 1
    assert expired.due_at > datetime.now()
    assert session.commits == 1
    assert bus.events[0][1] == "approval.escalated"

    empty_session = Session()
    assert await service.escalate_once(empty_session) == 0
    assert empty_session.commits == 0
