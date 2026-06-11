"""API-тесты Блока 2 логистики: парк машин, допуски груза, подбор пригодных."""


async def test_fleet_seed_idempotent(api):
    r = await api.post("/logistics/fleet/seed")
    assert r.status_code == 200
    counts = r.json()
    assert counts["vehicles"] == 11 and counts["capabilities"] == 15
    again = (await api.post("/logistics/fleet/seed")).json()
    assert again == counts                       # идемпотентно — без дублей


async def test_vehicles_and_capabilities_crud(api):
    v = await api.post("/logistics/carriers/own/vehicles", json={
        "vehicle_class": "Эвакуатор 3т", "capacity_kg": 3000, "volume_m3": 0, "count": 1,
    })
    assert v.status_code == 201 and v.json()["carrier_code"] == "own"
    assert any(x["vehicle_class"] == "Эвакуатор 3т"
               for x in (await api.get("/logistics/carriers/own/vehicles")).json())
    c = await api.post("/logistics/carriers/own/cargo-capabilities", json={
        "category": "хрупкое", "max_weight_kg": 500,
    })
    assert c.status_code == 201
    assert any(x["category"] == "хрупкое"
               for x in (await api.get("/logistics/carriers/own/cargo-capabilities")).json())


async def test_eligible_heavy_cargo_filters_small_carriers(api):
    await api.post("/logistics/fleet/seed")
    # тяжёлый груз 4500 кг → отсекаются мелкие (Белпочта/Европочта/СДЭК/DPD), остаются крупнотоннажные
    elig = (await api.get("/logistics/carriers/eligible?weight_kg=4500")).json()
    codes = {e["carrier_code"] for e in elig}
    assert "autolight" in codes and "own" in codes
    assert "belpost" not in codes and "evropochta" not in codes
    # сортировка по грузоподъёмности подходящей машины (по возрастанию)
    assert [e["capacity_kg"] for e in elig] == sorted(e["capacity_kg"] for e in elig)
    assert elig[0]["carrier"]                      # имя проставлено


async def test_eligible_by_category_and_adr(api):
    await api.post("/logistics/fleet/seed")
    # АКБ 300 кг — у autolight/cdek/own есть допуск АКБ и машина
    akb = {e["carrier_code"] for e in (await api.get("/logistics/carriers/eligible?weight_kg=300&category=АКБ")).json()}
    assert {"autolight", "cdek", "own"} <= akb
    # опасный груз ADR — только autolight (единственный с допуском ДОПОГ)
    adr = (await api.get("/logistics/carriers/eligible?weight_kg=300&category=опасный_ADR&adr=true")).json()
    assert {e["carrier_code"] for e in adr} == {"autolight"}


async def test_eligible_needs_temp_only_reefer(api):
    await api.post("/logistics/fleet/seed")
    # термо-груз → только перевозчик с рефрижератором (own)
    temp = (await api.get("/logistics/carriers/eligible?weight_kg=500&needs_temp=true")).json()
    assert {e["carrier_code"] for e in temp} == {"own"}
    assert temp[0]["vehicle_class"] == "Рефрижератор 8т"
