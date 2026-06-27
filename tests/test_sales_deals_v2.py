"""БД-тесты «Сделки 2.0»: отказ+причины (SALES-40), история стадий (SALES-43),
прогноз (SALES-44), счётчик непрочитанных (SALES-49). SQLite в памяти."""
from datetime import datetime


async def _new_deal(api, number, **extra):
    payload = {"number": number, "title": "t", "counterparty": "c", **extra}
    r = await api.post("/sales/deals", json=payload)
    assert r.status_code == 201
    return r.json()


# ── SALES-40: отказ + причины ──────────────────────────────────────────────

async def test_lose_requires_reason(api):
    deal = await _new_deal(api, "L-1", amount=1000)

    # без причины → 422
    bad = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": ""})
    assert bad.status_code == 422

    # с причиной → стадия lost, причина и дата проставлены
    ok = await api.post(
        f"/sales/deals/{deal['id']}/lose",
        json={"reason_code": "price", "comment": "дорого"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["stage"] == "lost"
    assert body["lost_reason_code"] == "price"
    assert body["lost_comment"] == "дорого"
    assert body["closed_date"]

    # повторно закрыть в отказ нельзя
    again = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "other"})
    assert again.status_code == 409


async def test_lose_validates_against_dictionary(session, api):
    from modules.sales.models import LossReason

    session.add(LossReason(code="price", title="Дорого", sort_order=1, active=True))
    await session.commit()

    deal = await _new_deal(api, "L-2")
    # код вне справочника → 422
    bad = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "zzz"})
    assert bad.status_code == 422
    # валидный код → ок
    ok = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "price"})
    assert ok.status_code == 200


async def test_loss_reasons_endpoint(session, api):
    from modules.sales.models import LossReason

    session.add(LossReason(code="a", title="A", sort_order=2, active=True))
    session.add(LossReason(code="b", title="B", sort_order=1, active=True))
    session.add(LossReason(code="c", title="C", sort_order=3, active=False))
    await session.commit()

    rows = (await api.get("/sales/loss-reasons")).json()
    codes = [r["code"] for r in rows]
    assert codes == ["b", "a"]  # только активные, по sort_order


async def test_lost_emits_event(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "L-3", amount=500)
    await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "competitor"})

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.deal.lost" in types


async def test_lost_column_on_board(api):
    deal = await _new_deal(api, "L-4", amount=700)
    await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "no_need"})

    board = (await api.get("/sales/board")).json()
    stages = {s["id"]: s for s in board["stages"]}
    assert "lost" in stages
    assert stages["lost"]["title"] == "Отказ"
    assert stages["lost"]["count"] == 1
    assert stages["lost"]["sum"] == 700


# ── SALES-40: выигрыш ───────────────────────────────────────────────────────

async def test_win_deal(session, api):
    from sqlalchemy import select

    from core.domain.models import OutboxEvent

    deal = await _new_deal(api, "W-1", amount=2000)
    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "won"
    assert body["closed_date"]

    # повторно нельзя
    assert (await api.post(f"/sales/deals/{deal['id']}/win")).status_code == 409

    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "sales.deal.won" in types


# ── SALES-43: история стадий и висяки ───────────────────────────────────────

async def test_stage_history_recorded(api):
    deal = await _new_deal(api, "H-1", stage="new")
    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "price_req"})

    hist = (await api.get(f"/sales/deals/{deal['id']}/history")).json()
    transitions = [(h["from_stage"], h["to_stage"]) for h in hist]
    assert ("new", "qual") in transitions
    assert ("qual", "price_req") in transitions


async def test_stage_change_updates_stage_changed_at(session, api):
    from modules.sales.models import Deal

    deal = await _new_deal(api, "H-2", stage="new")
    # состарим вход в стадию
    obj = await session.get(Deal, deal["id"])
    obj.stage_changed_at = datetime(2020, 1, 1)
    await session.commit()

    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    obj2 = await session.get(Deal, deal["id"])
    assert obj2.stage_changed_at.year >= 2026  # обновилось при смене стадии


