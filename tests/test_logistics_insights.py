"""API-тест Трека 2: сводка «улучшение стоимости» (/logistics/cost-insights).

Поверх сид-эндпоинтов (зоны/тарифы/аудит/демо-тендер): проверяем, что отчёт
считает разброс по зонам, экономию заключённого тендера и сумму к возврату.
"""


async def _seed_all(api):
    await api.post("/logistics/zones/seed")
    await api.post("/logistics/carrier-tariffs/seed")
    await api.post("/logistics/costs/audit/seed")
    rfq = (await api.post("/logistics/rfqs/seed")).json()
    await api.post(f"/logistics/rfqs/{rfq['id']}/award", json={})  # заключить → awarded_price
    return rfq


async def test_cost_insights_empty_db_is_safe(api):
    body = (await api.get("/logistics/cost-insights")).json()
    assert body["zones"] == [] and body["tenders"] == []
    assert body["potential_savings"] == 0 and body["audit_to_recover"] == 0
    assert body["tender_savings_total"] == 0 and body["best_savings_zone"] == ""
    assert body["recommendations"] == []
    assert body["reference_weight_kg"] == 30


async def test_cost_insights_over_seeded_data(api):
    await _seed_all(api)
    body = (await api.get("/logistics/cost-insights")).json()
    # зоны: тарифы по нескольким зонам, у каждой — дешёвый ≤ средний ≤ макс
    assert len(body["zones"]) >= 2
    z = body["zones"][0]
    assert z["cheapest_total"] <= z["avg_total"] <= z["max_total"]
    assert z["carriers"] >= 2 and z["cheapest_carrier_name"]
    assert body["potential_savings"] >= 0
    assert body["best_savings_zone"].startswith("z")
    # тендер: заключённый демо-тендер → экономия (худшая − выигравшая)
    assert body["tender_savings_total"] > 0
    assert any(t["saved"] > 0 and t["awarded"] < t["baseline"] for t in body["tenders"])
    # аудит: к возврату из сидов
    assert body["audit_to_recover"] > 0
    assert any("возврату" in r for r in body["recommendations"])


async def test_cost_insights_weight_param_changes_quotes(api):
    await api.post("/logistics/zones/seed")
    await api.post("/logistics/carrier-tariffs/seed")
    light = (await api.get("/logistics/cost-insights?weight_kg=5")).json()
    heavy = (await api.get("/logistics/cost-insights?weight_kg=100")).json()
    assert heavy["reference_weight_kg"] == 100
    # тяжелее эталон → котировки той же зоны не дешевле
    lz = {z["zone_code"]: z["avg_total"] for z in light["zones"]}
    hz = {z["zone_code"]: z["avg_total"] for z in heavy["zones"]}
    common = set(lz) & set(hz)
    assert common and all(hz[z] >= lz[z] for z in common)
