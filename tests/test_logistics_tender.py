# ruff: noqa: F811 -- pytest fixtures imported for this module
"""API-тесты Блока 4: тендер на перевозку — рассылка → предложения → торг → договор."""

from sqlalchemy import select

from core.domain.models import OutboxEvent
from tests.test_logistics_fixtures import exact, shipping_api  # noqa: F401


async def _types(session):
    rows = (await session.execute(select(OutboxEvent).order_by(OutboxEvent.id))).scalars().all()
    return [r.event_type for r in rows]


async def _new_rfq(shipping_api, **over):
    body = {"cargo": "АКБ 280Ач", "weight_kg": 900, "category": "АКБ",
            "route_from": "Минск", "route_to": "Гомель", "zone_code": "z2",
            "created_by": "Ольга К."}
    body.update(over)
    return (await shipping_api.post("/logistics/rfqs", json=body)).json()


async def test_create_rfq_autonumbers(shipping_api):
    rfq = await _new_rfq(shipping_api)
    assert rfq["number"].startswith("ТНД-2026-") and rfq["status"] == "draft"
    assert (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}")).json()["cargo"] == "АКБ 280Ач"
    assert (await shipping_api.get("/logistics/rfqs/999")).status_code == 404


async def test_broadcast_targets_eligible_carriers(shipping_api, session):
    await shipping_api.post("/logistics/fleet/seed")
    rfq = await _new_rfq(shipping_api)  # АКБ 900 кг → autolight/cdek/own имеют допуск АКБ и машину
    r = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/broadcast")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"
    assert set(body["carriers"]) == {"autolight", "cdek", "own"}
    assert body["invited"] == 3
    # повторная рассылка не дублирует приглашения
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/broadcast")
    assert len((await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/invites")).json()) == 3
    assert "logistics.rfq.broadcast" in await _types(session)


async def test_bids_collected_and_sorted(shipping_api):
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "autolight", "price": 680, "eta_days": 2})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "own", "price": 600, "eta_days": 1})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "cdek", "price": 740})
    assert (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}")).json()["status"] == "collecting"
    bids = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/bids")).json()
    assert [b["price"] for b in bids] == [600, 680, 740]   # по возрастанию цены
    assert bids[0]["carrier_code"] == "own" and bids[0]["is_best"] is True
    assert bids[0]["carrier"] == "Свой транспорт"


async def test_negotiate_creates_next_round(shipping_api):
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "autolight", "price": 680})
    neg = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/negotiate", json={"carrier_code": "autolight", "new_price": 620, "comment": "скидка за объём"})
    assert neg.status_code == 201
    assert neg.json()["round"] == 2 and neg.json()["price"] == 620
    assert (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}")).json()["status"] == "negotiation"
    # торг без предложения этого перевозчика → 404
    assert (await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/negotiate", json={"carrier_code": "dpd", "new_price": 500})).status_code == 404


async def test_award_creates_shipment_and_contract_event(shipping_api, session):
    rfq = await _new_rfq(shipping_api, deal_id=42, office_doc_ref="ДОК-2026-0001")
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "autolight", "price": 680})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "own", "price": 600})
    # без carrier_code → выбирается минимальная цена (own, 600)
    award = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/award", json={})
    assert award.status_code == 200
    body = award.json()
    assert body["carrier_code"] == "own" and body["price"] == 600
    assert body["shipment_number"].startswith("ЛОГ-2026-")
    rfq_after = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}")).json()
    assert rfq_after["status"] == "contracted" and rfq_after["awarded_price"] == 600
    assert rfq_after["shipment_id"] == body["shipment_id"]
    # создана отгрузка с перевозчиком и ценой; событие договора
    ship = next(s for s in (await shipping_api.get("/logistics/shipments")).json() if s["id"] == body["shipment_id"])
    assert ship["carrier"] == "Свой транспорт" and ship["amount"] == 600 and ship["deal_id"] == 1
    assert "logistics.contract.signed" in await _types(session)


