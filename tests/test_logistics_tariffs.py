# ruff: noqa: F811 -- pytest fixtures imported for this module
"""API-тесты Блока 1 логистики: зоны, тарифы, котировки, scorecard, аудит счетов."""

from tests.test_logistics_fixtures import exact, shipping_api  # noqa: F401


async def test_zones_seed_idempotent(shipping_api):
    r = await shipping_api.post("/logistics/zones/seed")
    assert r.status_code == 200
    assert {z["code"] for z in r.json()} == {"z1", "z2", "z3", "z4"}
    # повторный сид не плодит дубликаты
    again = await shipping_api.post("/logistics/zones/seed")
    assert len(again.json()) == 4
    assert len((await shipping_api.get("/logistics/zones")).json()) == 4


async def test_tariffs_seed_and_filter(shipping_api):
    r = await shipping_api.post("/logistics/carrier-tariffs/seed")
    assert r.status_code == 200
    assert len(r.json()) == 20                       # 5 перевозчиков × 4 зоны
    assert len((await shipping_api.post("/logistics/carrier-tariffs/seed")).json()) == 20  # идемпотентно
    z2 = (await shipping_api.get("/logistics/carrier-tariffs?zone=z2")).json()
    assert len(z2) == 5 and all(t["zone_code"] == "z2" for t in z2)


async def test_quote_sorted_cheapest_first(shipping_api):
    await shipping_api.post("/logistics/zones/seed")
    await shipping_api.post("/logistics/carrier-tariffs/seed")
    sid = (await shipping_api.post("/logistics/shipments", json={"customer": "ООО Тест", "weight_kg": 64})).json()["id"]
    r = await shipping_api.post(f"/logistics/shipments/{sid}/quote", json={"zone_code": "z2", "weight_kg": 64})
    assert r.status_code == 200
    quotes = r.json()
    assert len(quotes) == 5
    # дешевле всех — Белпочта (15.00 + 34*1.15 = 54.10); сортировка по total
    assert quotes[0]["carrier_code"] == "belpost" and quotes[0]["total"] == 54.10
    assert [q["total"] for q in quotes] == sorted(q["total"] for q in quotes)
    autolight = next(q for q in quotes if q["carrier_code"] == "autolight")
    assert autolight["total"] == 78.40            # пример из спеки
    assert autolight["carrier"] == "Автолайт Экспресс" and autolight["sla_days_max"] == 2


async def test_quote_uses_shipment_weight_when_omitted(shipping_api):
    await shipping_api.post("/logistics/zones/seed")
    await shipping_api.post("/logistics/carrier-tariffs/seed")
    sid = (await shipping_api.post("/logistics/shipments", json={"customer": "ООО Вес", "weight_kg": 3})).json()["id"]
    r = await shipping_api.post(f"/logistics/shipments/{sid}/quote", json={"zone_code": "z1"})
    assert r.status_code == 200
    # вес 3 кг → вилка ≤5; у Белпочты z1 base 4.20
    assert next(q for q in r.json() if q["carrier_code"] == "belpost")["base"] == 4.20


async def test_quote_errors(shipping_api):
    await shipping_api.post("/logistics/zones/seed")
    # 404 — нет отгрузки
    assert (await shipping_api.post("/logistics/shipments/999/quote", json={"zone_code": "z1"})).status_code == 404
    sid = (await shipping_api.post("/logistics/shipments", json={"customer": "X"})).json()["id"]
    # 422 — неизвестная зона
    assert (await shipping_api.post(f"/logistics/shipments/{sid}/quote", json={"zone_code": "zX"})).status_code == 422
    # 404 — зона есть, но тарифы не засеяны
    r = await shipping_api.post(f"/logistics/shipments/{sid}/quote", json={"zone_code": "z1"})
    assert r.status_code == 404


async def test_scorecard_seed_sorted_by_score(shipping_api):
    r = await shipping_api.post("/logistics/carriers/scorecard/seed")
    assert r.status_code == 200 and len(r.json()) == 5
    assert len((await shipping_api.post("/logistics/carriers/scorecard/seed")).json()) == 5  # идемпотентно
    cards = (await shipping_api.get("/logistics/carriers/scorecard?period=2026-06")).json()
    assert cards[0]["carrier_code"] == "dpd" and cards[0]["grade"] == "A"
    assert [c["score"] for c in cards] == sorted((c["score"] for c in cards), reverse=True)


async def test_scorecard_score_computed_from_metrics(shipping_api):
    from modules.logistics import pricing
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    dpd = next(
        c for c in (await shipping_api.get("/logistics/carriers/scorecard")).json()
        if c["carrier_code"] == "dpd"
    )
    # балл — не литерал сида, а свёртка метрик (pricing.score_carrier)
    expected = pricing.score_carrier(
        dpd["otd_pct"], dpd["damage_free_pct"], dpd["billing_accuracy_pct"], dpd["claims_ratio_pct"]
    )
    assert dpd["score"] == expected and dpd["grade"] == pricing.grade_for(expected)


