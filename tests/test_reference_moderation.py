"""Модерация чувствительных справочников: ставка НДС/пошлина → Approval (human-in-the-loop)."""
from sqlalchemy import select

from core.domain.models import Approval


async def test_sensitive_vat_creates_approval(api, session):
    r = await api.post(
        "/system/refs/vat-rates/versions",
        json={"code": "НДС20", "title": "НДС 20%", "rate": 20, "start_date": "2026-01-01"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending_approval"
    # версия НЕ записана сразу — ждёт согласования
    assert (await api.get("/system/refs/vat-rates?key=НДС20")).json() == []
    apprs = (
        await session.execute(select(Approval).where(Approval.kind == "reference.change"))
    ).scalars().all()
    assert apprs and apprs[0].status == "pending"
    assert apprs[0].entity_ref == "ref_vat_rate:НДС20"


async def test_sensitive_tnved_creates_approval(api):
    r = await api.post(
        "/system/refs/tnved/versions",
        json={"code": "8536", "name": "реле", "duty_rate": 5, "start_date": "2026-01-01"},
    )
    assert r.json()["status"] == "pending_approval"


async def test_nonsensitive_currency_writes_immediately(api):
    r = await api.post(
        "/system/refs/currency-rates/versions",
        json={"currency_code": "USD", "rate": 3.2, "start_date": "2026-01-01"},
    )
    assert r.status_code == 200
    assert "id" in r.json()  # записано как раньше, без согласования
    assert len((await api.get("/system/refs/currency-rates?key=USD")).json()) == 1


async def test_moderation_requires_system_write(api):
    r = await api.post(
        "/system/refs/vat-rates/versions",
        json={"code": "X", "rate": 1, "start_date": "2026-01-01"},
        headers={"X-User-Roles": "warehouse"},
    )
    assert r.status_code in (401, 403)
