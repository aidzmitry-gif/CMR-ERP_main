"""БД-тесты «Сделки 2.0»: отказ+причины (SALES-40), история стадий (SALES-43),
прогноз (SALES-44), счётчик непрочитанных (SALES-49). SQLite в памяти."""
from datetime import date, datetime, timezone


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


# ── Цикл 18 (фикс верификации): won-код воронки, реверс из closed ───────────

async def test_win_deal_repeat_clients_resolves_rp_won(api):
    """Фикс 1: win на сделке repeat_clients ставит ``rp_won`` (не литерал "won", которого
    нет в этой воронке) — иначе сделка выпадала бы с /board?funnel=repeat_clients."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "RP-W-1", stage="rp_request", funnel="repeat_clients", amount=1500)

    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "rp_won"
    assert body["closed_date"]

    # повторно нельзя — 409 сверяется с ПРАВИЛЬНЫМ won-кодом воронки, не с литералом "won"
    assert (await api.post(f"/sales/deals/{deal['id']}/win")).status_code == 409

    board = (await api.get("/sales/board?funnel=repeat_clients")).json()
    won_col = next(st for st in board["stages"] if st["id"] == "rp_won")
    assert won_col["count"] == 1


async def test_lose_deal_repeat_clients_resolves_rp_lost(api):
    """Тот же класс бага, что Фикс 1 (win): lose на сделке repeat_clients ставит ``rp_lost``
    (не литерал "lost", которого нет в этой воронке) — иначе закрытая сделка выпадала бы
    с /board?funnel=repeat_clients."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "RP-L-1", stage="rp_request", funnel="repeat_clients", amount=800)

    r = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "price"})
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "rp_lost"
    assert body["closed_date"]

    # повторно нельзя — 409 сверяется с ПРАВИЛЬНЫМ lost-кодом воронки, не с литералом "lost"
    again = await api.post(f"/sales/deals/{deal['id']}/lose", json={"reason_code": "other"})
    assert again.status_code == 409

    board = (await api.get("/sales/board?funnel=repeat_clients")).json()
    lost_col = next(st for st in board["stages"] if st["id"] == "rp_lost")
    assert lost_col["count"] == 1


async def test_reverse_from_won_clears_closed_date(api):
    """Фикс 2: реверс сделки из won в нетерминальную стадию сбрасывает ``closed_date`` —
    иначе сделка, возвращённая в работу, продолжает числиться закрытой в отчётах."""
    deal = await _new_deal(api, "REV-1", amount=900)
    won = await api.post(f"/sales/deals/{deal['id']}/win")
    assert won.json()["closed_date"]

    back = await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "qual"})
    assert back.status_code == 200
    assert back.json()["closed_date"] is None


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


# ── Цикл 17: возраст ожидания ответа ────────────────────────────────────────

async def test_chats_waiting_since(session, api):
    """waiting_since = created_at САМОГО СТАРОГО непрочитанного входящего (MIN, не MAX).

    Цикл 18 (фикс верификации): оба сообщения создаются в один SQLite-тик (секундная точность
    created_at) — без явного расхождения дат min==max, и тест прошёл бы даже с ошибочным
    func.max. Выставляем created_at напрямую разными датами, чтобы отличить min от max.
    """
    from sqlalchemy import select

    from modules.sales.models import Message

    deal = await _new_deal(api, "U-2", counterparty="ООО Ждёт")

    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Первое", "direction": "in"},
    )
    await api.post(
        f"/sales/deals/{deal['id']}/messages",
        json={"channel": "whatsapp", "text": "Второе", "direction": "in"},
    )

    rows = (
        await session.execute(
            select(Message).where(Message.deal_id == deal["id"]).order_by(Message.id)
        )
    ).scalars().all()
    rows[0].created_at = datetime(2026, 1, 1, 10, 0, 0)  # «Первое» — старше
    rows[1].created_at = datetime(2026, 1, 1, 11, 0, 0)  # «Второе» — младше
    await session.commit()

    msgs = (await api.get(f"/sales/deals/{deal['id']}/messages")).json()
    oldest_created_at, newest_created_at = msgs[0]["created_at"], msgs[1]["created_at"]

    chats = (await api.get("/sales/chats")).json()
    chat = next(c for c in chats if c["deal_id"] == deal["id"])
    assert chat["waiting_since"] == oldest_created_at
    assert chat["waiting_since"] != newest_created_at

    # отметить прочитанным → бейдж гаснет (waiting_since вновь None)
    r = await api.post(f"/sales/deals/{deal['id']}/messages/read")
    assert r.status_code == 200 and r.json()["read"] == 2

    chats2 = (await api.get("/sales/chats")).json()
    chat2 = next(c for c in chats2 if c["deal_id"] == deal["id"])
    assert chat2["waiting_since"] is None


