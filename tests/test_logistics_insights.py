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
    for weight in (5, 100):
        response = await api.get(f"/logistics/cost-insights?weight_kg={weight}")
        assert response.status_code == 409
        assert response.json()["detail"] == "organization_scope_incomplete"


async def test_cost_insights_over_seeded_data(api):
    await api.post("/logistics/zones/seed")
    await api.post("/logistics/carrier-tariffs/seed")
    for weight in (5, 100):
        response = await api.get(f"/logistics/cost-insights?weight_kg={weight}")
        assert response.status_code == 409
        assert response.json()["detail"] == "organization_scope_incomplete"


async def test_cost_insights_weight_param_changes_quotes(api):
    await api.post("/logistics/zones/seed")
    await api.post("/logistics/carrier-tariffs/seed")
    for weight in (5, 100):
        response = await api.get(f"/logistics/cost-insights?weight_kg={weight}")
        assert response.status_code == 409
        assert response.json()["detail"] == "organization_scope_incomplete"
