"""Unit-тесты расчёта тарифа доставки и балла перевозчика (без I/O)."""
from modules.logistics import pricing


class _Tariff:
    """Лёгкий стенд тарифа (как строка CarrierTariff) для расчёта."""

    def __init__(self, w5, w10, w30, over30, pickup=0, cod=0, ins=0):
        self.price_w5 = w5
        self.price_w10 = w10
        self.price_w30 = w30
        self.over30_per_kg = over30
        self.pickup_fee = pickup
        self.cod_pct = cod
        self.insurance_pct = ins


# Автолайт z2 из прайс-матрицы (BACKEND_SPEC §2).
AUTOLIGHT_Z2 = _Tariff(10.50, 15.00, 24.00, 1.60, pickup=4.00, cod=1.2, ins=0.25)


def test_quote_weight_bands():
    t = AUTOLIGHT_Z2
    assert pricing.quote_tariff(t, 3)["base"] == 10.50    # ≤5
    assert pricing.quote_tariff(t, 8)["base"] == 15.00    # ≤10
    assert pricing.quote_tariff(t, 25)["base"] == 24.00   # ≤30


def test_quote_over_30kg_matches_spec_example():
    # Минск→Гомель (z2), 64 кг, Автолайт → 24,00 + (64-30)*1,60 = 78,40 BYN
    assert pricing.quote_tariff(AUTOLIGHT_Z2, 64)["total"] == 78.40
    assert pricing.quote_tariff(AUTOLIGHT_Z2, 64)["base"] == 78.40


def test_quote_pickup_cod_insurance_fees():
    q = pricing.quote_tariff(
        AUTOLIGHT_Z2, 3, pickup=True, cod_amount=1000, declared_value=2000
    )
    assert q["pickup"] == 4.00
    assert q["cod_fee"] == 12.00          # 1000 * 1.2%
    assert q["insurance_fee"] == 5.00     # 2000 * 0.25%
    assert q["total"] == 10.50 + 4.00 + 12.00 + 5.00


def test_volumetric_and_chargeable_weight():
    # 50×40×30 см / 5000 = 12 кг объёмного; оплачиваемый = max(физ, объёмный)
    assert pricing.volumetric_weight(50, 40, 30) == 12.0
    assert pricing.chargeable_weight(8, 12) == 12
    assert pricing.chargeable_weight(20, 12) == 20


def test_score_and_grade():
    # формула: otd*0.40 + damage*0.25 + billing*0.20 + (100-claims)*0.15
    score = pricing.score_carrier(96, 99.1, 97, 0.9)
    assert score == round(96 * 0.40 + 99.1 * 0.25 + 97 * 0.20 + 99.1 * 0.15, 1)
    assert pricing.grade_for(92) == "A"
    assert pricing.grade_for(87) == "B"
    assert pricing.grade_for(74) == "C"
    assert pricing.grade_for(90) == "A" and pricing.grade_for(83) == "B"


def test_rank_bids_best_value_beats_cheapest():
    # дешёвая, но ненадёжная ставка не должна выиграть у чуть дороже, но качественной
    bids = [
        {"id": 1, "carrier_code": "belpost", "price": 100},     # дешевле всех, балл низкий
        {"id": 2, "carrier_code": "dpd", "price": 110},         # чуть дороже, балл высокий
    ]
    ranked = pricing.rank_bids(bids, {"belpost": 70.0, "dpd": 97.0})
    assert ranked[0][0]["id"] == 2                              # best-fit — dpd, не дешёвый belpost
    assert ranked[0][1] > ranked[1][1] and 0 <= ranked[1][1] <= 1


def test_rank_bids_equal_quality_picks_cheapest():
    # при равном качестве best-fit вырождается в «дешевле = лучше»
    bids = [
        {"id": 1, "carrier_code": "a", "price": 200},
        {"id": 2, "carrier_code": "b", "price": 150},
    ]
    ranked = pricing.rank_bids(bids, {"a": 90.0, "b": 90.0})
    assert ranked[0][0]["id"] == 2


def test_rank_bids_missing_score_is_neutral():
    # перевозчик без истории не наказывается (нейтральные 0.5), но цена решает
    ranked = pricing.rank_bids(
        [{"id": 1, "carrier_code": "x", "price": 100}], {}
    )
    assert ranked[0][1] == round(0.6 * 1.0 + 0.4 * 0.5, 4)


