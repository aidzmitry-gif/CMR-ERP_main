"""Bulk-upsert простых справочников: dry_run-план, идемпотентность, конфликты, аудит."""
from sqlalchemy import select

from core.domain.models import OutboxEvent

BASE = "/system/refs/units"


async def test_bulk_dry_run_then_apply_idempotent(api):
    await api.post(BASE, json={"code": "PCS", "title": "штука"})
    rows = [{"code": "PCS", "title": "штука!"}, {"code": "KG", "title": "килограмм"}]

    # dry_run: план без записи
    plan = (await api.post(f"{BASE}/bulk", json={"rows": rows, "dry_run": True})).json()
    assert plan["dry_run"] is True
    assert [c["key"] for c in plan["would_create"]] == ["KG"]
    assert [u["key"] for u in plan["would_update"]] == ["PCS"]
    items = {i["code"]: i for i in (await api.get(BASE)).json()}
    assert "KG" not in items  # ничего не создано
    assert items["PCS"]["title"] == "штука"  # ничего не обновлено

    # реальный прогон: создаёт/обновляет ровно ожидаемое
    res = (await api.post(f"{BASE}/bulk", json={"rows": rows})).json()
    assert res["created"] == 1 and res["updated"] == 1
    items = {i["code"]: i for i in (await api.get(BASE)).json()}
    assert items["KG"]["title"] == "килограмм"
    assert items["PCS"]["title"] == "штука!"

    # повтор идемпотентен: 0 изменений
    res2 = (await api.post(f"{BASE}/bulk", json={"rows": rows})).json()
    assert res2["created"] == 0 and res2["updated"] == 0


async def test_bulk_conflicts_dry_run(api):
    res = (await api.post(f"{BASE}/bulk", json={
        "dry_run": True,
        "rows": [
            {"title": "без кода"},          # нет key_field
            {"code": "DUP", "title": "a"},  # создаётся
            {"code": "DUP", "title": "b"},  # дубль ключа в наборе
            {"code": "NOREQ"},              # новый без обязательного title
        ],
    })).json()
    reasons = " | ".join(c["reason"] for c in res["conflicts"])
    assert "нет поля code" in reasons
    assert "дубль ключа" in reasons
    assert "не хватает" in reasons


async def test_bulk_emits_audit_per_row(api, session):
    await api.post(f"{BASE}/bulk", json={"rows": [{"code": "M", "title": "метр"}]})
    evs = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "reference.ref_unit.changed")
        )
    ).scalars().all()
    assert any(
        e.payload.get("action") == "bulk_upsert" and e.payload.get("entity_ref") == "ref_unit:M"
        for e in evs
    )


async def test_bulk_requires_system_write(api):
    r = await api.post(
        f"{BASE}/bulk", json={"rows": [{"code": "X", "title": "x"}]},
        headers={"X-User-Roles": "warehouse"},
    )
    assert r.status_code in (401, 403)
