"""Тесты ERP-модулей: создание записей и регистрация в ядре."""


async def test_procurement(api):
    r = await api.post(
        "/procurement/requests", json={"supplier": "ООО Поставщик", "item": "Болты", "qty": 100}
    )
    assert r.status_code == 201
    assert r.json()["status"] == "new"
    items = (await api.get("/procurement/requests")).json()
    assert any(i["item"] == "Болты" for i in items)


async def test_production(api):
    r = await api.post("/production/orders", json={"product": "Рама", "qty": 5})
    assert r.status_code == 201
    assert r.json()["status"] == "planned"
    assert (await api.get("/production/orders")).json()[0]["product"] == "Рама"


async def test_wms(api):
    r = await api.post("/wms/movements", json={"sku_code": "AKB-60", "kind": "in", "qty": 50})
    assert r.status_code == 201
    movements = (await api.get("/wms/movements")).json()
    assert movements[0]["sku_code"] == "AKB-60" and movements[0]["kind"] == "in"


async def test_erp_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    for module in ("sales", "integrations", "procurement", "production", "wms"):
        assert module in data["loaded_modules"]