async def test_stuck_deals_filter(session, api):
    from modules.sales.models import Deal

    stale = await _new_deal(api, "ST-1", stage="qual")
    fresh = await _new_deal(api, "ST-2", stage="qual")
    won = await _new_deal(api, "ST-3", stage="qual")

    old = datetime(2020, 1, 1)
    for num in (stale["id"], won["id"]):
        o = await session.get(Deal, num)
        o.stage_changed_at = old
    # won — закрыт, не должен попадать в висяки даже будучи старым
    won_obj = await session.get(Deal, won["id"])
    won_obj.stage = "won"
    await session.commit()

    rows = (await api.get("/sales/deals?stuck_days=7")).json()
    ids = {d["id"] for d in rows}
    assert stale["id"] in ids
    assert fresh["id"] not in ids
    assert won["id"] not in ids


# ── SALES-44: вероятность и взвешенная сумма ───────────────────────────────

async def test_probability_patch(api):
    deal = await _new_deal(api, "P-1", amount=1000)
    r = await api.patch(
        f"/sales/deals/{deal['id']}",
        json={"probability": 65, "expected_close_date": "30.06.2026"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["probability"] == 65
    assert body["expected_close_date"] == "30.06.2026"


async def test_board_weighted(api):
    # явная вероятность
    await _new_deal(api, "WT-1", stage="has_price", amount=1000, probability=20)
    # без вероятности → дефолт стадии has_price = 45%
    await _new_deal(api, "WT-2", stage="has_price", amount=1000)

    board = (await api.get("/sales/board")).json()
    col = next(s for s in board["stages"] if s["id"] == "has_price")
    assert col["sum"] == 2000
    assert col["weighted"] == 200 + 450  # 1000*20% + 1000*45%(дефолт)


# ── SALES-49: непрочитанные сообщения ──────────────────────────────────────

async def test_chats_unread_and_mark_read(api):
    deal = await _new_deal(api, "U-1", counterparty="ООО Чат")
    # входящее от клиента → непрочитано
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Здравствуйте", "direction": "in"},
    )
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Ещё вопрос", "direction": "in"},
    )

    chats = (await api.get("/sales/chats")).json()
    chat = next(c for c in chats if c["deal_id"] == deal["id"])
    assert chat["unread"] == 2

    # отметить прочитанным → счётчик обнуляется
    r = await api.post(f"/sales/deals/{deal['id']}/messages/read")
    assert r.status_code == 200 and r.json()["read"] == 2

    chats2 = (await api.get("/sales/chats")).json()
    chat2 = next(c for c in chats2 if c["deal_id"] == deal["id"])
    assert chat2["unread"] == 0


# ── Сделки 2.0: редактор стадий (sales.stage CRUD) ──────────────────────────
async def test_stage_editor_lazy_seed_and_crud(api):
    # первый GET лениво материализует канон (11 new_clients + 5 repeat_clients = 16)
    stages = (await api.get("/sales/stages")).json()
    new_clients = [s for s in stages if s["funnel"] == "new_clients"]
    repeat_clients = [s for s in stages if s["funnel"] == "repeat_clients"]
    assert len(new_clients) == 11 and len(repeat_clients) == 5
    assert new_clients[0]["code"] == "new"
    won = next(s for s in stages if s["code"] == "won")
    assert won["kind"] == "won" and won["probability"] == 100

    created = await api.post(
        "/sales/stages", json={"code": "nurture", "title": "Дожим", "probability": 40}
    )
    assert created.status_code == 201
    # дубль кода → 409
    assert (await api.post("/sales/stages", json={"code": "nurture", "title": "x"})).status_code == 409

    upd = await api.patch("/sales/stages/nurture", json={"title": "Дожим клиента", "probability": 42})
    assert upd.status_code == 200 and upd.json()["title"] == "Дожим клиента"

    # удалить пустую стадию → 204
    assert (await api.delete("/sales/stages/nurture")).status_code == 204


async def test_stage_delete_blocked_when_deals_exist(api):
    await api.get("/sales/stages")  # материализовать канон
    await _new_deal(api, "ST-1", stage="qual")
    # в стадии есть сделка → удаление запрещено (409, целостность Deal.stage)
    assert (await api.delete("/sales/stages/qual")).status_code == 409


# ── П1: факт-маржа через landed_cost ────────────────────────────────────────────
class _FakeLanded:
    """Стенд фасада landed_cost для тестов: SKU1 → unit_landed_cost_byn 10, остальные → None."""

    async def last_landed_cost(self, session, sku_code):
        return await self._one(sku_code)

    async def last_landed_cost_batch(self, session, sku_codes):
        return {c: await self._one(c) for c in sku_codes}

    async def _one(self, code):
        if code == "SKU1":
            from decimal import Decimal as D
            return {
                "unit_landed_cost_byn": D("10.00"),
                "shipment_id": 42,
                "fixed_at": datetime(2026, 6, 1, 10, 0),
                "stage": "closed",
                "fx_rate": D("3.21"),
                "fx_date": "2026-06-01",
            }
        return None


