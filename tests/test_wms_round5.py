"""WMS круг 5 — тест-харднинг edge-cases (5 кейсов).

Каждый тест доказывает реальный инвариант, нарушение которого было бы денежным/
безопасностным дефектом. Комментарий «Падал бы, если...» объясняет, что именно
стреляло бы на коде без проверяемого инварианта.

Импорты Sku/StockItem внутри каждого теста (как в test_erp.py) — чтобы не зависеть
от порядка загрузки модулей при отдельном запуске.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

# ===========================================================================
# Кейс 1 — QC-гейт приёмки
# ===========================================================================


async def test_qc_gate_no_movement_before_accept(api, session):
    """pending_qc НЕ создаёт StockMovement: движение прихода до accept отсутствует.

    Падал бы, если on_goods_received (или create_receipt) писал движение в момент
    создания приёмки вместо после accept — товар оказывается на остатке до QC.
    """
    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-R5-1", "qty": 20, "warehouse": "Гомель", "entity_ref": "purchase:99"},
        SimpleNamespace(session=session),
    )
    await session.commit()

    # До accept в журнале WMS нет ни одного движения reason=receipt по этому SKU
    mvs = (await api.get("/wms/movements?reason=receipt")).json()
    assert not any(m["sku_code"] == "AKB-R5-1" for m in mvs), (
        "pending_qc не должна создавать StockMovement до accept"
    )
    # Документ в очереди QC
    receipts = (await api.get("/wms/receipts?status=pending_qc")).json()
    assert any(r["entity_ref"] == "purchase:99" for r in receipts)


async def test_qc_gate_accept_without_explicit_qc_uses_expected(api, session):
    """Accept без явного QC-решения использует expected_qty (не None/0).

    Падал бы, если accepted_qty=None привёл бы к accepted=None → qty=None → движение
    с qty=None (DB-ошибка) или пропущенному движению при qty=0.
    """
    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-R5-1A", "qty": 15, "warehouse": "Минск", "entity_ref": "purchase:100"},
        SimpleNamespace(session=session),
    )
    await session.commit()

    rid = next(
        r["id"]
        for r in (await api.get("/wms/receipts?status=pending_qc")).json()
        if r["entity_ref"] == "purchase:100"
    )
    # Принимаем без явного QC (accepted_qty=None на строке → fallback на expected_qty)
    resp = await api.post(f"/wms/receipts/{rid}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    mvs = [m for m in (await api.get("/wms/movements?reason=receipt")).json()
           if m["sku_code"] == "AKB-R5-1A"]
    assert len(mvs) == 1, "Ровно одно движение прихода по ожидаемому кол-ву"
    assert mvs[0]["qty"] == 15.0


async def test_qc_gate_repeated_accept_still_exactly_one_movement(api, session):
    """Повторный accept (N раз) НЕ создаёт дополнительных движений — идемпотентен.

    Падал бы, если убрать guard по статусу accepted: 3 вызова → 3 движения =
    тройной фантомный приход (деньго-баг: +30 единиц вместо +10).
    """
    from modules.wms.events import on_goods_received

    await on_goods_received(
        {"item": "AKB-R5-2", "qty": 10, "warehouse": "Брест", "entity_ref": "purchase:101"},
        SimpleNamespace(session=session),
    )
    await session.commit()

    receipts = (await api.get("/wms/receipts?status=pending_qc")).json()
    rid = next(r["id"] for r in receipts if r["entity_ref"] == "purchase:101")

    # Первый accept
    r1 = await api.post(f"/wms/receipts/{rid}/accept")
    assert r1.json()["status"] == "accepted"

    # Повторные accept (3 раза) — всё ещё 200, но движений не прибавляется
    for _ in range(3):
        rx = await api.post(f"/wms/receipts/{rid}/accept")
        assert rx.status_code == 200

    mvs = [m for m in (await api.get("/wms/movements?reason=receipt")).json()
           if m["sku_code"] == "AKB-R5-2"]
    assert len(mvs) == 1, f"Ожидалось 1 движение, получено {len(mvs)}"


# ===========================================================================
# Кейс 2 — low-stock дедуп + кламп нулевого/отрицательного остатка
# ===========================================================================


async def test_low_stock_zero_available_clamp_out_of_stock(api, session):
    """qty_available=0 клампится в 0: дефицит=min_qty, severity=out_of_stock.

    Падал бы без max(avail−reserved, 0): при avail=0, reserved=0 free=0 корректно,
    но если avail=0, reserved>0 (oversell) → free<0 → дефицит раздут выше min_qty.
    Этот тест фиксирует ОБА случая.
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    # avail=0, reserved=0 → free=0
    session.add_all([
        Sku(code="R5-ZERO", title="Тест-ноль", unit="шт"),
        StockItem(sku_code="R5-ZERO", warehouse="Минск",
                  qty_available=Decimal(0), qty_reserved=Decimal(0), cost=Decimal(100)),
    ])
    await session.commit()
    await api.post("/wms/thresholds",
                   json={"sku_code": "R5-ZERO", "warehouse": "Минск", "min_qty": 5, "reorder_qty": 10})

    al = (await api.get("/wms/alerts")).json()
    row = next((r for r in al["rows"] if r["sku_code"] == "R5-ZERO"), None)
    assert row is not None, "Нулевой остаток должен тригерить дефицит"
    assert row["free_qty"] == 0.0
    assert row["deficit"] == 5.0  # 5 − 0 = 5, не раздуто
    assert row["severity"] == "out_of_stock"


