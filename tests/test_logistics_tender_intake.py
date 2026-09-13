# ruff: noqa: F811 -- pytest fixtures imported for this module
"""API-тесты Трека 3: реализм тендера — токен публичной ссылки, приём ставки, уведомление.

Рассылка выдаёт каждому приглашению токен и пишет журнал; перевозчик подаёт ставку
сам по ``POST /rfqs/bid/{token}`` (без авторизации), минуя ручной ввод офисом.
"""

from tests.test_logistics_fixtures import exact, shipping_api  # noqa: F401


async def _new_rfq(shipping_api, **over):
    body = {"cargo": "АКБ 280Ач", "weight_kg": 900, "category": "АКБ",
            "route_from": "Минск", "route_to": "Гомель", "zone_code": "z2"}
    body.update(over)
    return (await shipping_api.post("/logistics/rfqs", json=body)).json()


async def test_broadcast_assigns_tokens_and_journal(shipping_api):
    await shipping_api.post("/logistics/fleet/seed")
    rfq = await _new_rfq(shipping_api)                                  # АКБ 900 кг → autolight/cdek/own
    body = (await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/broadcast")).json()
    assert body["invited"] == 3 and body["notified"] == 0     # контактов в реестре нет → канал none
    invites = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/invites")).json()
    assert len(invites) == 3
    tokens = [i["token"] for i in invites]
    assert all(tokens) and len(set(tokens)) == 3              # у каждого свой непустой токен
    assert all(i["detail"] for i in invites)                  # журнал рассылки заполнен
    assert all(i["notified_at"] for i in invites)


async def test_broadcast_notifies_carrier_with_contact(shipping_api):
    await shipping_api.post("/logistics/fleet/seed")
    await shipping_api.post("/logistics/carriers", json={
        "name": "Автолайт Экспресс", "code": "autolight", "contact": "tender@autolight.by"})
    rfq = await _new_rfq(shipping_api)
    body = (await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/broadcast")).json()
    assert body["notified"] >= 1                               # есть контакт → уведомлён
    invites = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/invites")).json()
    al = next(i for i in invites if i["carrier_code"] == "autolight")
    assert al["channel"] == "email" and al["status"] == "sent"


async def test_public_bid_by_token_creates_bid(shipping_api):
    await shipping_api.post("/logistics/fleet/seed")
    rfq = await _new_rfq(shipping_api)
    await shipping_api.post(f"/logistics/rfqs/{rfq['id']}/broadcast")
    inv = (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/invites")).json()[0]
    r = await shipping_api.post(f"/logistics/rfqs/bid/{inv['token']}",
                       json={"price": 650, "eta_days": 2, "comment": "по ссылке"})
    assert r.status_code == 201
    bid = r.json()
    assert bid["carrier_code"] == inv["carrier_code"] and bid["price"] == 650
    # тендер → сбор, приглашение → откликнулось
    assert (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}")).json()["status"] == "collecting"
    inv_after = next(i for i in (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/invites")).json()
                     if i["id"] == inv["id"])
    assert inv_after["status"] == "responded"
    assert any(b["price"] == 650 for b in (await shipping_api.get(f"/logistics/rfqs/{rfq['id']}/bids")).json())


async def test_public_bid_unknown_token_404(shipping_api):
    r = await shipping_api.post("/logistics/rfqs/bid/нет-такого-токена", json={"price": 100})
    assert r.status_code == 404
