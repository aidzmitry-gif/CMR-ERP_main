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
    # балл поставщика на карточке — реальный (по supplier_id); без привязки поставщика — пусто
    await api.patch(f"/procurement/requests/{r.json()['id']}", json={"stage": "nego"})
    board2 = (await api.get("/procurement/board")).json()
    nego = next(s for s in board2["stages"] if s["id"] == "nego")
    assert nego["cards"][0]["score"] == ""  # supplier_id не задан → балла нет (не заглушка «8.7»)


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
    # RBAC воронки операций: чтение — wms.read (логистика ок), запись — wms.count (логистика 403)
    assert (await api.get("/wms/ops", headers={"X-User-Roles": "logistics"})).status_code == 200
    assert (await api.post("/wms/ops", json={"title": "x"},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


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


async def test_wms_alerts(api, session):
    """Low-stock: свободный остаток 1С ниже порога → дефицит + severity."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="ZU-30A", title="ЗУ 30А", unit="шт"),
        StockItem(sku_code="ZU-30A", warehouse="Минск", qty_available=Decimal(8),
                  qty_reserved=Decimal(6), cost=Decimal(760)),
        Sku(code="AKB-225", title="АКБ 225", unit="шт"),
        StockItem(sku_code="AKB-225", warehouse="Минск", qty_available=Decimal(0),
                  qty_reserved=Decimal(0), cost=Decimal(1280)),
        # oversell в 1С: reserved > available → свободный клампится в 0, дефицит не раздувается
        Sku(code="INOX-2", title="Нерж 2", unit="т"),
        StockItem(sku_code="INOX-2", warehouse="Минск", qty_available=Decimal(3),
                  qty_reserved=Decimal(5), cost=Decimal(9800)),
    ])
    await session.commit()
    await api.post("/wms/thresholds", json={"sku_code": "ZU-30A", "warehouse": "Минск", "min_qty": 5, "reorder_qty": 20})
    await api.post("/wms/thresholds", json={"sku_code": "AKB-225", "warehouse": "Минск", "min_qty": 3, "reorder_qty": 10})
    await api.post("/wms/thresholds", json={"sku_code": "INOX-2", "warehouse": "Минск", "min_qty": 2, "reorder_qty": 4})

    al = (await api.get("/wms/alerts")).json()
    assert al["gateway"] is True
    by = {r["sku_code"]: r for r in al["rows"]}
    assert by["ZU-30A"]["free_qty"] == 2.0 and by["ZU-30A"]["deficit"] == 3.0
    assert by["ZU-30A"]["severity"] == "below_min"
    assert by["AKB-225"]["severity"] == "out_of_stock" and by["AKB-225"]["deficit"] == 3.0
    # oversell: free=max(3−5,0)=0, дефицит=2 (а не 4), severity=out_of_stock
    assert by["INOX-2"]["free_qty"] == 0.0 and by["INOX-2"]["deficit"] == 2.0
    assert by["INOX-2"]["severity"] == "out_of_stock"

    assert (await api.post("/wms/thresholds", json={"sku_code": "X"},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_cycle_count(api, session):
    """Запуск плана цикл-каунта → заполненный из 1С документ инвентаризации + сдвиг срока."""
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="ROLL-5", title="Рулон 5", unit="т"),
        StockItem(sku_code="ROLL-5", warehouse="Гомель", qty_available=Decimal(30), cost=Decimal(2100)),
    ])
    await session.commit()
    plan = (await api.post("/wms/cycle-plans",
            json={"warehouse": "Гомель", "cadence_days": 7, "next_due_date": "2020-01-01"})).json()
    det = (await api.post(f"/wms/cycle-plans/{plan['id']}/run")).json()
    assert det["number"].startswith("ИНВ-") and det["warehouse"] == "Гомель"
    assert any(line["sku_code"] == "ROLL-5" and line["expected_qty"] == 30.0 for line in det["lines"])

    p = next(p for p in (await api.get("/wms/cycle-plans")).json() if p["id"] == plan["id"])
    assert p["next_due_date"] > "2020-01-01" and p["last_run_at"]  # срок сдвинут вперёд

    assert (await api.post("/wms/cycle-plans", json={"warehouse": "X"},
                           headers={"X-User-Roles": "logistics"})).status_code == 403


async def test_wms_dashboard(api, session):
    """Дашборд: живые счётчики (очередь QC, задачи, движения сегодня, gateway)."""
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-60", "qty": 5, "warehouse": "Минск", "entity_ref": "purchase:1"},
        SimpleNamespace(session=session),
    )
    await session.commit()
    d = (await api.get("/wms/dashboard")).json()
    assert d["receipts_pending_qc"] >= 1
    assert d["gateway"] is True
    assert isinstance(d["alerts_count"], int) and isinstance(d["movements_today_in"], float)


# --------------------------------------------------------------------------- #
#  Круг 5 — тест-харднинг WMS (edge-cases; падают на старом/откаченном коде)
# --------------------------------------------------------------------------- #
async def test_wms_accept_idempotent_exactly_one_mirror(api, session):
    """QC-гейт: pending_qc БЕЗ движения; accept → ровно одно зеркало; повтор accept не плодит.

    Падал бы на старом коде, если убрать идемпотентность accept (3 accept → 3 движения =
    тройной фантомный приход на свободный остаток — деньго-баг) или гейт qc-после-accept.
    """
    from types import SimpleNamespace

    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-132", "qty": 10, "warehouse": "Брест", "entity_ref": "purchase:51"},
        SimpleNamespace(session=session),
    )
    await session.commit()
    rid = (await api.get("/wms/receipts?status=pending_qc")).json()[0]["id"]
    line = (await api.get(f"/wms/receipts/{rid}")).json()["lines"][0]
    # гейт: до accept движения прихода нет
    assert (await api.get("/wms/movements?reason=receipt")).json() == []

    await api.post(f"/wms/receipts/{rid}/qc",
                   json={"decisions": [{"line_id": line["id"], "accepted_qty": 8, "rejected_qty": 2}]})
    assert (await api.post(f"/wms/receipts/{rid}/accept")).json()["status"] == "accepted"

    # три повторных accept не должны добавить ни одного лишнего движения
    for _ in range(3):
        assert (await api.post(f"/wms/receipts/{rid}/accept")).status_code == 200
    mv = [m for m in (await api.get("/wms/movements?reason=receipt")).json()
          if m["doc_ref"].startswith("ПРМ-")]
    assert len(mv) == 1 and mv[0]["qty"] == 8.0  # ровно одно зеркало по принятым 8 (брак 2 вне)

    # QC после проведения запрещён (статус уже accepted, не pending_qc)
    assert (await api.post(f"/wms/receipts/{rid}/qc",
                           json={"decisions": []})).status_code == 409


async def test_wms_alerts_emit_oversell_clamp_and_dedup(api, session):
    """low-stock на ЭМИТ-пути: oversell 1С клампится в 0 (дефицит не раздут) + дедуп порогов.

    Падал бы на старом коде без max(avail−res,0): free=−2 → deficit=6 (раздут) в payload,
    который кормит Закупки = перезаказ за деньги. И без дедупа — два события на одну пару.
    """
    from decimal import Decimal

    from sqlalchemy import select

    from core.domain.models import OutboxEvent, Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="INOX-2", title="Нерж 2", unit="т"),
        # oversell: reserved(5) > available(3) → свободный остаток отрицателен до клампа
        StockItem(sku_code="INOX-2", warehouse="Минск", qty_available=Decimal(3),
                  qty_reserved=Decimal(5), cost=Decimal(9800)),
    ])
    await session.commit()
    # два активных порога на одну (sku,warehouse): первый по id выигрывает пару (min 4, reorder 10)
    await api.post("/wms/thresholds", json={"sku_code": "INOX-2", "warehouse": "Минск", "min_qty": 4, "reorder_qty": 10})
    await api.post("/wms/thresholds", json={"sku_code": "INOX-2", "warehouse": "Минск", "min_qty": 6, "reorder_qty": 20})

    r = await api.post("/wms/alerts/emit")
    assert r.json() == {"emitted": 1, "gateway": True}  # дедуп: одно событие, не два
    evs = [e for e in (await session.execute(select(OutboxEvent))).scalars().all()
           if e.event_type == "wms.stock.low"]
    assert len(evs) == 1
    p = evs[0].payload
    assert p["free_qty"] == 0.0  # клампнут в 0, не −2
    assert p["deficit"] == 4.0   # 4 − 0 (НЕ 6); первый порог пары выиграл
    assert p["reorder_qty"] == 10.0 and p["severity"] == "out_of_stock"


async def test_wms_ops_funnel_rbac(api):
    """RBAC складской воронки (крит-фикс круга 2): запись требует wms.count, чужой модуль — 403.

    Падал бы на старом коде, где /ops,/board,POST,PATCH были БЕЗ require_permission:
    PATCH чужой роли вернул бы 404 (дошёл до хендлера), а не 403.
    """
    log = {"X-User-Roles": "logistics"}  # wms.read, без wms.count
    # чтение воронки роли склада доступно
    assert (await api.get("/wms/ops", headers=log)).status_code == 200
    assert (await api.get("/wms/board", headers=log)).status_code == 200
    # запись (создание/смена стадии) — только wms.count → 403 даже до обращения к данным
    assert (await api.post("/wms/ops", json={"title": "x"}, headers=log)).status_code == 403
    assert (await api.patch("/wms/ops/999999", json={"stage": "qc"}, headers=log)).status_code == 403
    # роль без доступа к модулю склада — 403 даже на чтение (гейт доступа к модулю)
    assert (await api.get("/wms/ops", headers={"X-User-Roles": "sales"})).status_code == 403


async def test_wms_reconciliation_does_not_overwrite_1c(api, session):
    """Сверка отдаёт diff, но НЕ перетирает 1С (истина склада): StockItem не меняется.

    Падал бы, если бы сверка писала обратно в зеркало 1С (синхронизировала остаток),
    нарушив инвариант «1С = истина, фаза 1» — данные/деньги.
    """
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add(Sku(code="LFP-24-200", title="LFP 24-200", unit="шт"))
    item = StockItem(sku_code="LFP-24-200", warehouse="Минск",
                     qty_available=Decimal(14), cost=Decimal(1850))
    session.add(item)
    await session.commit()
    await api.post("/wms/receipt", json={"sku_code": "LFP-24-200", "qty": 10, "warehouse": "Минск"})

    rec = (await api.get("/wms/reconciliation")).json()
    row = next(r for r in rec["rows"] if r["sku_code"] == "LFP-24-200")
    assert row["wms_qty"] == 10.0 and row["onec_qty"] == 14.0 and row["diff"] == -4.0

    # 1С-зеркало осталось 14 — сверка ничего не записала обратно
    await session.refresh(item)
    assert float(item.qty_available) == 14.0


async def test_wms_cycle_count_correcting_movement_valued(api, session):
    """Цикл-каунт: расхождение пересчёта → корректирующее движение + деньго-оценка (str-точность).

    Падал бы, если проведение перестанет писать adjustment-движение (теневой остаток не
    сойдётся) или сломается денежная оценка расхождения.
    """
    from decimal import Decimal

    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="ROLL-8", title="Рулон 8", unit="т"),
        StockItem(sku_code="ROLL-8", warehouse="Гомель",
                  qty_available=Decimal(30), cost=Decimal("1850.50")),
    ])
    await session.commit()
    plan = (await api.post("/wms/cycle-plans",
            json={"warehouse": "Гомель", "cadence_days": 7, "next_due_date": "2020-01-01"})).json()
    doc = (await api.post(f"/wms/cycle-plans/{plan['id']}/run")).json()
    line = next(line for line in doc["lines"] if line["sku_code"] == "ROLL-8")
    await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 27})  # недостача 3
    assert (await api.post(f"/wms/inventory/{doc['id']}/complete")).json()["status"] == "done"

    # корректирующее движение в журнал WMS (не в 1С)
    adj = next(m for m in (await api.get("/wms/movements?reason=adjustment")).json()
               if m["sku_code"] == "ROLL-8")
    assert adj["kind"] == "out" and adj["qty"] == 3.0 and adj["doc_ref"] == doc["number"]
    # деньго-оценка расхождения: −3 × 1850.50 = −5551.5 (точно, через Decimal(str()))
    det = (await api.get(f"/wms/inventory/{doc['id']}")).json()
    dl = next(line for line in det["lines"] if line["sku_code"] == "ROLL-8")
    assert dl["variance"] == -3.0 and dl["variance_value"] == -5551.5
    assert det["summary"]["shortage_value"] == -5551.5


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