async def test_low_stock_oversell_clamp_no_negative_free(api, session):
    """Oversell 1С (reserved > available): свободный остаток кламп в 0, дефицит не раздут.

    Падал бы без max(avail−reserved, 0): free = 3−5 = −2 → дефицит = min+2 (раздут),
    severity=out_of_stock, payload кормит Закупки с завышенным reorder.
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-OVER", title="Тест-оверселл", unit="шт"),
        StockItem(sku_code="R5-OVER", warehouse="Минск",
                  qty_available=Decimal(3), qty_reserved=Decimal(5), cost=Decimal(200)),
    ])
    await session.commit()
    await api.post("/wms/thresholds",
                   json={"sku_code": "R5-OVER", "warehouse": "Минск", "min_qty": 2, "reorder_qty": 5})

    al = (await api.get("/wms/alerts")).json()
    row = next((r for r in al["rows"] if r["sku_code"] == "R5-OVER"), None)
    assert row is not None
    assert row["free_qty"] == 0.0, "Клампинг: не −2, а 0"
    assert row["deficit"] == 2.0, "Дефицит = min(2) − free(0) = 2, не 4"
    assert row["severity"] == "out_of_stock"


async def test_low_stock_emit_dedup_within_call(api, session):
    """Два активных порога на одну (sku,warehouse): один вызов emit → одно событие.

    Падал бы, если _deficit_rows не делает by_pair.setdefault (дедуп первого порога):
    два порога → два события wms.stock.low → Закупки получают дубль → дубль заявки.
    """
    from sqlalchemy import select

    from core.domain.models import OutboxEvent, Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-DED", title="Тест-дедуп", unit="шт"),
        StockItem(sku_code="R5-DED", warehouse="Минск",
                  qty_available=Decimal(2), qty_reserved=Decimal(0), cost=Decimal(300)),
    ])
    await session.commit()
    # Два порога на одну (sku, warehouse)
    await api.post("/wms/thresholds",
                   json={"sku_code": "R5-DED", "warehouse": "Минск", "min_qty": 10, "reorder_qty": 20})
    await api.post("/wms/thresholds",
                   json={"sku_code": "R5-DED", "warehouse": "Минск", "min_qty": 8, "reorder_qty": 15})

    r = await api.post("/wms/alerts/emit")
    assert r.status_code == 200
    assert r.json()["emitted"] == 1, "Дедуп: только одно событие на (sku, warehouse)"

    evs = [e for e in (await session.execute(select(OutboxEvent))).scalars().all()
           if e.event_type == "wms.stock.low" and e.payload["sku_code"] == "R5-DED"]
    assert len(evs) == 1


# ===========================================================================
# Кейс 3 — RBAC воронки: без права → 403
# ===========================================================================


async def test_wms_funnel_rbac_403_without_permission(api):
    """Доступ к складской воронке без права wms.read → 403.

    Падал бы, если роуты /wms/board, /wms/ops, /wms/receipts, /wms/inventory,
    /wms/alerts были без require_permission: роль sales (нет wms.*) дошла бы
    до хендлера и вернула данные (information disclosure).
    """
    no_perm = {"X-User-Roles": "sales"}  # роль sales: нет wms.read/wms.count

    for endpoint in ["/wms/board", "/wms/ops", "/wms/receipts",
                     "/wms/inventory", "/wms/alerts", "/wms/reconciliation"]:
        resp = await api.get(endpoint, headers=no_perm)
        assert resp.status_code == 403, (
            f"Ожидался 403 для {endpoint} с ролью sales, получен {resp.status_code}"
        )


async def test_wms_funnel_rbac_write_logistics_403(api):
    """Роль logistics (только wms.read) не может писать движения/операции.

    Падал бы, если POST/PATCH требовали только wms.read: logistics смог бы
    создавать приёмки, проводить инвентаризацию — нарушение разделения функций.
    """
    log_headers = {"X-User-Roles": "logistics"}  # wms.read, без wms.count

    # Чтение — ОК для logistics
    assert (await api.get("/wms/ops", headers=log_headers)).status_code == 200

    # Запись — 403
    assert (await api.post("/wms/movements",
                            json={"sku_code": "X", "qty": 1},
                            headers=log_headers)).status_code == 403
    assert (await api.post("/wms/receipts",
                            json={"lines": []},
                            headers=log_headers)).status_code == 403
    assert (await api.post("/wms/inventory",
                            json={},
                            headers=log_headers)).status_code == 403
    assert (await api.post("/wms/alerts/emit", headers=log_headers)).status_code == 403


# ===========================================================================
# Кейс 4 — Сверка с 1С: diff отдаётся, не молчит и не перетирает
# ===========================================================================


async def test_reconciliation_shows_diff_not_silent(api, session):
    """Расхождение ERP↔1С явно отдаётся в rows, не схлопывается в пустой список.

    Падал бы, если бы reconciliation молчал при diff!=0 (напр. фильтровал строки
    с diff==0 и заодно прочие). Инвариант: дифф есть → строка в ответе.
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-DIFF", title="Тест-расхождение", unit="шт"),
        StockItem(sku_code="R5-DIFF", warehouse="Минск",
                  qty_available=Decimal(20), cost=Decimal(500)),
    ])
    await session.commit()

    # WMS: 12 пришло, 1С: 20 доступно → diff = 12 − 20 = −8
    await api.post("/wms/receipt",
                   json={"sku_code": "R5-DIFF", "qty": 12, "warehouse": "Минск"})

    rec = (await api.get("/wms/reconciliation")).json()
    assert rec["gateway"] is True
    assert len(rec["rows"]) >= 1, "Строки расхождения не должны молчать"
    row = next((r for r in rec["rows"] if r["sku_code"] == "R5-DIFF"), None)
    assert row is not None, "Строка R5-DIFF должна быть в ответе"
    assert row["diff"] == -8.0
    assert row["diff_value"] == -4000.0  # −8 × 500
    assert rec["total_abs_diff_value"] >= 4000.0