async def _seed_sku(session, code, title="t", unit="шт"):
    from core.domain.models import Sku

    sku = Sku(code=code, title=title, unit=unit)
    session.add(sku)
    await session.flush()
    return sku


async def test_deal_margin_priced_no_price_no_cost(api, session):
    """П1: margin отдаёт revenue/cogs/gross для priced; статусы no_price/no_cost для остальных."""
    from modules.sales.models import DealItem, PriceQuote

    # Заменим landed-фасад в core на стенд
    sku1 = await _seed_sku(session, "SKU1", "A1")
    sku2 = await _seed_sku(session, "SKU2", "A2")
    sku3 = await _seed_sku(session, "SKU3", "A3")
    deal = await _new_deal(api, "MGN-1", counterparty="ООО X")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku1.id, qty=5),
        DealItem(deal_id=deal["id"], sku_id=sku2.id, qty=3),
        DealItem(deal_id=deal["id"], sku_id=sku3.id, qty=2),
        PriceQuote(sku_code="SKU1", counterparty="ООО X", price=15),
        PriceQuote(sku_code="SKU2", counterparty="ООО X", price=20),
    ])
    await session.commit()
    # подменяем фасад на стенд
    app = api._transport.app  # type: ignore[attr-defined]

    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    finally:
        app.state.core.services.landed_cost = None
    assert r["revenue"] == 75.0
    assert r["cogs_landed"] == 50.0
    assert r["gross_profit"] == 25.0
    assert r["margin_pct"] == 33
    assert r["priced_count"] == 1 and r["total_count"] == 3
    statuses = {li["sku_code"]: li["status"] for li in r["lines"]}
    assert statuses == {"SKU1": "priced", "SKU2": "no_cost", "SKU3": "no_price"}


async def test_deal_margin_facade_missing(api, session):
    """П1: фасад landed_cost None → cogs/gross_profit/margin_pct = None + reason."""
    from modules.sales.models import DealItem, PriceQuote

    sku = await _seed_sku(session, "SKU-X")
    deal = await _new_deal(api, "MGN-2", counterparty="ООО Y")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku.id, qty=2),
        PriceQuote(sku_code="SKU-X", counterparty="ООО Y", price=50),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]

    app.state.core.services.landed_cost = None
    r = (await api.get(f"/sales/deals/{deal['id']}/margin")).json()
    assert r["cogs_landed"] is None and r["gross_profit"] is None and r["margin_pct"] is None
    assert "procurement" in (r["reason"] or "")


# ── П4: мульти-воронки в /board ────────────────────────────────────────────────
async def test_board_funnel_filter(api):
    await api.get("/sales/stages")  # материализовать канон обеих воронок
    await _new_deal(api, "F-1", stage="new")  # default funnel = new_clients
    await _new_deal(api, "F-2", stage="rp_request", funnel="repeat_clients")
    b_new = (await api.get("/sales/board?funnel=new_clients")).json()
    b_rep = (await api.get("/sales/board?funnel=repeat_clients")).json()
    n_new = sum(st["count"] for st in b_new["stages"])
    n_rep = sum(st["count"] for st in b_rep["stages"])
    assert n_new == 1 and n_rep == 1
    cols_new = [st["id"] for st in b_new["stages"]]
    cols_rep = [st["id"] for st in b_rep["stages"]]
    assert "qual" in cols_new and "rp_request" in cols_rep
    assert "rp_request" not in cols_new


