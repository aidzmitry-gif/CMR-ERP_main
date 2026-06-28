"""REF3-8 — запись датированной версии SKU при правке мастер-полей (SCD2) + чтение as_of.

``record_sku_version`` существовал, но не вызывался ни из одной точки правки (history был пуст).
Подключён в PATCH /system/sku/{code}: смена мастер-поля открывает датированную версию.
"""
from datetime import date

from sqlalchemy import select

from core.domain.models import OutboxEvent, Sku
from core.domain.reference import SkuVersion
from core.services import sku_history


async def _sku_changed_events(session) -> list:
    return (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "reference.sku.changed")
        )
    ).scalars().all()


async def test_record_sku_version_idempotent_and_dated(session):
    sku = Sku(code="S1", title="Товар", unit="шт", weight_kg=5.0)
    session.add(sku)
    await session.flush()

    v1 = await sku_history.record_sku_version(session, sku, date(2024, 1, 1))
    assert v1 is not None
    # повтор без изменений снимка — версию не плодим
    assert await sku_history.record_sku_version(session, sku, date(2024, 6, 1)) is None
    # изменение → новая версия с новой даты, прежняя закрыта этой датой
    sku.weight_kg = 7.0
    v2 = await sku_history.record_sku_version(session, sku, date(2025, 1, 1))
    assert v2 is not None
    await session.commit()

    rows = (
        await session.execute(
            select(SkuVersion).where(SkuVersion.sku_code == "S1").order_by(SkuVersion.start_date)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].end_date == date(2025, 1, 1)  # прежняя закрыта датой новой
    assert rows[1].end_date is None  # текущая открыта


async def test_patch_sku_records_version(api, session):
    session.add(Sku(code="S2", title="Товар2", unit="шт", weight_kg=1.0))
    await session.commit()

    r = await api.patch("/system/sku/S2", json={"weight_kg": 3.0, "tnved_code": "8507"})
    assert r.status_code == 200
    assert set(r.json()["changed"]) == {"weight_kg", "tnved_code"}

    rows = (
        await session.execute(select(SkuVersion).where(SkuVersion.sku_code == "S2"))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].weight_kg == 3.0 and rows[0].tnved_code == "8507"  # снимок ПОСЛЕ правки


async def test_patch_sku_requires_system_write(api, session):
    session.add(Sku(code="S3", title="Товар3", unit="шт"))
    await session.commit()
    r = await api.patch(
        "/system/sku/S3", json={"weight_kg": 2.0}, headers={"X-User-Roles": "warehouse"}
    )
    assert r.status_code in (401, 403)  # мутация мастер-данных — под system.write


async def test_patch_sku_repeat_no_new_version(api, session):
    session.add(Sku(code="S4", title="Товар4", unit="шт", weight_kg=2.0))
    await session.commit()
    await api.patch("/system/sku/S4", json={"weight_kg": 5.0})  # v1
    await api.patch("/system/sku/S4", json={"weight_kg": 5.0})  # без изменений → не плодит
    rows = (
        await session.execute(select(SkuVersion).where(SkuVersion.sku_code == "S4"))
    ).scalars().all()
    assert len(rows) == 1


async def test_patch_sku_same_day_change_coalesces(api, session):
    session.add(Sku(code="S6", title="Товар6", unit="шт", weight_kg=1.0))
    await session.commit()
    await api.patch("/system/sku/S6", json={"weight_kg": 2.0})  # v1 (сегодня)
    r = await api.patch("/system/sku/S6", json={"weight_kg": 3.0})  # тот же день, есть изменение
    assert r.status_code == 200
    rows = (
        await session.execute(select(SkuVersion).where(SkuVersion.sku_code == "S6"))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].weight_kg == 3.0  # текущая версия обновлена на месте (две версии в день SCD2 запрещает)


async def test_patch_sku_404(api):
    assert (await api.patch("/system/sku/NOPE", json={"weight_kg": 1.0})).status_code == 404


async def test_patch_sku_emits_changed_with_entity_ref_and_hint(api, session):
    """Круг5: реальная правка мастер-поля → ровно одно reference.sku.changed с entity_ref+value_hint."""
    session.add(Sku(code="EV1", title="t", unit="шт", weight_kg=1.0))
    await session.commit()
    await api.patch("/system/sku/EV1", json={"weight_kg": 4.0, "tnved_code": "8507"})
    evs = await _sku_changed_events(session)
    assert len(evs) == 1
    p = evs[0].payload
    assert p["entity_ref"] == "sku:EV1" and p["ref_key"] == "core.skus"
    assert set(p["value_hint"].split(",")) == {"weight_kg", "tnved_code"}


async def test_patch_sku_no_op_does_not_emit(api, session):
    """Круг5: no-op PATCH (те же значения ИЛИ без мастер-полей) НЕ эмитит событие и не плодит версию."""
    session.add(Sku(code="EV2", title="t", unit="шт", weight_kg=2.0))
    await session.commit()
    await api.patch("/system/sku/EV2", json={"weight_kg": 2.0})  # то же значение → no-op
    await api.patch("/system/sku/EV2", json={"note": "не мастер-поле"})  # нет мастер-полей → no-op
    assert await _sku_changed_events(session) == []
    vers = (
        await session.execute(select(SkuVersion).where(SkuVersion.sku_code == "EV2"))
    ).scalars().all()
    assert vers == []  # версию тоже не плодим


async def test_sku_history_as_of_via_query(api, session):
    sku = Sku(code="S5", title="Товар5", unit="шт", weight_kg=1.0)
    session.add(sku)
    await session.flush()
    await sku_history.record_sku_version(session, sku, date(2024, 1, 1))
    sku.weight_kg = 9.0
    await sku_history.record_sku_version(session, sku, date(2025, 1, 1))
    await session.commit()

    r = await api.post(
        "/system/references/query",
        json={"ref": "core.sku_history", "key": "S5", "as_of": "2024-06-01"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["weight_kg"] == 1.0  # версия, действовавшая на дату
