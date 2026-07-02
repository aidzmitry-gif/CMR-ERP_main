"""Круг 5 — тест-харднинг полосы sales (edge-cases кругов 2-4).

- R5-1 деньго-границы штрафа (guard: pydantic ge/le/max_length).
- R5-2 крайняя дата отгрузки прошлое/null (guard: эмит только на непустую смену).
- R5-3 запрет переноса в стадию ЧУЖОЙ воронки (фикс: 422).
- R5-4 margin_blind — честность null, не 0 (фикс, деньго-чувствительно).
- R5-5 идемпотентность handoff (guard: дедуп по deal_id).

Хелперы переиспользуются из test_sales_deals_v2 (_new_deal/_FakeLanded/_seed_sku).
"""
import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from core.services.eventbus import EventContext
from modules.sales.events import on_deal_won_handoff
from tests.test_sales_deals_v2 import _FakeLanded, _new_deal, _seed_sku

# ══ R5-1: деньго-границы штрафа (Numeric(6,2)/String) → 422, не DB overflow ══
# Guard: на коде БЕЗ Field-границ SQLite принял бы 10000 / строку >512 (не enforce-ит) → 201,
# и все «422» упали бы. На Postgres было бы DataError→500. Границы режут это в 422 на валидации.

async def test_penalty_rate_pct_max_accepted(api):
    r = await api.post("/sales/deals", json={
        "number": "PR-1", "title": "t", "counterparty": "c", "penalty_rate_pct": 9999.99})
    assert r.status_code == 201
    assert r.json()["penalty_rate_pct"] == pytest.approx(9999.99)


async def test_penalty_rate_pct_over_max_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "PR-2", "title": "t", "counterparty": "c", "penalty_rate_pct": 10000})
    assert r.status_code == 422


async def test_penalty_rate_pct_negative_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "PR-3", "title": "t", "counterparty": "c", "penalty_rate_pct": -0.01})
    assert r.status_code == 422


async def test_penalty_cap_pct_max_accepted(api):
    r = await api.post("/sales/deals", json={
        "number": "PC-1", "title": "t", "counterparty": "c", "penalty_cap_pct": 9999.99})
    assert r.status_code == 201
    assert r.json()["penalty_cap_pct"] == pytest.approx(9999.99)


async def test_penalty_cap_pct_over_max_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "PC-2", "title": "t", "counterparty": "c", "penalty_cap_pct": 10000})
    assert r.status_code == 422


async def test_penalty_cap_pct_negative_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "PC-3", "title": "t", "counterparty": "c", "penalty_cap_pct": -0.01})
    assert r.status_code == 422


async def test_penalty_terms_max_length_accepted(api):
    r = await api.post("/sales/deals", json={
        "number": "PT-1", "title": "t", "counterparty": "c", "penalty_terms": "А" * 512})
    assert r.status_code == 201


async def test_penalty_terms_over_max_length_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "PT-2", "title": "t", "counterparty": "c", "penalty_terms": "А" * 513})
    assert r.status_code == 422


async def test_ship_deadline_max_length_accepted(api):
    r = await api.post("/sales/deals", json={
        "number": "SD-1", "title": "t", "counterparty": "c", "ship_deadline": "D" * 32})
    assert r.status_code == 201


async def test_ship_deadline_over_max_length_rejected(api):
    r = await api.post("/sales/deals", json={
        "number": "SD-2", "title": "t", "counterparty": "c", "ship_deadline": "D" * 33})
    assert r.status_code == 422


async def test_patch_penalty_rate_pct_over_max_rejected(api):
    deal = await _new_deal(api, "PU-1")
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"penalty_rate_pct": 10000})
    assert r.status_code == 422


async def test_patch_penalty_terms_over_max_length_rejected(api):
    deal = await _new_deal(api, "PU-3")
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"penalty_terms": "X" * 513})
    assert r.status_code == 422