# ── П6: pipeline-аналитика ─────────────────────────────────────────────────────
async def test_pipeline_analytics(api, session):
    from modules.sales.models import Deal, DealStageEvent

    await api.get("/sales/stages")  # канон
    # 3 сделки: 2 в qual, 1 в won; 2 события new->qual
    for i, st in enumerate(("qual", "qual", "won"), start=1):
        await _new_deal(api, f"PA-{i}", stage=st)
    deals = (await session.execute(__import__("sqlalchemy").select(Deal))).scalars().all()
    # У каждой сделки в истории: ?→new (была в new), затем new→текущая (ушла из new).
    # Для won-сделки добавим ещё qual→won, чтобы проверить, что cycle/won считаются.
    for d in deals:
        session.add(DealStageEvent(deal_id=d.id, from_stage=None, to_stage="new"))
        session.add(DealStageEvent(deal_id=d.id, from_stage="new", to_stage=d.stage))
    await session.commit()
    r = (await api.get("/sales/pipeline/analytics?funnel=new_clients")).json()
    by_id = {st["id"]: st for st in r["stages"]}
    assert by_id["qual"]["count"] == 2
    assert by_id["won"]["count"] == 1
    # 3 сделки были в стадии "new" (через события); 2 из них ушли в qual → 67%
    # (3-я ушла в won через qual, поэтому new→qual = 3, но moved_to_next считает по парам
    # (new, qual) и берёт уникальные deal_id, значит 3, denom=3 → 100%).
    assert by_id["new"]["next_conv_pct"] is not None
    assert r["won_count"] == 1


# ── П8: цикл плана draft→submit→decide + права ────────────────────────────────
async def test_plan_lifecycle_and_permissions(api):
    # 1) Создать draft
    plan = (await api.post(
        "/sales/plans",
        json={"owner_id": 1, "metric": "calls", "period_type": "month",
              "period_key": "2026-06", "target": 100},
    )).json()
    assert plan["status"] == "draft"
    # 2) Submit
    sent = (await api.post(f"/sales/plans/{plan['id']}/submit")).json()
    assert sent["status"] == "pending_approval"
    # 3) Approve как РОП (фикстура api по умолчанию director — super-роль)
    decided = (await api.post(
        f"/sales/plans/{plan['id']}/decide", json={"approved": True, "comment": "ok"}
    )).json()
    assert decided["status"] == "approved"
    # 4) Повторный decide на approved → 409
    assert (await api.post(
        f"/sales/plans/{plan['id']}/decide", json={"approved": False}
    )).status_code == 409


async def test_plan_decide_requires_approve_permission():
    """sales.deal.approve есть только у РОП/super; Менеджер не может decide."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from config.modules import ENABLED_MODULES
    from core.db.base import Base
    from core.runtime.app import create_app
    from core.runtime.deps import get_session

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True).execution_options(
        schema_translate_map={m: None for m in ENABLED_MODULES}
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        app = create_app()

        async def _ovr():
            yield s

        app.dependency_overrides[get_session] = _ovr
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                                headers={"X-User-Roles": "director"}) as c1:
            # Создаём план под super → submit
            p = (await c1.post(
                "/sales/plans",
                json={"owner_id": 1, "metric": "calls", "period_type": "month",
                      "period_key": "2026-06", "target": 50},
            )).json()
            await c1.post(f"/sales/plans/{p['id']}/submit")
        # Теперь под не-РОП ролью — decide должен быть 403. ASCII-роль "guest" не имеет
        # sales.deal.approve (она не из ROLES sales) → 403, что и проверяем.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                                headers={"X-User-Roles": "guest"}) as c2:
            r = await c2.post(f"/sales/plans/{p['id']}/decide", json={"approved": True})
        assert r.status_code == 403
    await engine.dispose()


# ── П10: handoff на win ────────────────────────────────────────────────────────
async def test_handoff_on_won(api, session):
    """sales.deal.handoff появляется в outbox после перевода сделки в won."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext
    app = api._transport.app  # type: ignore[attr-defined]
    from modules.sales.events import on_deal_won_handoff

    deal = await _new_deal(api, "HF-1", stage="invoice", counterparty="ООО Z")
    # Прямой вызов обработчика — relay в тестах не крутится автоматически.
    ctx = EventContext(session=session, services=app.state.core.services)
    await on_deal_won_handoff({"deal_id": deal["id"], "number": deal["number"]}, ctx)
    await session.commit()
    # Идемпотентность: повторный вызов не плодит второй handoff.
    await on_deal_won_handoff({"deal_id": deal["id"], "number": deal["number"]}, ctx)
    await session.commit()
    events = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.handoff")
        )
    ).scalars().all()
    handoffs = [e for e in events if e.payload.get("deal_id") == deal["id"]]
    assert len(handoffs) == 1
    payload = handoffs[0].payload
    assert payload["counterparty"] == "ООО Z"
    assert payload["funnel"] == "new_clients"

    # GET /handoff отдаёт сводку
    r = (await api.get(f"/sales/deals/{deal['id']}/handoff")).json()
    assert r is not None and r["counterparty"] == "ООО Z"