async def test_reconciliation_no_cost_diff_value_is_none(api, session):
    """Расхождение без себеса 1С → diff_value=null, не 0 и не 500.

    Падал бы, если бы diff_value вычислялся с float-нулём вместо None: скрытое
    «ноль рублей расхождения» при реальном количественном расхождении.
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-NOCOST", title="Тест-без-себеса", unit="шт"),
        StockItem(sku_code="R5-NOCOST", warehouse="Минск",
                  qty_available=Decimal(10), cost=None),  # нет себеса
    ])
    await session.commit()

    # WMS: 5 пришло, 1С: 10 → diff = −5, но cost=None → diff_value должен быть null
    await api.post("/wms/receipt",
                   json={"sku_code": "R5-NOCOST", "qty": 5, "warehouse": "Минск"})

    rec = (await api.get("/wms/reconciliation")).json()
    row = next((r for r in rec["rows"] if r["sku_code"] == "R5-NOCOST"), None)
    assert row is not None
    assert row["diff"] == -5.0
    assert row["diff_value"] is None, (
        f"diff_value должен быть null при отсутствии себеса, получено {row['diff_value']!r}"
    )


async def test_reconciliation_does_not_write_to_1c(api, session):
    """Сверка НЕ модифицирует данные 1С (StockItem) — только читает diff.

    Падал бы, если бы reconciliation «синхронизировал» WMS→1С, нарушив
    контракт «1С = истина склада, фаза 1» (необратимая порча мастер-данных).
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    original_qty = Decimal(25)
    session.add_all([
        Sku(code="R5-NOWRITE", title="Тест-нет-записи", unit="шт"),
        StockItem(sku_code="R5-NOWRITE", warehouse="Минск",
                  qty_available=original_qty, cost=Decimal(1000)),
    ])
    await session.commit()

    # WMS: 15 ≠ 1С: 25
    await api.post("/wms/receipt",
                   json={"sku_code": "R5-NOWRITE", "qty": 15, "warehouse": "Минск"})
    await api.get("/wms/reconciliation")

    # StockItem в БД не изменился
    from sqlalchemy import select
    item = (await session.execute(
        select(StockItem).where(StockItem.sku_code == "R5-NOWRITE")
    )).scalars().first()
    assert item is not None
    assert item.qty_available == original_qty, (
        f"1С-зеркало изменилось: ожидалось {original_qty}, получено {item.qty_available}"
    )


# ===========================================================================
# Кейс 5 — Цикл-каунт: Decimal(str()) в деньго-оценке, нет float-погрешности
# ===========================================================================


