"""LOG3-1 — китайский импорт-фрахт → finance.

Контракт-фриз круга 3:
- эмит `logistics.freight.cost` с `leg='import'`, `ref='import:<id>'`, БЕЗ `deal_id`
  при ПЕРВОМ переходе stage→warehouse (prev_stage != warehouse) и amount>0;
- идемпотентность: повтор PATCH в warehouse не задваивает расход;
- движения склада здесь нет — приход делает procurement→wms;
- деньги в payload — str(BYN), не float (LOG3-2: дрейф копеек у finance Numeric).
"""
from __future__ import annotations

from sqlalchemy import select

from core.domain.models import OutboxEvent


async def _freight_imports_for(session, import_id: int) -> list[OutboxEvent]:
    """Все эмиты freight.cost с leg='import' для конкретного ImportShipment."""
    rows = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.cost")
    )).scalars().all()
    return [e for e in rows if e.payload.get("ref") == f"import:{import_id}"]


async def test_import_freight_emits_on_first_warehouse_transition(api, session):
    """LOG3-1: customs → warehouse эмитит ровно один freight.cost с leg='import'."""
    sid = (await api.post("/logistics/imports", json={
        "supplier": "Shenzhen Co", "cargo": "Контейнер 40HQ", "qty": 1,
        "amount": 8500.50, "stage": "customs", "po_ref": "purchase:777",
    })).json()["id"]
    r = await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
    assert r.status_code == 200

    events = await _freight_imports_for(session, sid)
    assert len(events) == 1, "ровно один freight.cost для импорта"
    p = events[0].payload
    assert p["leg"] == "import"
    assert p["ref"] == f"import:{sid}"
    assert p["entity_ref"] == f"import:{sid}"
    assert p["po_ref"] == "purchase:777"
    assert isinstance(p["amount"], str), "LOG3-2: деньги — str"
    assert p["amount"] == "8500.50"
    assert "deal_id" not in p, "контракт-фриз: deal_id у импорта НЕ передаём"


async def test_import_freight_idempotent_on_repeat(api, session):
    """Повтор PATCH stage=warehouse НЕ задваивает расход (потеря денег)."""
    sid = (await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Y", "qty": 1, "amount": 1000,
        "stage": "customs", "po_ref": "purchase:888",
    })).json()["id"]
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
    # повторяем — prev_stage уже warehouse, не должен эмитить второй freight.cost
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

    events = await _freight_imports_for(session, sid)
    assert len(events) == 1, "идемпотентность нарушена — двойной учёт!"


async def test_import_freight_zero_amount_no_emit(api, session):
    """amount=0 → НЕ эмитим freight.cost (нечего учитывать)."""
    sid = (await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Y", "qty": 1, "amount": 0,
        "stage": "customs", "po_ref": "purchase:999",
    })).json()["id"]
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

    events = await _freight_imports_for(session, sid)
    assert events == []


async def test_import_warehouse_does_not_move_stock(api, session):
    """Граница ответственности: stage→warehouse НЕ создаёт движений склада.

    Приход на склад — wms (по procurement.received). Логистика лишь информирует.
    """
    sid = (await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Y", "qty": 100, "amount": 500,
        "stage": "customs", "po_ref": "purchase:444",
    })).json()["id"]
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

    all_events = (await session.execute(select(OutboxEvent))).scalars().all()
    wms_from_us = [
        e for e in all_events
        if e.event_type.startswith("wms.") or e.event_type.startswith("inventory.")
    ]
    assert wms_from_us == [], "логистика не должна эмитить движения склада"


async def test_import_freight_only_first_transition_to_warehouse(api, session):
    """Не каждый PATCH stage=warehouse эмитит freight — только переход.

    Если поставка ПОПАЛА сразу в warehouse (создана с этим стейджем), а потом её
    патчем «трогают» обратно warehouse → НЕ эмитим. Защита от двойного учёта при
    миграциях стадии «вокруг» warehouse.
    """
    # Создаём поставку сразу в warehouse — это уже состояние, без перехода.
    sid = (await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Y", "qty": 1, "amount": 5000,
        "stage": "warehouse", "po_ref": "purchase:555",
    })).json()["id"]
    # PATCH с тем же stage warehouse — prev == warehouse, эмита быть не должно.
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

    events = await _freight_imports_for(session, sid)
    assert events == [], "повторный PATCH в тот же warehouse не должен эмитить"


async def test_import_freight_outbox_helper_isolated(session):
    """R5-1: helper `_import_freight_already_emitted` — изолированная проверка.

    Защищает outbox-страховку (B2 круга 3) от регрессии: помечает defence-in-depth
    через outbox-lookup, который срабатывает, когда `prev_stage`-проверка не помогает
    (сценарий warehouse→customs→warehouse). Если кто-то выкосит helper или сломает
    его условие — этот тест упадёт ДО интеграционных.
    """
    from core.domain.models import OutboxEvent
    from modules.logistics.routes import _import_freight_already_emitted

    # пустой outbox → ничего не эмиттилось → False
    assert await _import_freight_already_emitted(session, 42) is False

    # эмит чужого ref (другой import id) — для 42 всё ещё False (фильтр по ref)
    session.add(OutboxEvent(
        event_type="logistics.freight.cost", version=1,
        payload={"ref": "import:99", "leg": "import", "amount": "1000"},
    ))
    await session.flush()
    assert await _import_freight_already_emitted(session, 42) is False

    # эмит ровно нашего ref → True (повторный эмит должен быть заблокирован)
    session.add(OutboxEvent(
        event_type="logistics.freight.cost", version=1,
        payload={"ref": "import:42", "leg": "import", "amount": "2500"},
    ))
    await session.flush()
    assert await _import_freight_already_emitted(session, 42) is True

    # чужой event_type с тем же ref — НЕ считается freight (фильтр по типу)
    session.add(OutboxEvent(
        event_type="logistics.import.received", version=1,
        payload={"ref": "import:777"},
    ))
    await session.flush()
    assert await _import_freight_already_emitted(session, 777) is False


async def test_import_freight_no_doubling_on_rollback_and_retransition(api, session):
    """B2 (ревью круга 3): warehouse → customs → warehouse НЕ задваивает freight.cost.

    Откат и переотметка стадии (операционист исправил ошибку) — реальный сценарий.
    Без идемпотентности через outbox condition `prev != warehouse` срабатывает дважды
    и расход улетает в finance дважды (потеря денег).
    """
    sid = (await api.post("/logistics/imports", json={
        "supplier": "X", "cargo": "Y", "qty": 1, "amount": 3000,
        "stage": "customs", "po_ref": "purchase:bb",
    })).json()["id"]
    # 1) customs → warehouse: ровно один эмит
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
    assert len(await _freight_imports_for(session, sid)) == 1
    # 2) откат: warehouse → customs (по ошибке)
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "customs"})
    # 3) повторное warehouse — НЕ должно эмитить второй freight.cost
    await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
    events = await _freight_imports_for(session, sid)
    assert len(events) == 1, (
        "B2: defence-in-depth провален — двойной учёт фрахта при откате стадии"
    )
