"""Тесты «смена справочника → пересчёт плановой landed» (reference → procurement, круг 4 B2).

Справочники эмитят ``reference.ref_tnved.changed`` (пошлина) и ``reference.sku.changed``
(мастер-поля товара). Закупки пересчитывают ПЛАНОВУЮ (``estimated``) себестоимость затронутых
SKU по открытым (в пути) заказам через ГОТОВЫЙ фасад ``sku_master.landed_inputs`` (пошлина) +
движок ``allocate_landed_cost`` (фрахт). Главное — дебаунс против каскада (массовая правка =
шквал событий) и неприкосновенность факта приёмки (``actual`` важнее оценки в фасаде).

Фоновый relay в тестах не крутится — гоняем ``relay_once`` на той же in-memory сессии.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import core.services.sku_master as sku_master_mod
from core.domain.models import Sku
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.procurement.models import LandedCost, PurchaseOrder, PurchaseOrderLine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ref_app(session):
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


async def _seed(session, code, *, tnved=None, goods="1000", qty="10", freight="0", open_=True):
    """Товар + (опц.) открытый заказ с позицией на него. Открытый = в пути (оценка имеет смысл)."""
    session.add(Sku(code=code, title=code, tnved_code=tnved))
    if open_:
        o = PurchaseOrder(number=f"PO-{code}", supplier="S", status="ordered",
                          freight_byn=Decimal(freight))
        session.add(o)
        await session.flush()
        session.add(PurchaseOrderLine(order_id=o.id, sku_code=code, qty=Decimal(qty),
                                      goods_value_byn=Decimal(goods)))
    await session.commit()


async def _emit(core, session, event_type, **payload):
    core.event_bus.emit(session, event_type, payload)


async def _relay(core, session):
    await core.event_bus.relay_once(session, EventContext(session, core.services))


async def _landed(session, code, *, stage=None):
    q = select(LandedCost).where(LandedCost.sku_code == code)
    if stage:
        q = q.where(LandedCost.stage == stage)
    return (await session.execute(q)).scalars().all()


def _patch_duty(monkeypatch, pct):
    """Подменить фасад landed_inputs фиксированной пошлиной + счётчиком вызовов (для каскада)."""
    calls = {"n": 0}

    async def fake(session, sku_code, on_date=None):
        calls["n"] += 1
        return {"duty_pct": pct}

    monkeypatch.setattr(sku_master_mod, "landed_inputs", fake)
    return calls


# ───────────────────────── подписка ─────────────────────────


async def test_subscriptions_registered(ref_app):
    _, core = ref_app
    for et in ("reference.ref_tnved.changed", "reference.sku.changed"):
        handlers = core.event_bus._handlers.get(et, [])
        assert any(h.__name__ == "on_reference_changed" for h in handlers), et


# ───────────────────────── пересчёт значения ─────────────────────────


async def test_sku_change_recomputes_estimated(ref_app, session, monkeypatch):
    """``reference.sku.changed`` → одна плановая строка: (goods/qty)×(1+пошлина). 1000/10 ×1.1 = 110."""
    client, core = ref_app
    await _seed(session, "A", goods="1000", qty="10", freight="0")
    _patch_duty(monkeypatch, 10.0)
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)
    rows = await _landed(session, "A")
    assert len(rows) == 1
    r = rows[0]
    assert r.stage == "estimated" and r.purchase_order_id is None
    assert r.unit_landed_cost_byn == Decimal("110.0000")


async def test_freight_and_duty_in_estimate(ref_app, session, monkeypatch):
    """Фрахт входит в customs-стоимость до пошлины: (1000+200)/10 ×1.25 = 150."""
    client, core = ref_app
    await _seed(session, "A", goods="1000", qty="10", freight="200")
    _patch_duty(monkeypatch, 25.0)
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)
    rows = await _landed(session, "A")
    assert rows[0].unit_landed_cost_byn == Decimal("150.0000")


async def test_recompute_updates_in_place(ref_app, session, monkeypatch):
    """Повторная смена справочника обновляет ту же строку (не плодит дубль)."""
    client, core = ref_app
    await _seed(session, "A", goods="1000", qty="10")
    _patch_duty(monkeypatch, 10.0)
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)
    _patch_duty(monkeypatch, 20.0)  # пошлина выросла
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)
    rows = await _landed(session, "A")
    assert len(rows) == 1  # та же строка
    assert rows[0].unit_landed_cost_byn == Decimal("120.0000")


# ───────────────────────── маппинг ТН ВЭД → SKU ─────────────────────────


async def test_tnved_change_maps_only_matching_skus(ref_app, session, monkeypatch):
    """``reference.ref_tnved.changed`` пересчитывает только товары с этим кодом ТН ВЭД."""
    client, core = ref_app
    await _seed(session, "A", tnved="8501")
    await _seed(session, "B", tnved="9999")
    _patch_duty(monkeypatch, 0.0)
    await _emit(core, session, "reference.ref_tnved.changed",
                ref_key="core.tnved", entity_ref="ref_tnved:8501")
    await _relay(core, session)
    assert len(await _landed(session, "A")) == 1
    assert len(await _landed(session, "B")) == 0


# ───────────────────────── дебаунс против каскада ─────────────────────────


async def test_cascade_debounced_one_recompute_per_sku(ref_app, session, monkeypatch):
    """Шквал событий на один SKU за проход relay → пересчёт ровно раз (дедуп на ctx)."""
    client, core = ref_app
    await _seed(session, "A", tnved="8501")
    calls = _patch_duty(monkeypatch, 10.0)
    for _ in range(25):  # массовая правка справочника = каскад одинаковых событий
        await _emit(core, session, "reference.ref_tnved.changed",
                    ref_key="core.tnved", entity_ref="ref_tnved:8501")
    await _relay(core, session)
    assert calls["n"] == 1  # фасад дёрнут один раз, не 25
    assert len(await _landed(session, "A")) == 1  # одна строка, не 25 дублей


# ───────────────────────── граничные / защитные ─────────────────────────


async def test_no_open_order_skips(ref_app, session, monkeypatch):
    """Нет открытого заказа с SKU → базы для оценки нет → строку не пишем (не выдумываем нулём)."""
    client, core = ref_app
    await _seed(session, "A", open_=False)
    _patch_duty(monkeypatch, 10.0)
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)
    assert len(await _landed(session, "A")) == 0


async def test_irrelevant_ref_and_missing_entity_ref_noop(ref_app, session, monkeypatch):
    """Чужой справочник и пустой entity_ref — без пересчёта и без падения."""
    client, core = ref_app
    await _seed(session, "A")
    _patch_duty(monkeypatch, 10.0)
    await _emit(core, session, "reference.ref_unit.changed",  # не tnved/skus
                ref_key="core.units", entity_ref="ref_unit:шт")
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus")  # без entity_ref
    await _relay(core, session)
    assert len(await _landed(session, "A")) == 0


async def test_actual_receipt_preferred_over_estimate(ref_app, session, monkeypatch):
    """Факт приёмки (``actual``) важнее плановой оценки в фасаде себестоимости — оценка не затирает факт."""
    client, core = ref_app
    await _seed(session, "A", goods="1000", qty="10")
    session.add(LandedCost(sku_code="A", purchase_order_id=1, shipment_id="PO-A",
                           unit_landed_cost_byn=Decimal("90.0000"), stage="actual"))
    await session.commit()
    _patch_duty(monkeypatch, 10.0)
    await _emit(core, session, "reference.sku.changed", ref_key="core.skus", entity_ref="sku:A")
    await _relay(core, session)  # пишет estimated 110 (новее по fixed_at)
    facade = core.services.landed_cost
    one = await facade.last_landed_cost(session, "A")
    assert one["unit_landed_cost_byn"] == Decimal("90.0000") and one["stage"] == "actual"
    batch = await facade.last_landed_cost_batch(session, ["A"])
    assert batch["A"]["stage"] == "actual"  # факт побеждает и в батче
