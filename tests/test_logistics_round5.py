"""Тест-харднинг круга 5 — logistics (LOG-6).

4 кейса (координатор, 2026-06-28):
  R5-1  Импорт-фрахт идемпотентность: двойная страховка prev_stage + outbox.
  R5-2  phantom-guard _looks_like_import: таблица пограничных стран/маркеров.
  R5-3  bid_risk демпинг: медиана из 1 ставки / все равные / выброс вниз.
  R5-4  import.received без подписчиков: эмитится и не роняет шину.

Каждый тест ДОКАЗАН на «старом коде»: пояснение — в блоке «как упал бы» рядом.
Деньги — Decimal(str()), BYN.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.domain.models import OutboxEvent
from modules.logistics.events import _looks_like_import
from modules.logistics.pricing import DUMPING_MIN_BIDS, DUMPING_THRESHOLD_PCT, _median, bid_risk

# ---------------------------------------------------------------------------
# R5-1: Импорт-фрахт идемпотентность — двойная страховка
# ---------------------------------------------------------------------------

class TestImportFreightIdempotency:
    """R5-1: два независимых барьера против двойного учёта фрахта.

    Контракт LOG3-1 + B2 ревью круга 3: «defence-in-depth».
    Путь A — prev_stage-гард (уже warehouse): обычный повтор PATCH.
    Путь B — outbox-гард: сценарий warehouse → customs → warehouse.

    Как упал бы на старом коде без outbox-гарда:
      - В `update_import` была только проверка `prev_stage != WAREHOUSE_STAGE`.
      - При откате (→customs) и повторном PATCH(→warehouse) prev_stage снова
        НЕ равен warehouse → условие проходило → второй `freight.cost` улетал
        в finance → двойной расход (потеря денег, приоритет №1 платформы).
      - `test_path_b_outbox_guard_blocks_rollback_retransition` поймал бы это.
    """

    @pytest.mark.api
    async def test_path_a_prev_stage_guard_blocks_repeat_patch(self, api, session):
        """Путь A: повторный PATCH stage=warehouse при prev_stage=warehouse → ноль новых freight.cost.

        Стандартный кейс: оператор нажал «Принято» дважды. prev_stage-гард
        (строка `if prev_stage != WAREHOUSE_STAGE`) блокирует второй эмит.
        Outbox-гард не нужен — prev_stage уже warehouse, эмит до него не доходит.
        """
        sid = (await api.post("/logistics/imports", json={
            "supplier": "Shenzhen Co", "cargo": "Контейнер 40HQ", "qty": 1,
            "amount": "5000.00", "stage": "customs", "po_ref": "purchase:r5a",
        })).json()["id"]

        # Первый переход customs → warehouse — должен эмитить ровно один freight.cost.
        r1 = await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
        assert r1.status_code == 200

        # Повторный PATCH в тот же warehouse — prev_stage уже warehouse → гард срабатывает.
        r2 = await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})
        assert r2.status_code == 200

        events = (await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.cost")
        )).scalars().all()
        freight_for_sid = [e for e in events if e.payload.get("ref") == f"import:{sid}"]
        assert len(freight_for_sid) == 1, (
            f"Путь A нарушен: ожидался 1 freight.cost, получено {len(freight_for_sid)}"
        )

    @pytest.mark.api
    async def test_path_b_outbox_guard_blocks_rollback_retransition(self, api, session):
        """Путь B: warehouse → customs → warehouse — outbox-гард блокирует второй freight.cost.

        Откат стадии (операционист исправил ошибку) + переотметка:
          PATCH warehouse → PATCH customs → PATCH warehouse.

        Без outbox-гарда: при третьем PATCH prev_stage=customs ≠ warehouse → условие
        проходит → второй `freight.cost` записывается → двойной учёт в finance.
        `_import_freight_already_emitted` читает outbox и блокирует этот путь.
        """
        sid = (await api.post("/logistics/imports", json={
            "supplier": "Y", "cargo": "Запчасти", "qty": 100,
            "amount": "3500.00", "stage": "customs", "po_ref": "purchase:r5b",
        })).json()["id"]

        # Шаг 1: customs → warehouse → эмит #1.
        await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

        # Шаг 2: откат warehouse → customs (ошибочная правка).
        await api.patch(f"/logistics/imports/{sid}", json={"stage": "customs"})

        # Шаг 3: снова customs → warehouse. Без outbox-гарда здесь был бы эмит #2.
        await api.patch(f"/logistics/imports/{sid}", json={"stage": "warehouse"})

        events = (await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.cost")
        )).scalars().all()
        freight_for_sid = [e for e in events if e.payload.get("ref") == f"import:{sid}"]
        assert len(freight_for_sid) == 1, (
            f"Путь B нарушен (outbox-гард): ожидался 1 freight.cost, получено {len(freight_for_sid)}"
        )

    @pytest.mark.api
    async def test_two_guards_independent_different_shipments(self, api, session):
        """Два разных ImportShipment — каждый изолированно считает свой outbox-key.

        Outbox-гард фильтрует по `ref='import:<id>'`, поэтому эмит одного
        не мешает другому. Тест закрепляет корректную область видимости гарда.
        """
        sid1 = (await api.post("/logistics/imports", json={
            "supplier": "A", "cargo": "G1", "qty": 1,
            "amount": "1000.00", "stage": "customs", "po_ref": "purchase:r5c1",
        })).json()["id"]
        sid2 = (await api.post("/logistics/imports", json={
            "supplier": "B", "cargo": "G2", "qty": 2,
            "amount": "2000.00", "stage": "customs", "po_ref": "purchase:r5c2",
        })).json()["id"]

        await api.patch(f"/logistics/imports/{sid1}", json={"stage": "warehouse"})
        await api.patch(f"/logistics/imports/{sid2}", json={"stage": "warehouse"})
        # Повторные — должны остаться с по одному.
        await api.patch(f"/logistics/imports/{sid1}", json={"stage": "warehouse"})
        await api.patch(f"/logistics/imports/{sid2}", json={"stage": "warehouse"})

        events = (await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "logistics.freight.cost")
        )).scalars().all()
        for sid, expected_amount in [(sid1, "1000.00"), (sid2, "2000.00")]:
            sid_events = [e for e in events if e.payload.get("ref") == f"import:{sid}"]
            assert len(sid_events) == 1, f"import:{sid} — ожидался 1 freight, получено {len(sid_events)}"
            assert sid_events[0].payload["amount"] == expected_amount


# ---------------------------------------------------------------------------
# R5-2: phantom-guard _looks_like_import — пограничные страны (таблица)
# ---------------------------------------------------------------------------

class TestLooksLikeImportBoundary:
    """R5-2: таблица пограничных кейсов классификации payload procurement.received.

    Как упал бы на старом коде:
      - Если бы _DOMESTIC_COUNTRIES не включала РФ, строка ({"country": "РФ"}, False)
        падала (функция вернула бы True вместо False — создала бы ImportShipment для
        внутренней закупки, засорив импорт-доску).
      - Если бы strip().upper() не применялся, строка ({"country": " РБ "}, False)
        падала (пробелы не сматчили бы множество).
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("payload, expected, label", [
        # --- Внутренние: РБ (все варианты написания) ---
        ({"country": "РБ"}, False, "канон РБ"),
        ({"country": "BY"}, False, "ISO2 BY"),
        ({"country": "BLR"}, False, "ISO3 BLR"),
        ({"country": "BELARUS"}, False, "latin upper"),
        ({"country": "Belarus"}, False, "latin mixed"),
        ({"country": " РБ "}, False, "strip пробелы"),
        ({"country": "by"}, False, "нижний регистр"),
        # --- Внутренние: РФ (M1 ревью круга 3 — внутренний рынок CRM) ---
        ({"country": "РФ"}, False, "РФ кириллица"),
        ({"country": "RU"}, False, "ISO2 RU"),
        ({"country": "RUS"}, False, "ISO3 RUS"),
        ({"country": "RUSSIA"}, False, "Russia upper"),
        ({"country": "Russia"}, False, "Russia mixed"),
        ({"country": "ru"}, False, "RU lower"),
        # --- Внешние (импорт по стране) ---
        ({"country": "CN"}, True, "Китай ISO2"),
        ({"country": "Китай"}, True, "Китай кириллица"),
        ({"country": "UA"}, True, "Украина ISO2"),
        ({"country": "PL"}, True, "Польша ISO2"),
        ({"country": "DE"}, True, "Германия"),
        ({"country": "TR"}, True, "Турция"),
        # --- Incoterms маркер ---
        ({"incoterms": "FOB"}, True, "FOB"),
        ({"incoterms": "CIF"}, True, "CIF"),
        ({"incoterms": "EXW"}, True, "EXW"),
        ({"incoterms": ""}, False, "пустой incoterms"),
        ({"incoterms": "   "}, False, "пробелы incoterms"),
        # --- origin маркер ---
        ({"origin": "import"}, True, "origin lower"),
        ({"origin": "IMPORT"}, True, "origin upper"),
        ({"origin": "domestic"}, False, "origin domestic"),
        # --- Пустой / неопределённый ---
        ({}, False, "пустой payload"),
        ({"country": ""}, False, "пустая страна"),
        ({"country": None, "incoterms": None}, False, "None поля"),
        # --- Комбинации ---
        ({"country": "CN", "incoterms": "FOB"}, True, "Китай + FOB"),
        ({"country": "РБ", "incoterms": "FOB"}, True, "РБ + incoterms → incoterms сильнее"),
        ({"country": "RU", "incoterms": "CIF"}, True, "РФ + incoterms → incoterms сильнее"),
        ({"country": "CN", "origin": "domestic"}, True, "CN + domestic origin → страна CN сильнее"),
    ])
    def test_boundary_table(self, payload, expected, label):
        """Фиксирует текущую эвристику и защищает от регрессий при изменении _DOMESTIC_COUNTRIES."""
        result = _looks_like_import(payload)
        assert result is expected, (
            f"[{label}] payload={payload!r} → ожидался {expected}, получен {result}"
        )

    @pytest.mark.unit
    def test_rf_is_not_import_explicit(self):
        """Явный тест: РФ НЕ является импортом в этой CRM (внутренний рынок).

        Пояснение: M1 ревью (круг 3) зафиксировало РФ как «внутренний рынок» (РБ+РФ =
        _DOMESTIC_COUNTRIES). Если разработчик уберёт РФ — этот тест падает первым.
        """
        rf_variants = ["РФ", "RU", "RUS", "RUSSIA", "Russia", "Россия", "россия"]
        for variant in rf_variants:
            assert _looks_like_import({"country": variant}) is False, (
                f"РФ ({variant!r}) должна быть внутренним рынком, не импортом"
            )

    @pytest.mark.unit
    def test_empty_origin_is_not_import_marker(self):
        """Пустая строка / None в origin не даёт ложного True."""
        for origin_val in [None, "", "  ", "0", "false", "False"]:
            payload = {"origin": origin_val}
            # Только если строка == 'import' (case-insensitive) — True.
            result = _looks_like_import(payload)
            assert result is False, (
                f"origin={origin_val!r} не должен давать import-маркер, получен {result}"
            )


