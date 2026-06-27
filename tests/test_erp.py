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


async def test_wms_operational(api, session):
    """Операции (приёмка/отгрузка/перемещение/коррекция) → движения + оперативный остаток."""
    from types import SimpleNamespace

    from modules.wms.events import on_stock_released

    loc1 = (await api.post("/wms/locations", json={"warehouse": "Минск", "zone": "A", "code": "A-01"})).json()
    loc2 = (await api.post("/wms/locations", json={"warehouse": "Минск", "zone": "A", "code": "A-02"})).json()
    assert loc1["is_active"] is True

    base = {"sku_code": "AKB-60", "warehouse": "Минск"}
    assert (await api.post("/wms/receipt", json={**base, "qty": 10, "location_id": loc1["id"]})).status_code == 201
    assert (await api.post("/wms/shipment", json={**base, "qty": 3, "location_id": loc1["id"]})).status_code == 201
    tr = await api.post("/wms/transfer", json={**base, "qty": 2, "from_location_id": loc1["id"], "to_location_id": loc2["id"]})
    assert tr.status_code == 201 and len(tr.json()) == 2 and tr.json()[0]["doc_ref"].startswith("TRF-")
    assert (await api.post("/wms/adjustment", json={**base, "qty": -1, "location_id": loc1["id"]})).status_code == 201

    bal = (await api.get("/wms/balances?sku=AKB-60")).json()
    by_code = {r["location_code"]: r["qty"] for r in bal["rows"]}
    assert by_code["A-01"] == 4.0  # +10 −3 −2(перемещение) −1(коррекция)
    assert by_code["A-02"] == 2.0
    assert bal["sku_count"] == 1

    # фильтр движений по причине
    moves = (await api.get("/wms/movements?reason=transfer")).json()
    assert moves and all(m["reason"] == "transfer" for m in moves)

    # transfer на ту же ячейку — 400
    assert (await api.post("/wms/transfer", json={**base, "qty": 1,
            "from_location_id": loc1["id"], "to_location_id": loc1["id"]})).status_code == 400

    # снятие резерва (событие sales) → приходное движение reason=release
    await on_stock_released({"items": [{"sku_code": "AKB-60", "warehouse": "Минск", "qty": 5}]},
                            SimpleNamespace(session=session))
    await session.commit()
    rel = (await api.get("/wms/movements?reason=release")).json()
    assert rel and rel[0]["kind"] == "in" and rel[0]["qty"] == 5.0

    # RBAC: операции (wms.count) только у склада; логистика (wms.read) — 403
    assert (await api.post("/wms/receipt", json={**base, "qty": 1},
            headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_inventory_adjustment_movements(api, session):
    """Проведение инвентаризации пишет корректирующие движения в журнал WMS (не в 1С)."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add(Sku(code="ZU-15A", title="ЗУ 15А", unit="шт"))
    session.add(StockItem(sku_code="ZU-15A", warehouse="Гомель",
                          qty_available=Decimal(30), cost=Decimal(300)))
    await session.commit()

    doc = (await api.post("/wms/inventory", json={"warehouse": "Гомель"})).json()
    det = (await api.post(f"/wms/inventory/{doc['id']}/populate")).json()
    line = next(line for line in det["lines"] if line["sku_code"] == "ZU-15A")
    await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 27})  # недостача 3
    assert (await api.post(f"/wms/inventory/{doc['id']}/complete")).json()["status"] == "done"

    adj = (await api.get("/wms/movements?reason=adjustment")).json()
    row = next(m for m in adj if m["sku_code"] == "ZU-15A")
    assert row["kind"] == "out" and row["qty"] == 3.0 and row["doc_ref"] == doc["number"]


async def test_wms_receipt_qc(api, session):
    """Событие прихода → документ приёмки pending_qc БЕЗ движения; QC фиксирует решение."""
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-60", "qty": 20, "warehouse": "Минск", "entity_ref": "purchase:7"},
        SimpleNamespace(session=session),
    )
    await session.commit()

    rs = (await api.get("/wms/receipts?status=pending_qc")).json()
    assert rs and rs[0]["source"] == "procurement" and rs[0]["entity_ref"] == "purchase:7"
    rid = rs[0]["id"]
    det = (await api.get(f"/wms/receipts/{rid}")).json()
    line = det["lines"][0]
    assert line["sku_code"] == "AKB-60" and line["expected_qty"] == 20.0
    assert line["accepted_qty"] is None
    # ключевой DoD: движения прихода по приёмке ещё НЕТ (до accept)
    assert (await api.get("/wms/movements?reason=receipt")).json() == []

    qc = await api.post(
        f"/wms/receipts/{rid}/qc",
        json={"decisions": [{"line_id": line["id"], "accepted_qty": 18, "rejected_qty": 2,
                             "reject_reason": "бой"}], "decided_by": "Кладовщик"},
    )
    assert qc.status_code == 200
    l2 = qc.json()["lines"][0]
    assert l2["accepted_qty"] == 18.0 and l2["rejected_qty"] == 2.0 and l2["reject_reason"] == "бой"

    # RBAC: ручная приёмка — под wms.count
    assert (await api.post("/wms/receipts", json={"warehouse": "Минск", "lines": []},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_receipt_accept(api, session):
    """Проведение приёмки: приход по факту QC (брак не на балансе), идемпотентно."""
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-100", "qty": 15, "warehouse": "Брест", "entity_ref": "purchase:9"},
        SimpleNamespace(session=session),
    )
    await session.commit()
    rid = (await api.get("/wms/receipts?status=pending_qc")).json()[0]["id"]
    line = (await api.get(f"/wms/receipts/{rid}")).json()["lines"][0]
    await api.post(
        f"/wms/receipts/{rid}/qc",
        json={"decisions": [{"line_id": line["id"], "accepted_qty": 12, "rejected_qty": 3,
                             "reject_reason": "скол"}]},
    )
    acc = await api.post(f"/wms/receipts/{rid}/accept")
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"

    # оперативный остаток вырос ровно на принятые 12 (брак 3 на свободный остаток НЕ попал)
    bal = (await api.get("/wms/balances?sku=AKB-100")).json()
    assert sum(r["qty"] for r in bal["rows"] if r["sku_code"] == "AKB-100") == 12.0
    mv = (await api.get("/wms/movements?reason=receipt")).json()
    assert any(m["doc_ref"].startswith("ПРМ-") and m["qty"] == 12.0 for m in mv)

    # идемпотентность: повторный accept не плодит движения
    again = await api.post(f"/wms/receipts/{rid}/accept")
    assert again.status_code == 200
    assert len((await api.get("/wms/movements?reason=receipt")).json()) == len(mv)


async def test_wms_tasks(api, session):
    """accept приёмки → put-away задача; её завершение перемещает остаток; pick → out."""
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received

    recv = (await api.post("/wms/locations", json={"warehouse": "Минск", "zone": "RECV", "code": "RECV-01"})).json()
    perm = (await api.post("/wms/locations", json={"warehouse": "Минск", "zone": "A", "code": "A-10"})).json()
    await on_goods_received(
        {"item": "REBAR-10", "qty": 100, "warehouse": "Минск", "entity_ref": "purchase:11"},
        SimpleNamespace(session=session),
    )
    await session.commit()
    rid = (await api.get("/wms/receipts?status=pending_qc")).json()[0]["id"]
    line = (await api.get(f"/wms/receipts/{rid}")).json()["lines"][0]
    await api.post(f"/wms/receipts/{rid}/qc",
                   json={"decisions": [{"line_id": line["id"], "accepted_qty": 100, "location_id": recv["id"]}]})
    await api.post(f"/wms/receipts/{rid}/accept")

    tasks = (await api.get("/wms/tasks?kind=putaway&status=open")).json()
    t = next(t for t in tasks if t["sku_code"] == "REBAR-10")
    assert t["from_location_id"] == recv["id"] and t["qty"] == 100.0
    done = await api.patch(f"/wms/tasks/{t['id']}", json={"status": "done", "to_location_id": perm["id"]})
    assert done.status_code == 200 and done.json()["status"] == "done"
    bal = {r["location_code"]: r["qty"] for r in (await api.get("/wms/balances?sku=REBAR-10")).json()["rows"]}
    assert bal.get("A-10") == 100.0 and bal.get("RECV-01", 0) == 0.0

    # put-away done без ячейки назначения → 400
    t2 = (await api.post("/wms/tasks", json={"kind": "putaway", "sku_code": "X", "qty": 1,
                                             "warehouse": "Минск", "from_location_id": recv["id"]})).json()
    assert (await api.patch(f"/wms/tasks/{t2['id']}", json={"status": "done"})).status_code == 400

    # pick → расход reason=pick
    tp = (await api.post("/wms/tasks", json={"kind": "pick", "sku_code": "REBAR-10", "qty": 20,
                                             "warehouse": "Минск", "from_location_id": perm["id"]})).json()
    await api.patch(f"/wms/tasks/{tp['id']}", json={"status": "done"})
    picks = (await api.get("/wms/movements?reason=pick")).json()
    assert any(m["sku_code"] == "REBAR-10" and m["qty"] == 20.0 for m in picks)

    # RBAC: создание задачи под wms.count
    assert (await api.post("/wms/tasks", json={"kind": "pick", "sku_code": "X", "qty": 1},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_outbound(api, session):
    """Резерв из sales создаёт pick-задачи; упаковка (/pack) нейтральна для остатка."""
    from types import SimpleNamespace

    from modules.wms.events import on_stock_reserved

    await on_stock_reserved(
        {"doc_ref": "DEAL-5", "items": [{"sku_code": "ROLL-3", "warehouse": "Минск", "qty": 10}]},
        SimpleNamespace(session=session),
    )
    await session.commit()
    picks = (await api.get("/wms/tasks?kind=pick&status=open")).json()
    assert any(t["sku_code"] == "ROLL-3" and t["qty"] == 10.0 and t["doc_ref"] == "DEAL-5" for t in picks)

    before = sum(r["qty"] for r in (await api.get("/wms/balances?sku=ROLL-3")).json()["rows"])
    pk = await api.post("/wms/pack", json={"sku_code": "ROLL-3", "qty": 10, "warehouse": "Минск", "doc_ref": "DEAL-5"})
    assert pk.status_code == 201 and len(pk.json()) == 2
    after = sum(r["qty"] for r in (await api.get("/wms/balances?sku=ROLL-3")).json()["rows"])
    assert after == before  # упаковка balance-нейтральна (физический расход — отгрузка)

    assert (await api.post("/wms/pack", json={"sku_code": "X", "qty": 1},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_reconciliation(api, session):
    """Сверка теневого остатка WMS с зеркалом 1С: diff и его денежная оценка."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add(Sku(code="LFP-12-100", title="LFP АКБ", unit="шт"))
    session.add(StockItem(sku_code="LFP-12-100", warehouse="Минск",
                          qty_available=Decimal(14), cost=Decimal(1850)))
    await session.commit()
    await api.post("/wms/receipt", json={"sku_code": "LFP-12-100", "qty": 10, "warehouse": "Минск"})

    rec = (await api.get("/wms/reconciliation")).json()
    assert rec["gateway"] is True
    row = next(r for r in rec["rows"] if r["sku_code"] == "LFP-12-100" and r["warehouse"] == "Минск")
    assert row["wms_qty"] == 10.0 and row["onec_qty"] == 14.0 and row["diff"] == -4.0
    assert row["diff_value"] == -7400.0  # −4 × 1850
    assert rec["total_abs_diff_value"] >= 7400.0


async def test_wms_reconciliation_no_gateway(api_no_gateways):
    """Шлюз 1С выключен → честный пустой ответ (gateway=False), не 500."""
    rec = (await api_no_gateways.get("/wms/reconciliation")).json()
    assert rec["gateway"] is False and rec["rows"] == []


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
