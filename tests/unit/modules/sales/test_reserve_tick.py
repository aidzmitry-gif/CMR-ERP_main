from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.sales import reserve


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def scalars(self):
        return self


class Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return Result(self.rows)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


@pytest.mark.asyncio
async def test_reserve_tick_releases_expired_invoice_and_reminds_before_expiry(monkeypatch):
    now = datetime(2026, 9, 17, 10, 0)
    monkeypatch.setattr(reserve, "_utcnow", lambda: now)
    monkeypatch.setattr(reserve, "_deal_stock_items", AsyncMock(return_value=[{"sku_code": "SKU-1", "qty": 2.0}]))
    expired = SimpleNamespace(
        id=1, deal_id=10, number="INV-1", valid_until=date(2026, 9, 16),
        status="issued", reserve_status="reserved", reminded_at=None, cancelled_at=None,
    )
    expiring = SimpleNamespace(
        id=2, deal_id=11, number="INV-2", valid_until=date(2026, 9, 18),
        status="issued", reserve_status="reserved", reminded_at=None, cancelled_at=None,
    )
    bus = Bus()
    release = AsyncMock()
    services = SimpleNamespace(stock=SimpleNamespace(release=release), event_bus=bus)
    await reserve.tick_invoice_reserve(Session([expired, expiring]), services)

    assert (expired.status, expired.reserve_status, expired.cancelled_at) == ("cancelled", "released", now)
    assert expired.reminded_at is None
    assert expiring.reminded_at == now
    release.assert_awaited_once()
    assert [call[1] for call in bus.calls] == ["sales.invoice.cancelled", "sales.stock.released", "sales.invoice.expiring"]


@pytest.mark.asyncio
async def test_sync_tick_is_quiet_without_gateway_and_delegates_when_present(monkeypatch):
    flush = AsyncMock()
    monkeypatch.setattr("modules.integrations.sync_tick.sync_outbound.flush_pending", flush)
    session = object()
    await __import__("modules.integrations.sync_tick", fromlist=["tick_sync_out"]).tick_sync_out(
        session, SimpleNamespace(onec=None)
    )
    flush.assert_not_awaited()
    gateway = object()
    await __import__("modules.integrations.sync_tick", fromlist=["tick_sync_out"]).tick_sync_out(
        session, SimpleNamespace(onec=gateway)
    )
    flush.assert_awaited_once_with(session, gateway)