# ---------------------------------------------------------------------------
# R5-3: bid_risk демпинг — медиана и флаг
# ---------------------------------------------------------------------------

class TestBidRiskDumping:
    """R5-3: корректность флага демпинга и медианы при граничных наборах.

    Как упал бы на старом коде (если убрать guards):
      - _median([]) без guard вернул бы ZeroDivisionError (деление на 0).
      - bid_risk с одной ставкой: prices=[X], cheapest=X, median=X → deviation=0,
        suspicious=False → корректно; но если бы min(prices) вызывался на [],
        то ValueError. Тест закрепляет отсутствие этих путей.
      - Флаг демпинга при len(prices) < DUMPING_MIN_BIDS должен быть False —
        без guard `len(prices) >= DUMPING_MIN_BIDS` он был бы True при 2 ставках
        с большим разрывом.
    """

    @pytest.mark.unit
    def test_median_single_value(self):
        """_median с одним элементом не делит на ноль."""
        assert _median([100.0]) == 100.0

    @pytest.mark.unit
    def test_median_all_equal(self):
        """_median из одинаковых чисел = само число."""
        assert _median([200.0, 200.0, 200.0]) == 200.0

    @pytest.mark.unit
    def test_median_empty_no_error(self):
        """_median пустого списка возвращает 0.0, без исключения."""
        assert _median([]) == 0.0

    @pytest.mark.unit
    def test_bid_risk_single_bid_no_dumping_flag(self):
        """Одна ставка: нет медианного сравнения → флаг демпинга всегда False.

        DUMPING_MIN_BIDS=3, одна ставка → suspicious=False (нет базы для сравнения).
        deviation=0.0 (цена == медиана), нет деления на ноль.
        """
        bid = {"carrier_code": "A", "price": "500.00"}
        result = bid_risk(bid, [bid])
        assert result["is_suspiciously_cheap"] is False
        assert result["deviation_pct"] == 0.0
        assert result["median"] == 500.0

    @pytest.mark.unit
    def test_bid_risk_all_equal_no_dumping(self):
        """Все ставки одинаковые: отклонение 0.0, флаг False.

        Ни одна ставка не дешевле медианы → is_suspiciously_cheap=False.
        """
        bids = [
            {"carrier_code": "A", "price": "300.00"},
            {"carrier_code": "B", "price": "300.00"},
            {"carrier_code": "C", "price": "300.00"},
        ]
        for b in bids:
            result = bid_risk(b, bids)
            assert result["deviation_pct"] == 0.0, f"carrier {b['carrier_code']}: отклонение ≠ 0"
            assert result["is_suspiciously_cheap"] is False

    @pytest.mark.unit
    def test_bid_risk_dumping_outlier_below(self):
        """Выброс вниз при ≥ DUMPING_MIN_BIDS ставках: флаг демпинга True.

        Три ставки: 1000, 1000, 200 (−80% от медианы 1000). Порог 25%.
        is_suspiciously_cheap должен быть True для ставки 200.
        """
        bids = [
            {"carrier_code": "A", "price": "1000.00"},
            {"carrier_code": "B", "price": "1000.00"},
            {"carrier_code": "C", "price": "200.00"},  # демпинг
        ]
        outlier = bids[2]
        result = bid_risk(outlier, bids)
        assert result["is_suspiciously_cheap"] is True, "Выброс вниз должен детектироваться"
        # deviation должна быть > DUMPING_THRESHOLD_PCT (25%)
        assert result["deviation_pct"] > DUMPING_THRESHOLD_PCT, (
            f"deviation_pct={result['deviation_pct']} < порог {DUMPING_THRESHOLD_PCT}"
        )

    @pytest.mark.unit
    def test_bid_risk_not_dumping_below_min_bids(self):
        """Даже сильный разрыв при < DUMPING_MIN_BIDS ставок → флаг False.

        Всего 2 ставки: 1000 и 100. Порог по количеству не достигнут (min=3).
        """
        bids = [
            {"carrier_code": "A", "price": "1000.00"},
            {"carrier_code": "B", "price": "100.00"},
        ]
        result = bid_risk(bids[1], bids)
        assert result["is_suspiciously_cheap"] is False, (
            f"< {DUMPING_MIN_BIDS} ставок — флаг не должен срабатывать"
        )

    @pytest.mark.unit
    def test_bid_risk_zero_price_no_division_error(self):
        """Ставка с ценой 0 не вызывает деления на ноль."""
        bids = [
            {"carrier_code": "A", "price": "0"},
            {"carrier_code": "B", "price": "500.00"},
            {"carrier_code": "C", "price": "600.00"},
        ]
        # Нулевая цена исключена из prices при расчёте медианы (фильтр > 0).
        result = bid_risk(bids[0], bids)
        # Нет исключения — достаточно. Флаг тоже False (price=0 не считаем «дешёвым»).
        assert "is_suspiciously_cheap" in result
        assert result["is_suspiciously_cheap"] is False

    @pytest.mark.unit
    def test_bid_risk_threshold_boundary(self):
        """Ставка ровно на DUMPING_THRESHOLD_PCT % ниже медианы: флаг True (≥ порог).

        Граница включающая: deviation_pct >= 25.0 → suspicious.
        Медиана = 400, порог 25% → цена 300 (−25% ровно) должна давать True.
        """
        median_val = 400.0
        threshold_pct = DUMPING_THRESHOLD_PCT  # 25.0
        threshold_price = median_val * (1.0 - threshold_pct / 100.0)  # 300.0
        bids = [
            {"carrier_code": "A", "price": str(median_val)},
            {"carrier_code": "B", "price": str(median_val)},
            {"carrier_code": "C", "price": str(threshold_price)},  # ровно 25% ниже
        ]
        result = bid_risk(bids[2], bids)
        assert result["is_suspiciously_cheap"] is True, (
            f"deviation_pct={result['deviation_pct']} — ровно на пороге, должен быть True"
        )

    @pytest.mark.unit
    def test_bid_risk_just_below_threshold(self):
        """Ставка чуть выше порога (−24.9%): флаг False.

        Граница: deviation < 25.0 → not suspicious.
        """
        median_val = 400.0
        # -24.9% от медианы
        price = median_val * (1.0 - 0.249)  # ≈ 300.4
        bids = [
            {"carrier_code": "A", "price": str(median_val)},
            {"carrier_code": "B", "price": str(median_val)},
            {"carrier_code": "C", "price": str(round(price, 2))},
        ]
        result = bid_risk(bids[2], bids)
        assert result["is_suspiciously_cheap"] is False, (
            f"deviation_pct={result['deviation_pct']} < порог, флаг не должен срабатывать"
        )