async def test_tariff_edit_updates_existing(shipping_api):
    """Правка тарифа: PATCH меняет цены, GET отдаёт новые. 404 — на неизвестный код."""
    await shipping_api.post("/logistics/zones/seed")
    await shipping_api.post("/logistics/carrier-tariffs/seed")
    r = await shipping_api.patch(
        "/logistics/carrier-tariffs/dpd/z2",
        json={"price_w5": 999.99, "pickup_fee": 5.0},
    )
    assert r.status_code == 200
    assert float(r.json()["price_w5"]) == 999.99 and float(r.json()["pickup_fee"]) == 5.0
    # GET отдаёт изменённое
    z2 = (await shipping_api.get("/logistics/carrier-tariffs?zone=z2")).json()
    dpd = next(t for t in z2 if t["carrier_code"] == "dpd")
    assert float(dpd["price_w5"]) == 999.99
    # 404 на отсутствующий тариф
    assert (await shipping_api.patch(
        "/logistics/carrier-tariffs/unknown/z2", json={"price_w5": 1}
    )).status_code == 404


async def test_scorecard_edit_metrics_updates_score(shipping_api):
    """Правка KPI пересчитывает балл/грейд: dpd → claims↑ → балл↓, грейд может ухудшиться."""
    from modules.logistics import pricing

    await shipping_api.post("/logistics/carriers/scorecard/seed")
    before = next(
        c for c in (await shipping_api.get("/logistics/carriers/scorecard?period=2026-06")).json()
        if c["carrier_code"] == "dpd"
    )
    # резко увеличим долю претензий
    r = await shipping_api.patch(
        "/logistics/carriers/scorecard/dpd?period=2026-06",
        json={"claims_ratio_pct": 50.0},
    )
    assert r.status_code == 200
    after = r.json()
    expected = pricing.score_carrier(
        after["otd_pct"], after["damage_free_pct"],
        after["billing_accuracy_pct"], after["claims_ratio_pct"],
    )
    assert after["score"] == expected and after["score"] < before["score"]
    assert after["grade"] == pricing.grade_for(expected)


async def test_scorecard_edit_404_for_missing(shipping_api):
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    r = await shipping_api.patch(
        "/logistics/carriers/scorecard/unknown?period=2026-06",
        json={"otd_pct": 99.0},
    )
    assert r.status_code == 404


async def test_scorecard_edit_requires_period(shipping_api):
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    r = await shipping_api.patch("/logistics/carriers/scorecard/dpd", json={"otd_pct": 99.0})
    assert r.status_code == 422


async def test_scorecard_recompute_idempotent(shipping_api):
    await shipping_api.post("/logistics/carriers/scorecard/seed")
    before = (await shipping_api.get("/logistics/carriers/scorecard")).json()
    rc = await shipping_api.post("/logistics/carriers/scorecard/recompute")
    assert rc.status_code == 200
    after = {c["carrier_code"]: c["score"] for c in rc.json()}
    # пересчёт из тех же метрик не меняет баллы и сохраняет сортировку по убыванию
    assert {c["carrier_code"]: c["score"] for c in before} == after
    assert [c["score"] for c in rc.json()] == sorted((c["score"] for c in rc.json()), reverse=True)


async def test_audit_seed_and_report(shipping_api):
    assert (await shipping_api.post("/logistics/costs/audit/seed")).status_code == 409
    rep = await shipping_api.get("/logistics/costs/audit")
    assert rep.status_code == 409 and rep.json()["detail"] == "organization_scope_incomplete"


async def test_audit_create_with_explicit_expected(shipping_api):
    r = await shipping_api.post("/logistics/costs/audit", json={
        "shipment_code": "ЛОГ-2026-0099", "carrier_code": "dpd",
        "invoice_amount": 30.0, "expected_amount": 28.0, "reason": "тест",
    })
    assert r.status_code == 409 and r.json()["detail"] == "organization_scope_incomplete"


async def test_audit_create_computes_expected_from_tariff(shipping_api):
    await shipping_api.post("/logistics/carrier-tariffs/seed")
    # вес 64 кг, зона z2, автолайт → ожидаемо 78.40; счёт 80.00 → variance 1.60
    r = await shipping_api.post("/logistics/costs/audit", json={
        "shipment_code": "ЛОГ-2026-0100", "carrier_code": "autolight",
        "invoice_amount": 80.0, "zone_code": "z2", "weight_kg": 64,
    })
    assert r.status_code == 409 and r.json()["detail"] == "organization_scope_incomplete"


async def test_audit_create_without_expected_or_tariff_422(shipping_api):
    r = await shipping_api.post("/logistics/costs/audit", json={
        "shipment_code": "ЛОГ-2026-0101", "carrier_code": "autolight",
        "invoice_amount": 80.0, "zone_code": "z2", "weight_kg": 64,
    })
    assert r.status_code == 409 and r.json()["detail"] == "organization_scope_incomplete"
