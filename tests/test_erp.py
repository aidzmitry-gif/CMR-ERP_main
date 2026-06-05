"""Тесты ERP-модулей: создание записей и регистрация в ядре."""


async def test_procurement(api):
    r = await api.post(
        "/procurement/requests", json={"supplier": "ООО Поставщик", "item": "Болты", "qty": 100}
    )
    assert r.status_code == 201
    assert r.json()["stage"] == "need"
    assert r.json()["number"].startswith("ЗАК-")
    items = (await api.get("/procurement/requests")).json()
    assert any(i["item"] == "Болты" for i in items)
    # доска воронки: стадии по порядку, заявка в первой колонке
    board = (await api.get("/procurement/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "need"
    assert sum(s["count"] for s in board["stages"]) >= 1
    # стадия переговоров → Supplier Score на карточке
    await api.patch(f"/procurement/requests/{r.json()['id']}", json={"stage": "nego"})
    board2 = (await api.get("/procurement/board")).json()
    nego = next(s for s in board2["stages"] if s["id"] == "nego")
    assert nego["cards"][0]["score"] == "Score 8.7"


async def test_production(api):
    r = await api.post("/production/orders", json={"product": "Рама", "qty": 5})
    assert r.status_code == 201
    assert r.json()["stage"] == "queue"
    assert (await api.get("/production/orders")).json()[0]["product"] == "Рама"
    board = (await api.get("/production/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "queue"


async def test_wms(api):
    r = await api.post("/wms/movements", json={"sku_code": "AKB-60", "kind": "in", "qty": 50})
    assert r.status_code == 201
    movements = (await api.get("/wms/movements")).json()
    assert movements[0]["sku_code"] == "AKB-60" and movements[0]["kind"] == "in"
    # воронка складских операций
    op = await api.post("/wms/ops", json={"counterparty": "ООО Поставка", "title": "Металл", "items_count": 12, "amount": 500000})
    assert op.status_code == 201 and op.json()["stage"] == "inbound"
    moved = await api.patch(f"/wms/ops/{op.json()['id']}", json={"stage": "receiving"})
    assert moved.json()["stage"] == "receiving"
    assert len((await api.get("/wms/ops")).json()) >= 1
    assert (await api.patch("/wms/ops/999999", json={"stage": "qc"})).status_code == 404
    board = (await api.get("/wms/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "inbound"
    # на приёмке карточка получает soft-панель пересчёта и кнопку-действие
    recv = next(s for s in board["stages"] if s["id"] == "receiving")
    assert recv["cards"][0]["details"] and recv["cards"][0]["action"] == "Завершить приёмку"


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
    # воронка подбора (кандидаты)
    c = await api.post("/hr/candidates", json={"name": "Анна С.", "position": "Бухгалтер", "salary": 90000})
    assert c.status_code == 201 and c.json()["stage"] == "new"
    assert any(x["name"] == "Анна С." for x in (await api.get("/hr/candidates")).json())
    moved = await api.patch(f"/hr/candidates/{c.json()['id']}", json={"stage": "offer"})
    assert moved.json()["stage"] == "offer"
    assert (await api.patch("/hr/candidates/999999", json={"stage": "offer"})).status_code == 404
    board = (await api.get("/hr/board")).json()
    assert [s["id"] for s in board["stages"]] == ["new", "invite", "tech", "offer", "hired"]


async def test_office(api):
    r = await api.post("/office/docs", json={"company": "ООО Альфа", "title": "Поставка", "amount": 850000})
    assert r.status_code == 201 and r.json()["stage"] == "ready"
    assert len((await api.get("/office/docs")).json()) >= 1
    moved = await api.patch(f"/office/docs/{r.json()['id']}", json={"stage": "paid"})
    assert moved.json()["stage"] == "paid"
    assert (await api.patch("/office/docs/999999", json={"stage": "paid"})).status_code == 404
    board = (await api.get("/office/board")).json()
    assert [s["id"] for s in board["stages"]][0] == "ready"
    assert sum(s["count"] for s in board["stages"]) >= 1


async def test_legal(api):
    r = await api.post("/legal/cases", json={"company": "ООО Бета", "title": "Договор поставки", "amount": 500000})
    assert r.status_code == 201 and r.json()["stage"] == "inbox"
    moved = await api.patch(f"/legal/cases/{r.json()['id']}", json={"stage": "claim"})
    assert moved.json()["stage"] == "claim"
    assert len((await api.get("/legal/cases")).json()) >= 1
    assert (await api.patch("/legal/cases/999999", json={"stage": "done"})).status_code == 404
    board = (await api.get("/legal/board")).json()
    assert len(board["stages"]) == 6


async def test_knowledge(api):
    r = await api.post("/knowledge/courses", json={"title": "Охрана труда", "kind": "Обязательно", "duration": 30})
    assert r.status_code == 201 and r.json()["stage"] == "trial"
    assert r.json()["number"].startswith("КУРС-")
    assert len((await api.get("/knowledge/courses")).json()) >= 1
    moved = await api.patch(f"/knowledge/courses/{r.json()['id']}", json={"stage": "ai"})
    assert moved.json()["stage"] == "ai"
    assert (await api.patch("/knowledge/courses/999999", json={"stage": "ai"})).status_code == 404
    # статус курса из прогресса: Не начат / В процессе / Пройдено
    await api.post("/knowledge/courses", json={"title": "CRM", "progress": 60})
    await api.post("/knowledge/courses", json={"title": "Этика", "progress": 100})
    board = (await api.get("/knowledge/board")).json()
    states = {c["state"] for s in board["stages"] for c in s["cards"]}
    assert {"Не начат", "В процессе", "Пройдено"} <= states
    assert [s["id"] for s in board["stages"]][0] == "trial"


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
        "office",
        "legal",
        "knowledge",
    ):
        assert module in data["loaded_modules"]