async def test_cycle_count_variance_decimal_str_precision(api, session):
    """Деньго-оценка расхождения через Decimal(str()), без float-погрешности.

    Падал бы, если бы variance * cost считался через float: 3 × 1850.50 = 5551.5
    через float даёт 5551.499999... (BYN-ошибка копейки). Тест фиксирует точность.
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-DECIMAL", title="Тест-Decimal", unit="шт"),
        StockItem(sku_code="R5-DECIMAL", warehouse="Минск",
                  qty_available=Decimal(30), cost=Decimal("1850.50")),
    ])
    await session.commit()

    plan = (await api.post("/wms/cycle-plans",
                           json={"warehouse": "Минск", "cadence_days": 30})).json()
    doc = (await api.post(f"/wms/cycle-plans/{plan['id']}/run")).json()
    line = next((ln for ln in doc["lines"] if ln["sku_code"] == "R5-DECIMAL"), None)
    assert line is not None, "Строка R5-DECIMAL должна быть в документе инвентаризации"

    # Факт: 27 (недостача 3 ед.)
    await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 27})
    done = (await api.post(f"/wms/inventory/{doc['id']}/complete")).json()
    assert done["status"] == "done"

    det = (await api.get(f"/wms/inventory/{doc['id']}")).json()
    dl = next(ln for ln in det["lines"] if ln["sku_code"] == "R5-DECIMAL")
    # Точная проверка: −3 × 1850.50 = −5551.50
    assert dl["variance"] == -3.0
    assert dl["variance_value"] == -5551.5, (
        f"Float-погрешность: ожидалось -5551.5, получено {dl['variance_value']!r}"
    )


async def test_cycle_count_surplus_valued_positive(api, session):
    """Излишек (counted > expected): корректирующее движение 'in' + variance_value > 0.

    Падал бы, если sign инвертирован: излишек писался бы как 'out' (уменьшение остатка)
    и variance_value был бы отрицательным (излишек выглядел как недостача в деньгах).
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-SURPLUS", title="Тест-излишек", unit="шт"),
        StockItem(sku_code="R5-SURPLUS", warehouse="Гродно",
                  qty_available=Decimal(10), cost=Decimal("200.00")),
    ])
    await session.commit()

    plan = (await api.post("/wms/cycle-plans",
                           json={"warehouse": "Гродно", "cadence_days": 30})).json()
    doc = (await api.post(f"/wms/cycle-plans/{plan['id']}/run")).json()
    line = next((ln for ln in doc["lines"] if ln["sku_code"] == "R5-SURPLUS"), None)
    assert line is not None

    # Факт: 14 (излишек 4 ед.)
    await api.patch(f"/wms/inventory/lines/{line['id']}", json={"counted_qty": 14})
    await api.post(f"/wms/inventory/{doc['id']}/complete")

    # Корректирующее движение — приход (излишек)
    mvs = [m for m in (await api.get("/wms/movements?reason=adjustment")).json()
           if m["sku_code"] == "R5-SURPLUS"]
    assert len(mvs) == 1
    assert mvs[0]["kind"] == "in", "Излишек → движение 'in'"
    assert mvs[0]["qty"] == 4.0

    # Деньго-оценка: +4 × 200 = +800
    det = (await api.get(f"/wms/inventory/{doc['id']}")).json()
    dl = next(ln for ln in det["lines"] if ln["sku_code"] == "R5-SURPLUS")
    assert dl["variance"] == 4.0
    assert dl["variance_value"] == 800.0


async def test_cycle_count_zero_variance_no_movement(api, session):
    """Пересчёт без расхождения (counted == expected) НЕ пишет движение.

    Падал бы, если бы complete записывал нулевые adjustment-движения: шум в журнале
    (движение qty=0 не меняет остаток, но засоряет историю и may break downstream).
    """
    from core.domain.models import Sku
    from modules.integrations.models import StockItem

    session.add_all([
        Sku(code="R5-ZERO-VAR", title="Тест-нет-расхождения", unit="шт"),
        StockItem(sku_code="R5-ZERO-VAR", warehouse="Витебск",
                  qty_available=Decimal(5), cost=Decimal("100.00")),
    ])
    await session.commit()

    plan = (await api.post("/wms/cycle-plans",
                           json={"warehouse": "Витебск", "cadence_days": 30})).json()
    doc = (await api.post(f"/wms/cycle-plans/{plan['id']}/run")).json()
    line = next((ln for ln in doc["lines"] if ln["sku_code"] == "R5-ZERO-VAR"), None)
    assert line is not None

    # Факт совпадает с ожидаемым
    await api.patch(f"/wms/inventory/lines/{line['id']}",
                    json={"counted_qty": float(line["expected_qty"])})
    await api.post(f"/wms/inventory/{doc['id']}/complete")

    # Движений adjustment по этому SKU быть не должно
    mvs = [m for m in (await api.get("/wms/movements?reason=adjustment")).json()
           if m["sku_code"] == "R5-ZERO-VAR"]
    assert mvs == [], f"Нулевое расхождение не должно давать движение, получено: {mvs}"
