"""Тесты модуля Integrations (чтение из 1С)."""


async def test_1c_sync(session, api):
    from sqlalchemy import select

    from core.domain.models import Counterparty, CounterpartyAlias, OutboxEvent

    r = await api.post("/integrations/1c/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["stock"] == 3
    assert body["counterparties"] == 3
    assert body["counterparty_aliases"] == 3  # на каждый контрагент 1С — alias-провенанс

    stock = (await api.get("/integrations/1c/stock")).json()
    assert len(stock) == 3
    assert any(s["sku_code"] == "AKB-60" for s in stock)

    counterparties = (await session.execute(select(Counterparty))).scalars().all()
    assert len(counterparties) >= 3

    # провенанс источника записан в golden record (Ref_Key 1С → counterparty_alias)
    onec_aliases = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(onec_aliases) == 3

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "integration.1c.synced" in types

    # повторный sync идемпотентен: ни новых контрагентов, ни дублей алиасов
    body2 = (await api.post("/integrations/1c/sync")).json()
    assert body2["new_counterparties"] == 0
    assert body2["counterparty_aliases"] == 0
    again = (
        await session.execute(select(CounterpartyAlias).where(CounterpartyAlias.source == "1c"))
    ).scalars().all()
    assert len(again) == 3


async def test_egr_lookup(api):
    # известный УНП → карточка контрагента из реестра ЕГР
    r = await api.get("/integrations/egr/191234567")
    assert r.status_code == 200
    body = r.json()
    assert body["unp"] == "191234567"
    assert "Аккумулятор" in body["name"]
    assert body["status"] == "Действующий"

    # неизвестный УНП → 404
    assert (await api.get("/integrations/egr/000000000")).status_code == 404


async def test_two_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    assert "sales" in data["loaded_modules"]
    assert "integrations" in data["loaded_modules"]
