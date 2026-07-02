"""Тесты подписок модуля Production на события шины.

- ``sales.deal.handoff``  → ProductionPlan создан с deal_id (идемпотентно).
- ``procurement.order.received`` → graceful no-op.

Гоняем через core.event_bus.relay_once (как реальный фоновый relay),
чтобы проверить именно зарегистрированные в module.register подписки.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from core.runtime.app import create_app
from modules.production.models import ProductionPlan


def _core_ctx(session):
    core = create_app().state.core
    return core, SimpleNamespace(session=session, services=core.services)


async def test_deal_handoff_creates_plan(session):
    """sales.deal.handoff → ProductionPlan создан с нужным deal_id."""
    core, ctx = _core_ctx(session)
    core.event_bus.emit(session, "sales.deal.handoff", {"deal_id": 99, "product": "АКБ-100"})
    await core.event_bus.relay_once(session, ctx)

    plans = (
        await session.execute(select(ProductionPlan).where(ProductionPlan.deal_id == 99))
    ).scalars().all()
    assert len(plans) == 1
    assert plans[0].deal_id == 99
    assert plans[0].source_event == "sales.deal.handoff"


async def test_deal_handoff_idempotent(session):
    """Второй emit с тем же deal_id не создаёт дубль."""
    core, ctx = _core_ctx(session)
    core.event_bus.emit(session, "sales.deal.handoff", {"deal_id": 42, "product": "АКБ-50"})
    core.event_bus.emit(session, "sales.deal.handoff", {"deal_id": 42, "product": "АКБ-50"})
    await core.event_bus.relay_once(session, ctx)

    plans = (
        await session.execute(select(ProductionPlan).where(ProductionPlan.deal_id == 42))
    ).scalars().all()
    assert len(plans) == 1


async def test_deal_handoff_no_deal_id_noop(session):
    """Payload без deal_id → план не создаётся."""
    core, ctx = _core_ctx(session)
    core.event_bus.emit(session, "sales.deal.handoff", {"product": "АКБ-200"})
    await core.event_bus.relay_once(session, ctx)

    plans = (await session.execute(select(ProductionPlan))).scalars().all()
    assert plans == []


async def test_order_received_graceful(session):
    """procurement.order.received не падает при отсутствии связанного плана."""
    core, ctx = _core_ctx(session)
    core.event_bus.emit(
        session, "procurement.order.received", {"po_number": "PO-001", "sku_codes": ["АКБ-001"]}
    )
    await core.event_bus.relay_once(session, ctx)
    # нет assert — убеждаемся, что relay не выбросил исключение


async def test_import_main():
    """import main резолвится без ошибок (целостность реестра модулей)."""
    import importlib

    importlib.import_module("main")
