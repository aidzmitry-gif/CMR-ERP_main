"""Добор покрытия backend: guard-ветки обработчиков, резерв склада, sync 1С, загрузчик."""
import types
from types import SimpleNamespace

import pytest


def _ctx(session):
    return SimpleNamespace(session=session, services=SimpleNamespace())


def test_loader_resolve_errors(monkeypatch):
    from core.runtime import loader

    fake = types.ModuleType("modules.fake.module")
    monkeypatch.setattr(loader.importlib, "import_module", lambda name: fake)
    # нет фабрики get_module() → RuntimeError
    with pytest.raises(RuntimeError):
        loader._resolve_module("fake")
    # get_module() вернул не ModuleContract → TypeError
    fake.get_module = lambda: object()
    with pytest.raises(TypeError):
        loader._resolve_module("fake")


async def test_payment_paid_guard_branches(session):
    from modules.sales.events import on_payment_paid

    # нет ref → ранний выход; ref без документа → ничего не меняем
    await on_payment_paid({}, _ctx(session))
    await on_payment_paid({"ref": "НЕТ-ТАКОГО"}, _ctx(session))


async def test_shipment_delivered_guard_branches(session):
    from modules.sales.events import on_shipment_delivered

    # нет deal_id → ранний выход; несуществующая сделка → no-op
    await on_shipment_delivered({}, _ctx(session))
    await on_shipment_delivered({"deal_id": 999999}, _ctx(session))


async def test_stock_reserve_skip_branches(session):
    from modules.integrations.models import StockItem
    from modules.integrations.stock import StockService

    svc = StockService()
    # пустой список / без кода / нулевое qty / неизвестный SKU — всё пропускается
    assert await svc.reserve(session, []) == []
    assert await svc.reserve(session, [{"sku_code": "", "qty": 1}]) == []
    assert await svc.reserve(session, [{"sku_code": "X", "qty": 0}]) == []
    assert await svc.reserve(session, [{"sku_code": "НЕТ", "qty": 5}]) == []

    session.add(StockItem(sku_code="RS-1", warehouse="Главный", qty_available=100, qty_reserved=2))
    await session.commit()
    res = await svc.reserve(session, [{"sku_code": "RS-1", "qty": 3}])
    assert res and res[0]["sku_code"] == "RS-1" and res[0]["qty"] == 3


async def test_sync_1c_idempotent_update(api):
    # первый sync создаёт записи, второй — обновляет существующие (ветка upsert)
    r1 = await api.post("/integrations/1c/sync")
    assert r1.status_code in (200, 201)
    r2 = await api.post("/integrations/1c/sync")
    assert r2.status_code in (200, 201)
