"""Тесты «срок клиента → план машины» (sales → procurement): подписка на
``sales.deal.ship_deadline.set`` + обратное планирование от срока − буфер + риск срыва/штрафа.

Продажи эмитят крайнюю дату отгрузки клиенту; закупки складывают её как требование по (сделка, sku)
и планируют машину так, чтобы прийти в Минск к самому раннему сроку минус буфер последней мили.
Фоновый relay в тестах не крутится — гоняем ``relay_once`` на той же in-memory сессии.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.eventbus import EventContext
from modules.procurement.models import ShipRequirement

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def deadline_app(session):
    app = create_app()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"X-User-Roles": "director"}
    ) as client:
        yield client, app.state.core


async def _emit_deadline(core, session, **over):
    payload = {
        "deal_id": 1, "number": "СД-1", "counterparty": "ООО Клиент",
        "ship_deadline": "2026-12-31", "penalty_rate_pct": 0.5, "penalty_cap_pct": 10.0,
        "penalty_terms": "0.5%/день, до 10%", "items": [{"sku_code": "A", "qty": 5}],
        "actor": "sales", "entity_ref": "deal:1",
    }
    payload.update(over)
    core.event_bus.emit(session, "sales.deal.ship_deadline.set", payload)
    await core.event_bus.relay_once(session, EventContext(session, core.services))


async def _reqs(session):
    return (await session.execute(select(ShipRequirement))).scalars().all()


async def _order(client, **over):
    body = {"supplier": "S", "lines": [{"sku_code": "A", "qty": 5, "goods_value_byn": 500}]}
    body.update(over)
    r = await client.post("/procurement/orders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ───────────────────────── подписка на срок клиента ─────────────────────────


async def test_subscription_registered(deadline_app):
    _, core = deadline_app
    handlers = core.event_bus._handlers.get("sales.deal.ship_deadline.set", [])
    assert any(h.__name__ == "on_ship_deadline_set" for h in handlers)


async def test_deadline_event_stores_requirement(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session)
    rows = await _reqs(session)
    assert len(rows) == 1
    r = rows[0]
    assert r.deal_id == 1 and r.sku_code == "A"
    assert r.ship_deadline == "2026-12-31"
    assert str(r.ship_deadline_date) == "2026-12-31"  # разобрана в дату
    assert float(r.penalty_rate_pct) == 0.5


async def test_deadline_event_idempotent_and_syncs_items(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 5}, {"sku_code": "B", "qty": 2}])
    assert {r.sku_code for r in await _reqs(session)} == {"A", "B"}
    # повтор с другим сроком + убрана позиция B → A обновлена, B снята (не дубль)
    await _emit_deadline(core, session, ship_deadline="2026-11-30", items=[{"sku_code": "A", "qty": 9}])
    rows = await _reqs(session)
    assert {r.sku_code for r in rows} == {"A"}  # B снята
    assert rows[0].ship_deadline == "2026-11-30" and float(rows[0].qty) == 9  # A обновлена


async def test_deadline_event_without_deal_id_skipped(deadline_app, session):
    client, core = deadline_app
    await _emit_deadline(core, session, deal_id=None)
    assert await _reqs(session) == []


# ───────────────────────── обратное планирование от срока + риск ─────────────────────────


async def test_plan_auto_derives_target_from_deadline(deadline_app, session):
    """План без явной даты: target = самый ранний срок клиента − буфер (3 дня)."""
    client, core = deadline_app
    o = await _order(client)
    await _emit_deadline(core, session, ship_deadline="2026-12-31")  # позиция A
    r = await client.post(
        f"/procurement/orders/{o['id']}/plan", json={"transport_method_code": "container"}
    )
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["required_by"] == "2026-12-31"
    assert plan["required_arrival"] == "2026-12-28"  # срок − буфер 3
    assert plan["target_arrival_date"] == "2026-12-28"  # авто-подсказка
    assert plan["at_risk"] is False
    assert plan["slack_days"] == 0


async def test_plan_flags_risk_and_penalty_when_late(deadline_app, session):
    """Срок клиента раньше планового прихода → at_risk + сделка в at_risk_deals со штрафом."""
    client, core = deadline_app
    o = await _order(client, lines=[{"sku_code": "B", "qty": 1, "goods_value_byn": 100}])
    await _emit_deadline(
        core, session, deal_id=2, number="СД-2", ship_deadline="2026-07-05",
        penalty_rate_pct=1.0, items=[{"sku_code": "B", "qty": 1}],
    )
    # target позже крайней даты (2026-07-02), но старт в будущем — риск чисто от срока
    r = await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-10-01"},
    )
    plan = r.json()
    assert plan["required_arrival"] == "2026-07-02"  # 2026-07-05 − 3
    assert plan["at_risk"] is True
    assert len(plan["at_risk_deals"]) == 1
    d = plan["at_risk_deals"][0]
    assert d["number"] == "СД-2" and d["penalty_rate_pct"] == 1.0
    assert d["slack_days"] < 0  # опоздание


async def test_plan_no_target_no_deadline_422(deadline_app, session):
    """Без явной даты и без срока клиента — планировать не от чего → 422."""
    client, _ = deadline_app
    o = await _order(client)  # позиция A, но требований нет
    r = await client.post(
        f"/procurement/orders/{o['id']}/plan", json={"transport_method_code": "container"}
    )
    assert r.status_code == 422


async def test_deadline_event_duplicate_sku_no_crash(deadline_app, session):
    """Дубль sku в позициях сделки → одна строка (UNIQUE не падает, relay не зависает) — last-write-wins."""
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 3}, {"sku_code": "A", "qty": 5}])
    rows = [r for r in await _reqs(session) if r.sku_code == "A"]
    assert len(rows) == 1 and float(rows[0].qty) == 5


async def test_deadline_empty_items_preserves_requirements(deadline_app, session):
    """Сигнал с пустыми позициями НЕ стирает уже сохранённые требования сделки (защита от стирания)."""
    client, core = deadline_app
    await _emit_deadline(core, session, items=[{"sku_code": "A", "qty": 3}, {"sku_code": "B", "qty": 1}])
    assert len(await _reqs(session)) == 2
    await _emit_deadline(core, session, items=[])  # пустой сигнал
    assert len(await _reqs(session)) == 2  # ничего не стёрто


async def test_unplanned_machine_with_deadline_is_at_risk(deadline_app, session):
    """Машина с живым сроком клиента, но БЕЗ плана (GET до POST /plan) — at_risk=True, не «зелёная»."""
    client, core = deadline_app
    o = await _order(client)  # позиция A
    await _emit_deadline(core, session, ship_deadline="2026-12-31")
    plan = (await client.get(f"/procurement/orders/{o['id']}/plan")).json()
    assert plan["target_arrival_date"] is None  # ещё не планировали
    assert plan["required_arrival"] == "2026-12-28"
    assert plan["at_risk"] is True  # наивысший риск: срок есть, машина не запланирована


async def test_plan_multi_deal_earliest_deadline_wins(deadline_app, session):
    """Две сделки на один sku машины: required_by = самый ранний срок; в риске только опоздавшая."""
    client, core = deadline_app
    o = await _order(client)  # позиция A
    await _emit_deadline(core, session, deal_id=1, number="СД-1", ship_deadline="2027-06-01",
                         items=[{"sku_code": "A", "qty": 1}])  # комфортный
    await _emit_deadline(core, session, deal_id=2, number="СД-2", ship_deadline="2026-11-20",
                         penalty_rate_pct=1.0, items=[{"sku_code": "A", "qty": 1}])  # жёсткий
    plan = (await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2027-01-01"},
    )).json()
    assert plan["required_by"] == "2026-11-20" and plan["required_arrival"] == "2026-11-17"
    assert {d["number"] for d in plan["at_risk_deals"]} == {"СД-2"}  # СД-1 (2027-06-01) — успеваем


async def test_unparsed_deadline_ignored_in_plan(deadline_app, session):
    """Неразобранный срок не участвует: единственный такой → 422 авто; в смеси — не в риске/required_by."""
    client, core = deadline_app
    o = await _order(client)  # позиция A
    await _emit_deadline(core, session, deal_id=1, number="СД-J", ship_deadline="24 июля 2026",
                         items=[{"sku_code": "A", "qty": 1}])
    assert (await client.post(
        f"/procurement/orders/{o['id']}/plan", json={"transport_method_code": "container"}
    )).status_code == 422  # единственный срок неразобран → авто-подсказки нет
    await _emit_deadline(core, session, deal_id=2, number="СД-OK", ship_deadline="2026-12-31",
                         items=[{"sku_code": "A", "qty": 1}])
    plan = (await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2027-06-01"},
    )).json()
    assert plan["required_by"] == "2026-12-31"  # junk проигнорирован
    assert all(d["number"] != "СД-J" for d in plan["at_risk_deals"])


async def test_past_start_is_at_risk(deadline_app, session):
    """Старт сбора уже в прошлом (близкий target, длинный контейнер 112 дн) → at_risk=True без срыва срока."""
    client, _ = deadline_app
    o = await _order(client)  # требований нет
    plan = (await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "container", "target_arrival_date": "2026-08-01"},
    )).json()
    assert plan["start_date"] < "2026-06-28"  # старт раньше сегодня (ISO-строки сравнимы)
    assert plan["at_risk"] is True


async def test_slack_days_exact_both_sides(deadline_app, session):
    """Точный slack: комфортный (+, не риск) и опоздание (−, риск). required_arrival = 2026-12-28."""
    client, core = deadline_app
    o = await _order(client)
    await _emit_deadline(core, session, ship_deadline="2026-12-31", items=[{"sku_code": "A", "qty": 1}])
    early = (await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2026-12-23"},
    )).json()
    assert early["slack_days"] == 5 and early["at_risk"] is False
    late = (await client.post(
        f"/procurement/orders/{o['id']}/plan",
        json={"transport_method_code": "truck", "target_arrival_date": "2027-01-01"},
    )).json()
    assert late["slack_days"] == -4 and late["at_risk"] is True
