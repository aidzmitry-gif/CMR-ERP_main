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
