from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from modules.sales.touch_history import SalesTouchHistory


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def scalar_one(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value


class Session:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_touches_and_summary_merge_all_sources_and_limit_latest_rows():
    deal_at = datetime(2026, 9, 10, 10, 0)
    call_at = datetime(2026, 9, 11, 10, 0)
    message_at = datetime(2026, 9, 12, 10, 0)
    deal = SimpleNamespace(number="D-1", title="Поставка", created_at=deal_at)
    call = SimpleNamespace(
        direction="in", result="дозвонились", status="ended", started_at=call_at, call_id="C-1"
    )
    message = SimpleNamespace(
        channel="telegram", direction="out", text="x" * 150, created_at=message_at, deal_id=7
    )
    session = Session(
        Result(scalar="ACME"),
        Result([7]),
        Result([deal]),
        Result([call]),
        Result([message]),
        Result(scalar="ACME"),
        Result([7]),
        Result(scalar=1),
        Result(scalar=call_at),
        Result(scalar=1),
        Result(scalar=deal_at),
        Result(scalar=1),
        Result(scalar=message_at),
    )

    touches = await SalesTouchHistory().touches(session, 5, limit=2)
    assert [item["kind"] for item in touches] == ["message", "call"]
    assert len(touches[0]["title"]) == 120
    assert touches[1]["title"] == "дозвонились"

    summary = await SalesTouchHistory().summary(session, 5)
    assert summary == {
        "calls": 1,
        "messages": 1,
        "deals": 1,
        "total": 3,
        "last_contact_at": message_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_touch_history_is_empty_for_unknown_counterparty_and_no_deals():
    session = Session(
        Result(scalar=None),
        Result([]),
        Result([]),
        Result(scalar=0),
        Result(scalar=None),
    )

    history = SalesTouchHistory()
    assert await history.touches(session, 404) == []
    assert await history.summary(session, 404) == {
        "calls": 0,
        "messages": 0,
        "deals": 0,
        "total": 0,
        "last_contact_at": None,
    }
