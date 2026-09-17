from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.wms import events


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _ctx():
    session = FakeSession()
    return SimpleNamespace(session=session), session


@pytest.mark.asyncio
async def test_stock_reserved_creates_outgoing_movements_and_pick_tasks():
    ctx, session = _ctx()
    await events.on_stock_reserved(
        {"doc_ref": "deal:7", "items": [{"sku_code": "SKU-1", "qty": "2.5"}, {"sku_code": "SKU-2", "qty": 1, "warehouse": "B"}]},
        ctx,
    )
    assert len(session.added) == 4
    movement, task, movement2, task2 = session.added
    assert (movement.sku_code, movement.warehouse, movement.kind, movement.qty, movement.reason, movement.doc_ref) == ("SKU-1", "Главный", "out", Decimal("2.5"), "reserve", "deal:7")
    assert (task.kind, task.status, task.warehouse, task.doc_ref) == ("pick", "open", "Главный", "deal:7")
    assert movement2.warehouse == "B"
    assert task2.sku_code == "SKU-2"


@pytest.mark.asyncio
async def test_stock_released_creates_incoming_availability_movements():
    ctx, session = _ctx()
    await events.on_stock_released({"items": [{"sku_code": "SKU-1", "qty": "3"}]}, ctx)
    movement = session.added[0]
    assert (movement.kind, movement.reason, movement.qty, movement.warehouse) == ("in", "release", Decimal("3"), "Главный")
    await events.on_stock_reserved({"items": []}, None)
    await events.on_stock_released({"items": []}, None)