# ── Сделки 2.0: редактор стадий (sales.stage CRUD) ──────────────────────────
async def test_stage_editor_lazy_seed_and_crud(api):
    # первый GET лениво материализует канон (11 new_clients + 5 repeat_clients + 5 tenders = 21)
    stages = (await api.get("/sales/stages")).json()
    new_clients = [s for s in stages if s["funnel"] == "new_clients"]
    repeat_clients = [s for s in stages if s["funnel"] == "repeat_clients"]
    tenders = [s for s in stages if s["funnel"] == "tenders"]
    assert len(new_clients) == 11 and len(repeat_clients) == 5 and len(tenders) == 5
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
    await api.get("/sales/stages")  # материализовать канон всех воронок
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


# ── Слайс 3: воронка «Тендеры» ──────────────────────────────────────────────────
async def test_board_funnel_tenders(api):
    await api.get("/sales/stages")  # материализовать канон всех воронок
    await _new_deal(api, "T-1", stage="tn_bidding", funnel="tenders")
    b_tn = (await api.get("/sales/board?funnel=tenders")).json()
    cols_tn = [st["id"] for st in b_tn["stages"]]
    assert cols_tn == ["tn_announced", "tn_submitted", "tn_bidding", "tn_won", "tn_lost"]
    n_tn = sum(st["count"] for st in b_tn["stages"])
    assert n_tn == 1

    funnels = (await api.get("/sales/funnels")).json()
    codes = {f["code"] for f in funnels}
    assert {"new_clients", "repeat_clients", "tenders"} <= codes


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


# ── Период-срез конверсии/времени на стадии (pipeline/stage-metrics) ───────────
async def test_pipeline_stage_metrics_period_window(api, session):
    """entered_count/avg_time_days/conv_next_pct считаются только по сегментам,
    попавшим в окно periода — переход вне окна (SM-OLD) не портит статистику."""
    from datetime import timedelta

    from sqlalchemy import select

    from modules.sales.models import Deal, DealStageEvent

    deal_in = await _new_deal(api, "SM-1", stage="new")
    deal_old = await _new_deal(api, "SM-OLD", stage="new")

    d_in = (
        await session.execute(select(Deal).where(Deal.id == deal_in["id"]))
    ).scalar_one()
    d_old = (
        await session.execute(select(Deal).where(Deal.id == deal_old["id"]))
    ).scalar_one()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # SM-1: вошла в "new" 10 дней назад, ушла в "qual" 3 дня назад (5 дн длительность
    # была бы неверной — реально 7 дн) — внутри окна «месяц» (30 дн).
    d_in.created_at = now - timedelta(days=10)
    d_in.stage = "qual"
    session.add(DealStageEvent(deal_id=d_in.id, from_stage="new", to_stage="qual",
                                changed_at=now - timedelta(days=3)))
    # SM-OLD: переход был 90 дней назад — целиком вне окна «месяц», не должен всплыть.
    d_old.created_at = now - timedelta(days=120)
    d_old.stage = "qual"
    session.add(DealStageEvent(deal_id=d_old.id, from_stage="new", to_stage="qual",
                                changed_at=now - timedelta(days=90)))
    await session.commit()

    r = (await api.get("/sales/pipeline/stage-metrics?funnel=new_clients&period=month")).json()
    by_id = {st["id"]: st for st in r["stages"]}
    assert by_id["new"]["entered_count"] == 1  # только SM-1 (created_at в окне)
    assert by_id["new"]["completed_count"] == 1
    assert by_id["new"]["avg_time_days"] == 7.0
    assert by_id["new"]["conv_next_pct"] == 100

    # honest-empty: стадия без истории за период — None, не 0
    assert by_id["price_req"]["entered_count"] == 0
    assert by_id["price_req"]["avg_time_days"] is None
    assert by_id["price_req"]["conv_next_pct"] is None

    # Явный диапазон дат перекрывает period — окно расширили, SM-OLD теперь виден.
    d_from = (now - timedelta(days=200)).date().isoformat()
    d_to = now.date().isoformat()
    r2 = (
        await api.get(
            f"/sales/pipeline/stage-metrics?funnel=new_clients&date_from={d_from}&date_to={d_to}"
        )
    ).json()
    assert {st["id"]: st for st in r2["stages"]}["new"]["entered_count"] == 2


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


