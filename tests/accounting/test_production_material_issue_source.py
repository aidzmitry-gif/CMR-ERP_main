from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from modules.production.accounting_ownership import ProductionOrderOwnership, order_snapshot
from modules.production.models import ProductionOrder
from modules.wms import production_material_issues
from modules.wms.models import StockMovement


class Gateway:
    async def source_member(self, _session, _organization_id, _user):
        return "tester"

    async def source_write_authority(self, _session, _organization_id, _user):
        return "tester"


class EventBus:
    def __init__(self):
        self.events = []

    def emit(self, _session, event_type, payload):
        self.events.append((event_type, payload))


@pytest_asyncio.fixture
async def source_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", execution_options={
        "schema_translate_map": {"production": None, "wms": None},
    })
    tables = [ProductionOrder.__table__, ProductionOrderOwnership.__table__,
              StockMovement.__table__, production_material_issues.ProductionMaterialIssue.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def command(order_id: int, digest: str):
    return production_material_issues.ProductionMaterialIssueCommand(
        request_id=uuid4(), order_id=order_id, expected_order_digest=digest,
        operation_date=date(2026, 10, 10), sku_code="MAT-1", quantity="1.00",
        warehouse="Main", lot="LOT-1", evidence="Reviewed material issue source",
    )


@pytest.mark.asyncio
async def test_material_issue_source_is_previewed_recorded_and_exactly_replayed(source_db, monkeypatch):
    async def no_free(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_material_issues, "guard_free", no_free)
    order = ProductionOrder(number="MAT-ORDER", product="Widget", qty=1)
    source_stock = StockMovement(organization_id=11, sku_code="MAT-1", warehouse="Main",
                                 kind="in", qty="2.00", reason="receipt", batch_ref="LOT-1")
    source_db.add_all([order, source_stock])
    await source_db.flush()
    snapshot, digest = order_snapshot(order)
    source_db.add(ProductionOrderOwnership(order_id=order.id, organization_id=11,
                                           snapshot=snapshot, digest=digest,
                                           evidence="Reviewed production owner", actor="tester"))
    await source_db.commit()
    data = command(order.id, digest)
    gateway, events = Gateway(), EventBus()

    preview = await production_material_issues.preview_material_issue(source_db, gateway, 11, "tester", data)
    assert preview["posted"] is False and preview["source"].startswith("production_material:")
    assert await source_db.scalar(select(func.count()).select_from(production_material_issues.ProductionMaterialIssue)) == 0

    row, movement = await production_material_issues.record_material_issue(
        source_db, gateway, 11, "tester", data, event_bus=events)
    await source_db.commit()
    replay, replay_movement = await production_material_issues.record_material_issue(
        source_db, gateway, 11, "tester", data, event_bus=events)
    assert (replay.id, replay_movement.id) == (row.id, movement.id)
    assert len(events.events) == 1 and events.events[0][0] == "production.material.issued"
    assert await source_db.scalar(select(func.count()).select_from(production_material_issues.ProductionMaterialIssue)) == 1
    assert movement.reason == "production_issue" and movement.doc_ref == preview["source"]
    assert row.snapshot["movement"]["qty"] == "1.00"

    with pytest.raises(HTTPException) as conflict:
        await production_material_issues.record_material_issue(
            source_db, gateway, 11, "tester", data.model_copy(update={"evidence": "Changed reviewed source"}))
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_material_issue_source_requires_owned_order(source_db, monkeypatch):
    async def no_free(*_args, **_kwargs):
        return None

    monkeypatch.setattr(production_material_issues, "guard_free", no_free)
    order = ProductionOrder(number="PRIVATE", product="Widget", qty=1)
    source_db.add(order)
    await source_db.flush()
    _, digest = order_snapshot(order)
    data = command(order.id, digest)
    with pytest.raises(HTTPException) as missing:
        await production_material_issues.preview_material_issue(source_db, Gateway(), 11, "tester", data)
    assert missing.value.status_code == 404