async def test_patch_all_penalty_fields_valid(api):
    deal = await _new_deal(api, "PU-5")
    r = await api.patch(f"/sales/deals/{deal['id']}", json={
        "penalty_rate_pct": 5.5, "penalty_cap_pct": 10.0,
        "penalty_terms": "Штраф 0.5% в день", "ship_deadline": "2026-12-31"})
    assert r.status_code == 200
    body = r.json()
    assert body["penalty_rate_pct"] == pytest.approx(5.5)
    assert body["penalty_cap_pct"] == pytest.approx(10.0)
    assert body["penalty_terms"] == "Штраф 0.5% в день"
    assert body["ship_deadline"] == "2026-12-31"


# ══ R5-2: крайняя дата отгрузки — прошлое/null (детерминизм эмита) ══
# Guard: эмит sales.deal.ship_deadline.set только на непустую СМЕНУ; "" / null / повтор — нет.

async def test_empty_string_deadline_no_emit(api, session):
    """PATCH ship_deadline='' → НЕ эмитит (нечего слать в закупки), не 500."""
    deal = await _new_deal(api, "R5-A-1", amount=500)
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": ""})
    assert r.status_code == 200
    evs = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(evs) == 0


async def test_clear_deadline_after_set_no_emit(api, session):
    """Была дата → PATCH '' → нет нового сигнала, не падает."""
    deal = await _new_deal(api, "R5-B-1", ship_deadline="2026-08-01")
    after_create = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(after_create) == 1  # эмит при создании с датой
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": ""})
    assert r.status_code == 200
    after_clear = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(after_clear) == 1  # очистка не плодит новый сигнал
    assert r.json()["ship_deadline"] in ("", None)


async def test_past_deadline_accepted_and_emits(api, session):
    """Дата в прошлом → принимается (просрочка) И эмитит сигнал (закупки видят срочность)."""
    deal = await _new_deal(api, "R5-C-1", amount=1000)
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": "2020-01-01"})
    assert r.status_code == 200
    assert r.json()["ship_deadline"] == "2020-01-01"
    evs = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(evs) == 1
    assert evs[0].payload["ship_deadline"] == "2020-01-01"
    assert evs[0].payload["deal_id"] == deal["id"]


async def test_null_deadline_on_create_no_emit(api, session):
    """POST без ship_deadline → 201, без эмита (создание без срока — норма)."""
    r = await api.post("/sales/deals", json={
        "number": "R5-D-1", "title": "t", "counterparty": "c"})
    assert r.status_code == 201
    assert r.json()["ship_deadline"] is None
    evs = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(evs) == 0


async def test_explicit_null_patch_no_emit(api, session):
    """PATCH ship_deadline=null → нет эмита, не 500."""
    deal = await _new_deal(api, "R5-E-1")
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": None})
    assert r.status_code == 200
    evs = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.ship_deadline.set"))).scalars().all()
    assert len(evs) == 0


# ══ R5-3: мульти-воронки — нельзя двинуть сделку в стадию ЧУЖОЙ воронки (фикс) ══

async def test_cross_funnel_stage_rejected(api):
    """PATCH стадией чужой воронки → 422; сделка не выпадает с досок."""
    stages = (await api.get("/sales/stages")).json()  # материализовать канон
    nc_codes = {s["code"] for s in stages if s["funnel"] == "new_clients"}
    rc_codes = {s["code"] for s in stages if s["funnel"] == "repeat_clients"}
    assert "new" in nc_codes and "rp_won" in rc_codes
    assert "rp_won" not in nc_codes

    deal = (await api.post("/sales/deals", json={
        "number": "R5-3-001", "title": "Тест", "counterparty": "ООО Тест"})).json()
    assert deal["funnel"] == "new_clients"

    patch = await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "rp_won"})
    assert patch.status_code in (422, 409), (
        f"чужая стадия должна отбиваться, получили {patch.status_code}: {patch.text}")

    got = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert got["stage"] != "rp_won" and got["funnel"] == "new_clients"


async def test_same_funnel_stage_still_allowed(api):
    """Контроль: стадия СВОЕЙ воронки по-прежнему проходит (фикс не зарубил легитимный путь)."""
    await api.get("/sales/stages")
    deal = await _new_deal(api, "R5-3-OK", stage="new")
    r = await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    assert r.status_code == 200 and r.json()["stage"] == "qual"


# ══ R5-4: margin_blind — фасад есть, но landed None по всем sku → честный null, не 0/500 ══