# ---------------------------------------------------------------------------
# R5-4: import.received без подписчиков — INFO-эвент не роняет шину
# ---------------------------------------------------------------------------

class TestImportReceivedNoSubscribers:
    """R5-4: шина с нулём подписчиков на logistics.import.received не падает.

    Контракт LOG3-4 (CLAUDE.md): «оставляем INFO без обязательного подписчика — осознанно».
    relay_once должен пометить OutboxEvent.processed_at и записать AuditLog-проекцию.

    Как упал бы на старом коде:
      - Если бы relay_once не обрабатывал пустой список handlers корректно, а падал
        с KeyError/IndexError при dispatch → OutboxEvent остался бы незапомечен →
        бесконечный повтор + потенциальный блок всего relay-цикла.
      - Тест доказывает at-least-once + graceful no-op при отсутствии подписчиков.
    """

    @pytest.mark.api
    async def test_import_received_emits_without_subscribers(self, session):
        """INFO-эвент записывается в outbox и relay не кидает при нуле handlers."""
        from core.domain.models import AuditLog
        from core.services.eventbus import EventContext, OutboxEventBus

        bus = OutboxEventBus()
        # Никаких subscribe — handlers для этого типа отсутствуют.
        assert "logistics.import.received" not in bus._handlers

        bus.emit(
            session,
            "logistics.import.received",
            {
                "import_id": 10, "number": "ИМП-2026-0010",
                "po_ref": "purchase:10", "freight_amount": "1500.00",
                "eta": None, "supplier": "Shenzhen Ltd", "entity_ref": "ИМП-2026-0010",
            },
        )
        await session.flush()

        ctx = EventContext(session=session, services=object())
        # relay_once без подписчиков не должен кинуть исключение.
        processed = await bus.relay_once(session, ctx)
        assert processed == 1, "relay_once должен обработать (пометить) эвент"

        # OutboxEvent помечен processed_at.
        event = (await session.execute(select(OutboxEvent))).scalars().first()
        assert event is not None
        assert event.processed_at is not None, "OutboxEvent должен быть помечен processed_at"
        assert event.event_type == "logistics.import.received"

        # AuditLog-проекция создана relay'ем.
        audits = (await session.execute(select(AuditLog))).scalars().all()
        matching = [a for a in audits if a.action == "logistics.import.received"]
        assert matching, "AuditLog-проекция должна быть создана relay'ем"
        assert matching[0].entity_ref == "ИМП-2026-0010"

    @pytest.mark.api
    async def test_freight_cost_no_subscribers_relay_ok(self, session):
        """Зеркальный тест: freight.cost без finance-подписчика relay не роняет.

        При временном падении finance-подписчика logistics должен продолжать
        работу: событие запишется в outbox и будет повторено позже.
        """
        from core.services.eventbus import EventContext, OutboxEventBus

        bus = OutboxEventBus()
        bus.emit(session, "logistics.freight.cost", {
            "ref": "import:99", "leg": "import", "amount": "9999.99",
            "po_ref": "purchase:99", "entity_ref": "import:99",
        })
        await session.flush()

        processed = await bus.relay_once(
            session, EventContext(session=session, services=object())
        )
        assert processed == 1

        event = (await session.execute(select(OutboxEvent))).scalars().first()
        assert event is not None and event.processed_at is not None

    @pytest.mark.api
    async def test_multiple_events_no_subscribers_all_processed(self, session):
        """Несколько INFO-событий в одном flush — relay обрабатывает все (at-least-once).

        Граничный кейс: два события, оба без подписчиков → оба processed.
        """
        from core.services.eventbus import EventContext, OutboxEventBus

        bus = OutboxEventBus()
        for i in (1, 2):
            bus.emit(
                session, "logistics.import.received",
                {"import_id": i, "number": f"ИМП-2026-{i:04d}",
                 "po_ref": f"purchase:{i}", "freight_amount": "0",
                 "eta": None, "supplier": "X", "entity_ref": f"ИМП-2026-{i:04d}"},
            )
        await session.flush()

        ctx = EventContext(session=session, services=object())
        # Два раза relay_once — каждый раз обрабатывает один pending-эвент.
        total = 0
        for _ in range(5):  # не больше 5 итераций
            n = await bus.relay_once(session, ctx)
            total += n
            if n == 0:
                break

        assert total == 2, f"Ожидалось 2 обработанных, получено {total}"

        events = (await session.execute(select(OutboxEvent))).scalars().all()
        for ev in events:
            assert ev.processed_at is not None, (
                f"OutboxEvent id={ev.id} type={ev.event_type} не помечен"
            )