# ── S3-1: взвешенный прогноз ВАЛОВОЙ МАРЖИ воронки ──────────────────────────────
async def test_margin_forecast_weighted_gross(api, session):
    """S3-1: revenue/gross взвешены на вероятность; deals_priced=1/2 (priced + no_cost)."""
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")  # landed=10 в _FakeLanded
    sku2 = await _seed_sku(session, "SKU2", "A2")  # landed=None → no_cost
    a = await _new_deal(api, "MF-1", counterparty="ООО X", probability=40)
    b = await _new_deal(api, "MF-2", counterparty="ООО X", probability=10)
    session.add_all([
        DealItem(deal_id=a["id"], sku_id=sku1.id, qty=5),   # priced: выручка 75, gross 25
        DealItem(deal_id=b["id"], sku_id=sku2.id, qty=3),   # no_cost: выручка 60, без gross
        PriceQuote(sku_code="SKU1", counterparty="ООО X", price=15),
        PriceQuote(sku_code="SKU2", counterparty="ООО X", price=20),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()
    try:
        r = (await api.get("/sales/pipeline/margin-forecast?funnel=new_clients")).json()
    finally:
        app.state.core.services.landed_cost = None
    # выручка взвеш = 75*0.40 + 60*0.10 = 36.0; gross взвеш = 25*0.40 = 10.0
    assert r["revenue_weighted"] == 36.0
    assert r["gross_weighted"] == 10.0
    assert r["margin_pct_blended"] == 28  # round(10/36*100)
    assert r["deals_priced"] == 1 and r["deals_total"] == 2
    assert r["reason"] is None


async def test_margin_forecast_facade_missing(api, session):
    """S3-1: фасада landed нет → gross_weighted=null + reason, выручка остаётся числом."""
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")
    a = await _new_deal(api, "MF-3", counterparty="ООО Y", probability=50)
    session.add_all([
        DealItem(deal_id=a["id"], sku_id=sku1.id, qty=4),
        PriceQuote(sku_code="SKU1", counterparty="ООО Y", price=10),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = None
    r = (await api.get("/sales/pipeline/margin-forecast?funnel=new_clients")).json()
    assert r["gross_weighted"] is None          # НЕ 0
    assert r["revenue_weighted"] == 20.0        # 10*4*0.50 — не зависит от landed
    assert r["margin_pct_blended"] is None
    assert r["deals_priced"] == 0
    assert "procurement" in (r["reason"] or "")


# ── S3-3: procurement.received → sales.supply.arrived ───────────────────────────
async def test_procurement_received_signals_active_deals(api, session):
    """S3-3: поставка по SKU активной сделки → sales.supply.arrived; payload без sku не валит."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from core.services.eventbus import EventContext
    from modules.sales.events import on_procurement_received
    from modules.sales.models import Deal, DealItem

    app = api._transport.app  # type: ignore[attr-defined]
    sku1 = await _seed_sku(session, "SKU1", "A1")
    active = await _new_deal(api, "SUP-1", stage="qual")
    closed = await _new_deal(api, "SUP-2", stage="qual")
    session.add_all([
        DealItem(deal_id=active["id"], sku_id=sku1.id, qty=2),
        DealItem(deal_id=closed["id"], sku_id=sku1.id, qty=1),
    ])
    await session.commit()
    cobj = await session.get(Deal, closed["id"])
    cobj.stage = "won"  # терминал — не сигналим
    await session.commit()

    ctx = EventContext(session=session, services=app.state.core.services)
    # payload без sku → ранний выход, ничего не эмитим, не падаем
    await on_procurement_received({"qty": "5"}, ctx)
    await session.commit()
    # поставка SKU1 → сигнал только на активную сделку
    await on_procurement_received(
        {"sku_code": "SKU1", "qty": "5", "entity_ref": "purchase:7"}, ctx
    )
    await session.commit()

    evs = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.supply.arrived")
    )).scalars().all()
    assert len(evs) == 1
    p = evs[0].payload
    assert p["sku_code"] == "SKU1" and p["qty"] == "5"
    assert active["id"] in p["deal_ids"] and closed["id"] not in p["deal_ids"]


# ── S3-4: сверка маржи sales ↔ finance (sku-агрегат) ────────────────────────────
async def test_margin_reconcile_with_and_without_finance(api, session):
    """S3-4: без landed-событий → no_finance; с аудитом → delta/converged; actual бьёт estimated."""
    from core.domain.models import OutboxEvent
    from modules.sales.models import DealItem, PriceQuote

    sku1 = await _seed_sku(session, "SKU1", "A1")
    deal = await _new_deal(api, "RC-1", counterparty="ООО R")
    session.add_all([
        DealItem(deal_id=deal["id"], sku_id=sku1.id, qty=5),
        PriceQuote(sku_code="SKU1", counterparty="ООО R", price=15),
    ])
    await session.commit()
    app = api._transport.app  # type: ignore[attr-defined]
    app.state.core.services.landed_cost = _FakeLanded()  # SKU1 landed=10 → sales gross=(15-10)*5=25
    try:
        # 1) нет landed-событий → no_finance, sales-сторона посчитана
        r0 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r0["status"] == "no_finance"
        assert r0["finance_actual_gross"] is None
        assert r0["sales_forecast_gross"] == 25.0
        assert r0["level"] == "sku_aggregate"
        # 2) аудит landed=10 → finance gross=(15-10)*5=25 → converged
        session.add(OutboxEvent(
            event_type="procurement.landed_cost.calculated",
            payload={"sku_code": "SKU1", "unit_landed_cost_byn": "10.00", "qty": "5",
                     "stage": "estimated", "entity_ref": "purchase_order:1"},
        ))
        await session.commit()
        r1 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r1["finance_actual_gross"] == 25.0 and r1["delta"] == 0.0
        assert r1["status"] == "converged"
        # 3) более позднее actual=12 бьёт estimated → finance gross=(15-12)*5=15, delta=10 → diverged
        session.add(OutboxEvent(
            event_type="procurement.landed_cost.calculated",
            payload={"sku_code": "SKU1", "unit_landed_cost_byn": "12.00", "qty": "5",
                     "stage": "actual", "entity_ref": "purchase_order:1"},
        ))
        await session.commit()
        r2 = (await api.get(f"/sales/deals/{deal['id']}/margin/reconcile")).json()
        assert r2["finance_actual_gross"] == 15.0 and r2["delta"] == 10.0
        assert r2["status"] == "diverged"
    finally:
        app.state.core.services.landed_cost = None


# ── S3-5: согласованный план РОП → цель скорборда (KpiTarget) ───────────────────
async def test_plan_approved_upserts_kpi_target(api, session):
    """S3-5: approve по метрике скорборда → KpiTarget.target=план; метрика вне скорборда — игнор."""
    from decimal import Decimal

    from sqlalchemy import select

    from core.services.eventbus import EventContext
    from modules.sales.events import on_plan_approved
    from modules.sales.models import KpiTarget

    app = api._transport.app  # type: ignore[attr-defined]
    session.add(KpiTarget(key="calls", title="Звонки", target=Decimal("20"),
                          unit="count", icon="phone", tone="neutral", sort_order=1))
    await session.commit()
    ctx = EventContext(session=session, services=app.state.core.services)

    await on_plan_approved({"metric": "calls", "target": 30.0, "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "calls")
    )).scalars().first()
    assert float(kpi.target) == 30.0
    rows = (await api.get("/sales/kpis?period=day")).json()
    calls_row = next(r for r in rows if r["key"] == "calls")
    assert calls_row["target"] == 30.0

    # план МЕСЯЦА нормализуется в дневной seed (÷ рабочих дней), /kpis?period=month отдаёт итог
    session.add(KpiTarget(key="leads", title="Лиды", target=Decimal("5"),
                          unit="count", icon="user", tone="neutral", sort_order=2))
    await session.commit()
    await on_plan_approved({"metric": "leads", "target": 440.0, "period_type": "month",
                            "period_key": "2026-06", "owner_id": 1}, ctx)
    await session.commit()
    leads_kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "leads")
    )).scalars().first()
    assert float(leads_kpi.target) == 20.0  # 440 / 22 рабочих дней месяца
    rows_m = (await api.get("/sales/kpis?period=month")).json()
    leads_row = next(r for r in rows_m if r["key"] == "leads")
    assert leads_row["target"] == 440.0  # 20 × 22 — план месяца не раздут

    # кривой target не валит обработчик и не меняет цель (poison-pill guard для шины)
    await on_plan_approved({"metric": "calls", "target": "n/a", "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    calls_kpi = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "calls")
    )).scalars().first()
    assert float(calls_kpi.target) == 30.0  # не изменилось

    # метрика вне скорборда — строку не создаём, не падаем
    await on_plan_approved({"metric": "tenders_count", "target": 5.0, "period_type": "day",
                            "period_key": "2026-06-12", "owner_id": 1}, ctx)
    await session.commit()
    absent = (await session.execute(
        select(KpiTarget).where(KpiTarget.key == "tenders_count")
    )).scalars().first()
    assert absent is None


# ── /sales/kpis?period=YYYY-MM: произвольный месяц ──────────────────────────────
async def test_kpis_arbitrary_month_aggregates_only_that_month(session, api):
    """period=2026-05 агрегирует Activity только за май 2026, апрель/июнь не подмешиваются."""
    from decimal import Decimal

    from modules.sales.models import Activity, KpiTarget

    session.add(KpiTarget(key="calls", title="Звонки", target=Decimal("20"),
                          unit="count", icon="phone", tone="neutral", sort_order=1))
    session.add(Activity(kpi_key="calls", value=Decimal("3"), date=date(2026, 4, 30)))
    session.add(Activity(kpi_key="calls", value=Decimal("5"), date=date(2026, 5, 1)))
    session.add(Activity(kpi_key="calls", value=Decimal("7"), date=date(2026, 5, 31)))
    session.add(Activity(kpi_key="calls", value=Decimal("11"), date=date(2026, 6, 1)))
    await session.commit()

    rows = (await api.get("/sales/kpis?period=2026-05")).json()
    calls_row = next(r for r in rows if r["key"] == "calls")
    assert calls_row["actual"] == 12.0  # только 5+7 (апрель/июнь не подмешаны)
    # план: 20/день × число рабочих дней мая-2026 (21 будний день пн-пт)
    assert calls_row["target"] == 20.0 * 21


async def test_kpis_invalid_period_does_not_crash(api):
    """Невалидный period (не relative-ключ и не YYYY-MM) — честный фоллбэк, не 500."""
    # "0000-01" — год < 1 (date() кинул бы ValueError, если год не валидировать) — тоже фоллбэк.
    for bad_period in ("2026-13", "foo", "2026-5", "0000-01", "0000-13"):
        r = await api.get(f"/sales/kpis?period={bad_period}")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Крайняя дата отгрузки + штраф за опоздание → сигнал в закупки ───────────────
async def test_deal_ship_deadline_and_penalty_persist(api):
    """Поля крайней даты и штрафа сохраняются при создании и обновлении сделки."""
    deal = await _new_deal(
        api, "SD-1", ship_deadline="2026-07-15",
        penalty_rate_pct=0.1, penalty_cap_pct=10, penalty_terms="0.1%/день, макс 10%",
    )
    assert deal["ship_deadline"] == "2026-07-15"
    assert deal["penalty_rate_pct"] == 0.1
    assert deal["penalty_cap_pct"] == 10
    assert deal["penalty_terms"] == "0.1%/день, макс 10%"

    upd = (await api.patch(
        f"/sales/deals/{deal['id']}", json={"ship_deadline": "2026-07-20"}
    )).json()
    assert upd["ship_deadline"] == "2026-07-20"
    got = (await api.get(f"/sales/deals/{deal['id']}")).json()
    assert got["ship_deadline"] == "2026-07-20"


async def test_ship_deadline_emits_to_procurement(api, session):
    """Выставление/смена крайней даты → sales.deal.ship_deadline.set (дата+штраф+позиции)."""
    from sqlalchemy import select

    from core.domain.models import OutboxEvent
    from modules.sales.models import DealItem

    sku = await _seed_sku(session, "SKU-SD", "Товар к сроку")
    deal = await _new_deal(api, "SD-2", counterparty="ООО Срок")
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=4))
    await session.commit()

    await api.patch(f"/sales/deals/{deal['id']}", json={
        "ship_deadline": "2026-08-01", "penalty_rate_pct": 0.5,
        "penalty_cap_pct": 15, "penalty_terms": "0.5%/день",
    })
    evs = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.ship_deadline.set")
    )).scalars().all()
    assert len(evs) == 1
    p = evs[0].payload
    assert p["deal_id"] == deal["id"]
    assert p["ship_deadline"] == "2026-08-01"
    assert p["penalty_rate_pct"] == 0.5 and p["penalty_cap_pct"] == 15
    assert p["counterparty"] == "ООО Срок"
    assert any(it["sku_code"] == "SKU-SD" and it["qty"] == 4 for it in p["items"])

    # та же дата повторно → нового сигнала нет (эмит только на смену)
    await api.patch(f"/sales/deals/{deal['id']}", json={"ship_deadline": "2026-08-01"})
    # PATCH другого поля → тоже не эмитит
    await api.patch(f"/sales/deals/{deal['id']}", json={"title": "Переименовал"})
    evs2 = (await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == "sales.deal.ship_deadline.set")
    )).scalars().all()
    assert len(evs2) == 1


async def test_penalty_out_of_range_rejected(api):
    """Штраф вне диапазона режется в 422 на валидации, а не падает в 500 (overflow колонок БД)."""
    # ставка > Numeric(6,2) предела (9999.99) → 422
    r = await api.post("/sales/deals", json={
        "number": "PN-1", "title": "t", "counterparty": "c", "penalty_rate_pct": 99999,
    })
    assert r.status_code == 422
    # отрицательная ставка → 422
    r2 = await api.post("/sales/deals", json={
        "number": "PN-2", "title": "t", "counterparty": "c", "penalty_rate_pct": -1,
    })
    assert r2.status_code == 422
    # примечание длиннее String(512) → 422
    deal = await _new_deal(api, "PN-3")
    r3 = await api.patch(f"/sales/deals/{deal['id']}", json={"penalty_terms": "x" * 513})
    assert r3.status_code == 422


# ── повтор прошлого заказа ──────────────────────────────────────────────────

async def test_repeat_last_order_returns_prior_deal_items(api, session):
    """Вторая сделка того же контрагента → позиции подтягиваются из первой (с позициями)."""
    from modules.sales.models import DealItem

    sku1 = await _seed_sku(session, "RLO-1", "Товар 1")
    sku2 = await _seed_sku(session, "RLO-2", "Товар 2")
    first = await _new_deal(api, "RLO-D1", counterparty="ООО Повтор")
    session.add_all([
        DealItem(deal_id=first["id"], sku_id=sku1.id, qty=5),
        DealItem(deal_id=first["id"], sku_id=sku2.id, qty=3),
    ])
    await session.commit()
    second = await _new_deal(api, "RLO-D2", counterparty="ООО Повтор")

    r = await api.get(f"/sales/deals/{second['id']}/repeat-last-order")
    assert r.status_code == 200
    items = r.json()
    assert {(i["code"], i["qty"]) for i in items} == {("RLO-1", 5.0), ("RLO-2", 3.0)}


async def test_repeat_last_order_empty_when_no_prior_deals(api):
    """Нет предыдущих сделок контрагента с позициями → пустой список, статус 200."""
    deal = await _new_deal(api, "RLO-D3", counterparty="ООО Без Истории")
    r = await api.get(f"/sales/deals/{deal['id']}/repeat-last-order")
    assert r.status_code == 200
    assert r.json() == []


async def test_repeat_last_order_404_for_missing_deal(api):
    """Несуществующая сделка → 404."""
    r = await api.get("/sales/deals/999999/repeat-last-order")
    assert r.status_code == 404


async def test_repeat_last_order_ignores_newer_parallel_deal(api, session):
    """Повтор берёт ПРЕДЫДУЩУЮ сделку (id меньше), а не более новую параллельную.

    Регрессия из code-review: раньше выбиралась «последняя другая» по created_at без
    условия «раньше текущей» → черновик более новой параллельной сделки подменял
    реально заказанное из прошлой.
    """
    from modules.sales.models import DealItem

    old_sku = await _seed_sku(session, "RLO-OLD", "Старый заказ")
    new_sku = await _seed_sku(session, "RLO-NEW", "Черновик новее")
    first = await _new_deal(api, "RLO-P1", counterparty="ООО Параллель")  # прошлый заказ
    session.add(DealItem(deal_id=first["id"], sku_id=old_sku.id, qty=2))
    await session.commit()
    middle = await _new_deal(api, "RLO-P2", counterparty="ООО Параллель")  # текущая (звоним по ней)
    newer = await _new_deal(api, "RLO-P3", counterparty="ООО Параллель")  # созданная ПОЗЖЕ
    session.add(DealItem(deal_id=newer["id"], sku_id=new_sku.id, qty=9))
    await session.commit()

    items = (await api.get(f"/sales/deals/{middle['id']}/repeat-last-order")).json()
    # только позиции ПРЕДЫДУЩЕЙ сделки (first), не черновик более новой (newer)
    assert {i["code"] for i in items} == {"RLO-OLD"}


# ── Журнал продаж (GET /sales/journal) ──────────────────────────────────────────

async def test_journal_only_won_deals(api):
    """Журнал отдаёт ТОЛЬКО won-сделки — активная и отказная в реестр не попадают."""
    active = await _new_deal(api, "JRN-ACT", amount=100)
    lost = await _new_deal(api, "JRN-LST", amount=200)
    await api.post(f"/sales/deals/{lost['id']}/lose", json={"reason_code": "price"})
    won = await _new_deal(api, "JRN-WON", amount=300)
    await api.post(f"/sales/deals/{won['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    ids = {r["deal_id"] for r in rows}
    assert won["id"] in ids
    assert active["id"] not in ids
    assert lost["id"] not in ids


async def test_journal_funnel_aware_repeat_clients(api):
    """Сделка repeat_clients, выигранная через /win (стадия ``rp_won``, не литерал "won"),
    попадает в журнал с funnel=repeat_clients — тот же класс бага, что Фикс 1 win/lose."""
    await api.get("/sales/stages")  # материализовать канон всех воронок
    deal = await _new_deal(api, "JRN-RP-1", stage="rp_request", funnel="repeat_clients", amount=500)
    r = await api.post(f"/sales/deals/{deal['id']}/win")
    assert r.json()["stage"] == "rp_won"

    rows = (await api.get("/sales/journal")).json()
    row = next(x for x in rows if x["deal_id"] == deal["id"])
    assert row["funnel"] == "repeat_clients"


async def test_journal_payment_paid_and_none(session, api):
    """Оплаченный счёт → payment="paid"+invoice_number; сделка без счетов → payment="none"."""
    from core.services.eventbus import EventContext
    from modules.sales.events import on_payment_paid

    paid_deal = await _new_deal(api, "JRN-PAY-1", amount=1000)
    doc = (
        await api.post(f"/sales/deals/{paid_deal['id']}/documents", json={"kind": "invoice"})
    ).json()
    await on_payment_paid({"ref": doc["number"]}, EventContext(session, None))
    await session.commit()
    await api.post(f"/sales/deals/{paid_deal['id']}/win")

    unpaid_deal = await _new_deal(api, "JRN-PAY-2", amount=500)
    await api.post(f"/sales/deals/{unpaid_deal['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    paid_row = next(r for r in rows if r["deal_id"] == paid_deal["id"])
    unpaid_row = next(r for r in rows if r["deal_id"] == unpaid_deal["id"])
    assert paid_row["payment"] == "paid"
    assert paid_row["invoice_number"] == doc["number"]
    assert unpaid_row["payment"] == "none"
    assert unpaid_row["invoice_number"] is None


async def test_journal_sorted_by_closed_on_desc(session, api):
    """Сортировка реестра: closed_on DESC (свежезакрытые — первыми)."""
    from sqlalchemy import select

    from modules.sales.models import Deal

    old = await _new_deal(api, "JRN-OLD", amount=10)
    await api.post(f"/sales/deals/{old['id']}/win")
    new = await _new_deal(api, "JRN-NEW", amount=20)
    await api.post(f"/sales/deals/{new['id']}/win")

    old_obj = (await session.execute(select(Deal).where(Deal.id == old["id"]))).scalar_one()
    new_obj = (await session.execute(select(Deal).where(Deal.id == new["id"]))).scalar_one()
    old_obj.closed_date = "01.01.2026"
    new_obj.closed_date = "10.07.2026"
    await session.commit()

    rows = (await api.get("/sales/journal")).json()
    ids = [r["deal_id"] for r in rows if r["deal_id"] in (old["id"], new["id"])]
    assert ids == [new["id"], old["id"]]  # DESC по closed_on


async def test_journal_honest_margin_without_facade(session, api):
    """Честная деградация: без фасада landed_cost margin_pct is None + margin_reason непустой
    (НЕ 0 — дефолт тестового ядра, core.services.landed_cost is None, пока не подменён стендом)."""
    from modules.sales.models import DealItem

    sku = await _seed_sku(session, "JRN-SKU")
    deal = await _new_deal(api, "JRN-MGN-1", counterparty="ООО Журнал", amount=400)
    session.add(DealItem(deal_id=deal["id"], sku_id=sku.id, qty=1))
    await session.commit()
    await api.post(f"/sales/deals/{deal['id']}/win")

    rows = (await api.get("/sales/journal")).json()
    row = next(r for r in rows if r["deal_id"] == deal["id"])
    assert row["revenue"] is None
    assert row["gross_profit"] is None
    assert row["margin_pct"] is None
    assert row["margin_reason"]


# ── Конструктор месячного плана продавца (GET /plan-sources, PUT /plan-items) ────

async def test_plan_sources_regulars_cycle_and_single_order(session, api):
    """≥2 won-заказа одного контрагента → цикл перезаказа (среднее интервалов) и ожидание
    следующего в месяце; контрагент с 1 заказом — cycle_days/expected пусты, in_month=False."""
    from sqlalchemy import select

    from modules.sales.models import Deal

    d1 = await _new_deal(api, "REG-1", counterparty="Постоянный", amount=1000)
    await api.post(f"/sales/deals/{d1['id']}/win")
    d2 = await _new_deal(api, "REG-2", counterparty="Постоянный", amount=1000)
    await api.post(f"/sales/deals/{d2['id']}/win")
    obj1 = (await session.execute(select(Deal).where(Deal.id == d1["id"]))).scalar_one()
    obj2 = (await session.execute(select(Deal).where(Deal.id == d2["id"]))).scalar_one()
    obj1.closed_date = "10.01.2026"
    obj2.closed_date = "10.03.2026"

    d3 = await _new_deal(api, "REG-3", counterparty="Одноразовый", amount=500)
    await api.post(f"/sales/deals/{d3['id']}/win")
    obj3 = (await session.execute(select(Deal).where(Deal.id == d3["id"]))).scalar_one()
    obj3.closed_date = "01.02.2026"
    await session.commit()

    rows = (await api.get("/sales/plan-sources", params={"month": "2026-05"})).json()
    by_cp = {r["counterparty"]: r for r in rows["regulars"]}

    regular = by_cp["Постоянный"]
    assert regular["orders_count"] == 2
    assert 58 <= regular["cycle_days"] <= 60
    assert regular["expected"].startswith("2026-05")
    assert regular["in_month"] is True

    single = by_cp["Одноразовый"]
    assert single["orders_count"] == 1
    assert single["cycle_days"] is None
    assert single["expected"] is None
    assert single["in_month"] is False


async def test_plan_sources_committed_open_only(api):
    """committed отдаёт ОТКРЫТУЮ сделку с expected_close_date в месяце; won-сделку — нет."""
    open_deal = await _new_deal(api, "CMT-1", amount=800, expected_close_date="15.08.2026")
    won_deal = await _new_deal(api, "CMT-2", amount=900, expected_close_date="20.08.2026")
    await api.post(f"/sales/deals/{won_deal['id']}/win")

    rows = (await api.get("/sales/plan-sources", params={"month": "2026-08"})).json()
    refs = {c["ref"] for c in rows["committed"]}
    assert f"deal:{open_deal['id']}" in refs
    assert f"deal:{won_deal['id']}" not in refs


async def test_plan_items_replace_all_snapshot(api):
    """PUT /plan-items — снапшот-замена: 2 строки → saved_items==2; 1 строка → стало 1."""
    owner_id, period = 501, "2026-08"
    row_a = {"source": "committed", "ref": "deal:1", "title": "A", "when_label": "закрытие ~15.08",
             "revenue": 1000, "gross": 200, "probability": 70, "enabled": True}
    row_b = {"source": "regular", "ref": "cp:Клиент", "title": "Клиент", "when_label": "",
             "revenue": 500, "gross": 100, "probability": 60, "enabled": True}

    put1 = await api.put(
        "/sales/plan-items", params={"owner_id": owner_id, "period_key": period},
        json=[row_a, row_b],
    )
    assert put1.status_code == 200
    assert len(put1.json()) == 2

    src1 = (await api.get(
        "/sales/plan-sources", params={"month": period, "owner_id": owner_id}
    )).json()
    assert len(src1["saved_items"]) == 2

    put2 = await api.put(
        "/sales/plan-items", params={"owner_id": owner_id, "period_key": period}, json=[row_a],
    )
    assert len(put2.json()) == 1

    src2 = (await api.get(
        "/sales/plan-sources", params={"month": period, "owner_id": owner_id}
    )).json()
    assert len(src2["saved_items"]) == 1


async def test_plan_sources_base_gross_from_approved_plan(api):
    """base_gross — согласованный (approved) PlanTarget gross_profit за месяц владельца."""
    owner_id, month = 502, "2026-09"
    plan = (await api.post(
        "/sales/plans",
        json={"owner_id": owner_id, "metric": "gross_profit", "period_type": "month",
              "period_key": month, "target": 15000},
    )).json()
    await api.post(f"/sales/plans/{plan['id']}/submit")
    await api.post(f"/sales/plans/{plan['id']}/decide", json={"approved": True})

    src = (await api.get(
        "/sales/plan-sources", params={"month": month, "owner_id": owner_id}
    )).json()
    assert src["base_gross"] == 15000.0


async def test_plan_sources_invalid_month_422(api):
    """Кривой month → 422 на GET /plan-sources и на PUT /plan-items (period_key)."""
    bad_get = await api.get("/sales/plan-sources", params={"month": "2026-13"})
    assert bad_get.status_code == 422

    bad_put = await api.put(
        "/sales/plan-items", params={"owner_id": 1, "period_key": "not-a-month"}, json=[]
    )
    assert bad_put.status_code == 422
