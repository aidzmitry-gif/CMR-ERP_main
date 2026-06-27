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


async def test_wms_stock_mirror(api, session):
    """`/wms/stock` — зеркало 1С через шлюз: свободно = наличие − резерв, итоги, RBAC."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add(Sku(code="AKB-60", title="Аккумулятор 60 Ач", unit="шт"))
    session.add_all([
        StockItem(sku_code="AKB-60", warehouse="Минск", qty_available=Decimal(41),
                  qty_reserved=Decimal(13), qty_forecast=Decimal(0)),
        StockItem(sku_code="AKB-60", warehouse="Гомель", qty_available=Decimal(18),
                  qty_reserved=Decimal(0), qty_forecast=Decimal(5)),
    ])
    await session.commit()

    data = (await api.get("/wms/stock")).json()
    assert data["gateway"] is True and data["sku_count"] == 1
    minsk = next(r for r in data["rows"] if r["warehouse"] == "Минск")
    assert minsk["qty_free"] == 28.0  # 41 − 13
    assert data["total_available"] == 59.0 and data["total_reserved"] == 13.0
    # фильтр по складу
    one = (await api.get("/wms/stock?warehouse=Гомель")).json()
    assert {r["warehouse"] for r in one["rows"]} == {"Гомель"}

    # RBAC: роль склада проходит (право wms.read), чужая роль — 403 на модуле
    assert (await api.get("/wms/stock", headers={"X-User-Roles": "warehouse"})).status_code == 200
    assert (await api.get("/wms/stock", headers={"X-User-Roles": "sales"})).status_code == 403


async def test_wms_stock_no_gateway(api_no_gateways):
    """Шлюз остатков отключён → честный пустой ответ (gateway=False), не 500."""
    data = (await api_no_gateways.get("/wms/stock")).json()
    assert data["gateway"] is False and data["rows"] == []


async def test_wms_inventory(api, session):
    """Инвентаризация: populate из 1С → факт → расхождение в деньгах → проведение; RBAC."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add(Sku(code="AKB-60", title="Аккумулятор 60 Ач", unit="шт"))
    session.add(StockItem(sku_code="AKB-60", warehouse="Минск",
                          qty_available=Decimal(41), cost=Decimal(230)))
    await session.commit()

    # создать документ и наполнить ожидаемым из 1С
    doc = (await api.post("/wms/inventory", json={"warehouse": "Минск"})).json()
    assert doc["status"] == "open" and doc["number"].startswith("ИНВ-2026-")
    det = (await api.post(f"/wms/inventory/{doc['id']}/populate")).json()
    line = next(line for line in det["lines"] if line["sku_code"] == "AKB-60")
    assert line["expected_qty"] == 41.0 and line["unit_cost"] == 230.0
    assert line["counted_qty"] is None and line["variance"] is None

    # внести факт → недостача 3 шт = −690 BYN
    upd = (await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 38})).json()
    assert upd["variance"] == -3.0 and upd["variance_value"] == -690.0
    det = (await api.get(f"/wms/inventory/{doc['id']}")).json()
    assert det["summary"]["shortages"] == 1 and det["summary"]["shortage_value"] == -690.0

    # провести → done; повторная правка строки запрещена (409)
    done = (await api.post(f"/wms/inventory/{doc['id']}/complete")).json()
    assert done["status"] == "done" and done["completed_at"]
    reedit = await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 40})
    assert reedit.status_code == 409

    # RBAC: пересчёт (wms.count) только у склада; логистика (только wms.read) — 403
    assert (await api.post("/wms/inventory", json={"warehouse": "Минск"},
                           headers={"X-User-Roles": "warehouse"})).status_code == 201
    assert (await api.post("/wms/inventory", json={"warehouse": "Минск"},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


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
