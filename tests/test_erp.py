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


async def test_logistics(api):
    r = await api.post(
        "/logistics/shipments",
        json={"customer": "ООО Клиент", "address": "Минск", "carrier": "СДЭК"},
    )
    assert r.status_code == 201
    assert (await api.get("/logistics/shipments")).json()[0]["customer"] == "ООО Клиент"


async def test_finance(api):
    r = await api.post("/finance/payments", json={"ref": "Счёт СЧ-1", "amount": 5000})
    assert r.status_code == 201
    assert (await api.get("/finance/payments")).json()[0]["amount"] == 5000


async def test_marketing(api):
    r = await api.post(
        "/marketing/campaigns",
        json={"name": "Весна", "channel": "email", "budget": 1000, "leads": 25},
    )
    assert r.status_code == 201
    assert (await api.get("/marketing/campaigns")).json()[0]["leads"] == 25


async def test_service(api):
    r = await api.post(
        "/service/tickets", json={"customer": "ООО Клиент", "subject": "Не работает доставка"}
    )
    assert r.status_code == 201
    assert r.json()["status"] == "open"
    assert (await api.get("/service/tickets")).json()[0]["subject"] == "Не работает доставка"


async def test_hr(api):
    r = await api.post(
        "/hr/employees",
        json={"full_name": "Иван Петров", "position": "Менеджер", "department": "Продажи"},
    )
    assert r.status_code == 201
    assert (await api.get("/hr/employees")).json()[0]["full_name"] == "Иван Петров"


async def test_erp_modules_loaded(api):
    data = (await api.get("/system/modules")).json()
    for module in (
        "sales",
        "integrations",
        "procurement",
        "production",
        "wms",
        "logistics",
        "finance",
        "marketing",
        "service",
        "hr",
    ):
        assert module in data["loaded_modules"]