def test_bid_risk_dumping_flagged_when_below_median():
    # 5 ставок, медиана 100, дешёвая 70 → 30% ниже → флаг демпинга
    bids = [{"carrier_code": str(i), "price": p} for i, p in enumerate([70, 95, 100, 105, 120])]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["median"] == 100 and risk["deviation_pct"] == 30.0
    assert risk["is_suspiciously_cheap"] is True


def test_bid_risk_no_dump_when_few_bids():
    # 2 ставки — мало для надёжного флага демпинга даже при сильном отклонении
    bids = [{"carrier_code": "a", "price": 50}, {"carrier_code": "b", "price": 100}]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["is_suspiciously_cheap"] is False


def test_bid_risk_no_dump_when_close_to_median():
    # 4 ставки, дешёвая на 10% ниже медианы — норма, не демпинг
    bids = [{"carrier_code": str(i), "price": p} for i, p in enumerate([90, 95, 105, 110])]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["deviation_pct"] == 10.0 and risk["is_suspiciously_cheap"] is False


def test_bid_risk_single_bid_no_signal():
    # одна ставка → нет медианы для сравнения → нет сигналов
    bid = {"carrier_code": "x", "price": 100}
    risk = pricing.bid_risk(bid, [bid])
    assert risk["is_suspiciously_cheap"] is False


# --- Круг 5 харднинг: пограничные случаи bid_risk (демпинг + защита от /0) ---


def test_bid_risk_all_equal_no_flag():
    """Все ставки равны → отклонение 0, флаг НЕ срабатывает (нет «дешёвой» среди них)."""
    bids = [{"carrier_code": str(i), "price": 100} for i in range(5)]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["median"] == 100
    assert risk["deviation_pct"] == 0
    assert risk["is_suspiciously_cheap"] is False


def test_bid_risk_zero_price_does_not_divide():
    """price=0 у проверяемой ставки → guard срабатывает, БЕЗ ZeroDivisionError."""
    bids = [
        {"carrier_code": "z", "price": 0},
        {"carrier_code": "a", "price": 100},
        {"carrier_code": "b", "price": 110},
        {"carrier_code": "c", "price": 120},
    ]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["is_suspiciously_cheap"] is False
    assert risk["deviation_pct"] == 0


def test_bid_risk_all_zero_prices_safe():
    """Все цены 0 → median = 0 → guard вернёт нули без падения (защита от деления на ноль)."""
    bids = [{"carrier_code": str(i), "price": 0} for i in range(4)]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["median"] == 0
    assert risk["is_suspiciously_cheap"] is False


def test_bid_risk_threshold_boundary_exact():
    """Граница порога: ровно на DUMPING_THRESHOLD_PCT (25%) ниже медианы → флаг СРАБАТЫВАЕТ."""
    # Медиана 100, ставка 75 → отклонение 25% (граница ≥), мин. 3 ставки.
    bids = [{"carrier_code": str(i), "price": p} for i, p in enumerate([75, 100, 100, 100, 125])]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["median"] == 100
    assert risk["deviation_pct"] == pricing.DUMPING_THRESHOLD_PCT
    assert risk["is_suspiciously_cheap"] is True


def test_bid_risk_just_below_threshold_no_flag():
    """Ровно на 1% меньше порога (24.9%) — флаг НЕ срабатывает (строгое неравенство ≥)."""
    # Медиана 1000, цена 751 → 24.9% (24.9 < 25)
    bids = [{"carrier_code": str(i), "price": p} for i, p in enumerate([751, 1000, 1000, 1249])]
    risk = pricing.bid_risk(bids[0], bids)
    assert risk["deviation_pct"] == 24.9
    assert risk["is_suspiciously_cheap"] is False


def test_bid_risk_outlier_low_vs_dense_cluster():
    """Один выброс далеко вниз при плотном кластере остальных → демпинг.

    Реальный кейс: 1 «слишком дешёвый», 4 рыночных близких → медиана НЕ ползёт за
    выбросом, флаг чётко указывает на одиночку.
    """
    bids = [{"carrier_code": str(i), "price": p}
            for i, p in enumerate([50, 200, 210, 205, 215])]
    risk = pricing.bid_risk(bids[0], bids)
    # Медиана 5 цен: средний после сортировки [50,200,205,210,215] = 205
    assert risk["median"] == 205
    # (205 - 50) / 205 * 100 = 75.6% — далеко за порогом
    assert risk["deviation_pct"] >= 75
    assert risk["is_suspiciously_cheap"] is True