async def test_margin_blind_facade_present_sku_no_cost(api, session):
    """priced_count=0 при живом фасаде → cogs/gross = None (не 0), reason есть."""
    from modules.sales.models import DealItem, PriceQuote

    sku2 = await _seed_sku(session, "SKU2", "Товар без landed")  # _FakeLanded → None
    deal = await _new_deal(api, "MB-1", counterparty="ООО Слепой")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku2.id, qty=3),
        PriceQuote(sku_code="SKU2", counterparty="ООО Слепой", price=20),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.landed_cost = None

    assert r["priced_count"] == 0 and r["total_count"] == 1
    assert r["lines"][0]["status"] == "no_cost"
    assert r["cogs_landed"] is None, "0 ≠ «неизвестно» — должно быть None"
    assert r["gross_profit"] is None, "0 ≠ «неизвестно» — должно быть None"
    assert r["margin_pct"] is None and r["reason"] is not None


async def test_pipeline_forecast_blind_facade_honest(api, session):
    """Прогноз при слепом фасаде: не 500; выручка считается; gross_weighted = None (не 0)."""
    from modules.sales.models import DealItem, PriceQuote

    sku2 = await _seed_sku(session, "SKU2C", "Blind SKU")
    a = await _new_deal(api, "MBF-1", counterparty="ООО F", probability=50)
    session.add_all([
        DealItem(deal_id=a["id"], sku_id=sku2.id, qty=2),
        PriceQuote(sku_code="SKU2C", counterparty="ООО F", price=30),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = await api.get("/sales/pipeline/margin-forecast?funnel=new_clients")
    finally:
        app.state.core.services.landed_cost = None

    assert r.status_code == 200
    body = r.json()
    assert body["deals_priced"] == 0
    assert body["revenue_weighted"] == 30.0  # 30*2*0.50 — выручка не зависит от landed
    assert body["gross_weighted"] is None     # честный null, не 0
    assert body["margin_pct_blended"] is None and body["reason"] is not None


# ══ R5-5: идемпотентность handoff — дедуп по deal_id, не глобальный (guard) ══

async def test_two_different_deals_get_two_handoffs(api, session):
    app = api._transport.app  # type: ignore[attr-defined]
    ctx = EventContext(session=session, services=app.state.core.services)
    deal_a = await _new_deal(api, "HF-IA-1", counterparty="ООО Альфа")
    deal_b = await _new_deal(api, "HF-IA-2", counterparty="ООО Бета")
    await on_deal_won_handoff({"deal_id": deal_a["id"], "number": deal_a["number"]}, ctx)
    await on_deal_won_handoff({"deal_id": deal_b["id"], "number": deal_b["number"]}, ctx)
    await session.commit()
    events = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.handoff"))).scalars().all()
    ha = [e for e in events if e.payload.get("deal_id") == deal_a["id"]]
    hb = [e for e in events if e.payload.get("deal_id") == deal_b["id"]]
    assert len(ha) == 1 and len(hb) == 1
    assert ha[0].payload["counterparty"] == "ООО Альфа"
    assert hb[0].payload["counterparty"] == "ООО Бета"


async def test_triple_call_same_deal_yields_one_handoff(api, session):
    app = api._transport.app  # type: ignore[attr-defined]
    ctx = EventContext(session=session, services=app.state.core.services)
    deal = await _new_deal(api, "HF-IB-1", counterparty="ООО Гамма")
    payload = {"deal_id": deal["id"], "number": deal["number"]}
    for _ in range(3):
        await on_deal_won_handoff(payload, ctx)
        await session.commit()
    events = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.handoff"))).scalars().all()
    handoffs = [e for e in events if e.payload.get("deal_id") == deal["id"]]
    assert len(handoffs) == 1


async def test_payload_without_deal_id_no_handoff(api, session):
    app = api._transport.app  # type: ignore[attr-defined]
    ctx = EventContext(session=session, services=app.state.core.services)
    await on_deal_won_handoff({}, ctx)
    await session.commit()
    await on_deal_won_handoff({"deal_id": None, "number": "X"}, ctx)
    await session.commit()
    events = (await session.execute(select(OutboxEvent).where(
        OutboxEvent.event_type == "sales.deal.handoff"))).scalars().all()
    assert len(events) == 0