async def test_award_by_specific_carrier(shipping_api):
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "autolight", "price": 680})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "own", "price": 600})
    # явный выбор перевозчика дороже минимального
    award = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/award", json={"carrier_code": "autolight"})
    assert award.json()["carrier_code"] == "autolight" and award.json()["price"] == 680


async def test_award_without_bids_404(shipping_api):
    rfq = await _new_rfq(shipping_api)
    assert (await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/award", json={})).status_code == 404


async def test_rfq_seed_and_board(shipping_api):
    seeded = await shipping_api.post("/logistics/rfqs/seed")
    assert seeded.status_code == 409 and seeded.json()["detail"] == "organization_scope_incomplete"
    rfq = await _new_rfq(shipping_api)
    board = (await shipping_api.get("/logistics/rfqs/board")).json()
    assert any(card["id"] == rfq["id"] for stage in board["stages"] for card in stage["cards"])


async def test_bids_ranked_best_value_not_cheapest(shipping_api):
    # надёжный dpd чуть дороже дешёвого belpost → best-fit выбирает dpd, не цену
    await shipping_api.post("/logistics/carriers/scorecard/seed")   # балл dpd ≫ belpost
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "belpost", "price": 600})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "dpd", "price": 610})
    ranked = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/bids/ranked")).json()
    assert ranked[0]["carrier_code"] == "dpd" and ranked[0]["is_best_value"] is True
    assert 0 <= ranked[1]["value_score"] <= ranked[0]["value_score"] <= 1
    # для сравнения: по цене лучший — belpost
    by_price = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/bids")).json()
    assert by_price[0]["carrier_code"] == "belpost" and by_price[0]["is_best"] is True


async def test_award_best_value_strategy(shipping_api):
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "belpost", "price": 600})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "dpd", "price": 610})
    # cheapest (по умолчанию) → belpost; best_value → dpd
    cheapest = await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/award", json={})
    assert cheapest.json()["carrier_code"] == "belpost" and cheapest.json()["price"] == 600
    rfq2 = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq2['id']}/bids", json={"carrier_code": "belpost", "price": 600})
    await shipping_api.post(f"/logistics/rfqs/{rfq2['id']}/bids", json={"carrier_code": "dpd", "price": 610})
    best = await shipping_api.post(f"/logistics/rfqs/{rfq2['id']}/award", json={"strategy": "best_value"})
    assert best.json()["carrier_code"] == "dpd" and best.json()["price"] == 610


async def test_rfq_recommendation_dumping_flag(shipping_api):
    # 5 ставок: belpost демпинг 60, остальные 95..120 → флаг dumping_risk
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    rfq = await _new_rfq(shipping_api)
    for code, price in [("belpost", 60), ("evropochta", 95), ("cdek", 100),
                         ("autolight", 105), ("dpd", 120)]:
        await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids",
                       json={"carrier_code": code, "price": price})
    rec = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/recommendation")).json()
    assert rec["median_price"] == 100
    assert rec["cheapest_deviation_pct"] == 40.0
    assert rec["dumping_risk"] is True
    assert "демпинг" in rec["rationale"] or "медиан" in rec["rationale"]


async def test_rfq_recommendation_premium_and_rationale(shipping_api):
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "belpost", "price": 600})
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/bids", json={"carrier_code": "dpd", "price": 610})
    rec = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/recommendation")).json()
    assert rec["cheapest"]["carrier_code"] == "belpost"
    assert rec["best_value"]["carrier_code"] == "dpd"
    assert rec["reliability_premium"] == 10 and rec["same_carrier"] is False
    assert "BYN" in rec["rationale"]
    # совпадение дёшево=надёжно → same_carrier, доплата 0
    rfq2 = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq2['id']}/bids", json={"carrier_code": "dpd", "price": 500})
    rec2 = (await shipping_api.get(f"/logistics/rfqs/{rfq2['id']}/recommendation")).json()
    assert rec2["same_carrier"] is True and rec2["reliability_premium"] == 0
    # нет ставок → 404
    rfq3 = await _new_rfq(shipping_api)
    assert (await shipping_api.get(f"/logistics/rfqs/{rfq3['id']}/recommendation")).status_code == 404
