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
    assert stages["lost"]["title"] == "Закрыто: Отказ"
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
    await api.patch(f"/sales/deals/{deal['id']}", json={"stage": "prop"})

    hist = (await api.get(f"/sales/deals/{deal['id']}/history")).json()
    transitions = [(h["from_stage"], h["to_stage"]) for h in hist]
    assert ("new", "qual") in transitions
    assert ("qual", "prop") in transitions


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
    await _new_deal(api, "WT-1", stage="prop", amount=1000, probability=20)
    # без вероятности → дефолт стадии prop = 50%
    await _new_deal(api, "WT-2", stage="prop", amount=1000)

    board = (await api.get("/sales/board")).json()
    prop = next(s for s in board["stages"] if s["id"] == "prop")
    assert prop["sum"] == 2000
    assert prop["weighted"] == 200 + 500  # 1000*20% + 1000*50%(дефолт)


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
