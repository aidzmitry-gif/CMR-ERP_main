"""Unit-тесты подбора перевозчика по пригодности груза (без I/O)."""
from modules.logistics import fleet


class _V:
    def __init__(self, cls, cap, temp=False):
        self.vehicle_class = cls
        self.capacity_kg = cap
        self.temp_control = temp


class _C:
    def __init__(self, cat, adr=False, oversize=False, mw=0, md=0):
        self.category = cat
        self.adr = adr
        self.oversize = oversize
        self.max_weight_kg = mw
        self.max_dim_cm = md


VEH = [_V("Газель 1.5т", 1500), _V("Тент 5т", 5000), _V("Фура 20т", 20000)]
CAPS = [_C("обычный"), _C("АКБ", mw=1000), _C("опасный_ADR", adr=True), _C("негабарит", oversize=True, md=600)]


def test_vehicle_fits_weight_and_temp():
    assert fleet.vehicle_fits(_V("Тент", 5000), 420) is True
    assert fleet.vehicle_fits(_V("Газель", 1500), 2000) is False
    assert fleet.vehicle_fits(_V("Реф", 8000, temp=True), 500, needs_temp=True) is True
    assert fleet.vehicle_fits(_V("Тент", 8000), 500, needs_temp=True) is False  # не рефрижератор


def test_capability_allows_limits_and_adr():
    assert fleet.capability_allows(_C("АКБ", mw=1000), 500) is True
    assert fleet.capability_allows(_C("АКБ", mw=1000), 1500) is False           # сверх лимита веса
    assert fleet.capability_allows(_C("опасный_ADR", adr=True), 100, adr=True) is True
    assert fleet.capability_allows(_C("обычный"), 100, adr=True) is False        # нет допуска ADR
    assert fleet.capability_allows(_C("негабарит", md=600), 100, max_dim_cm=800) is False  # длиннее лимита


def test_carrier_eligible_picks_minimal_sufficient_vehicle():
    # 420 кг АКБ → минимальная достаточная машина = Газель 1.5т
    m = fleet.carrier_eligible(VEH, CAPS, weight_kg=420, category="АКБ")
    assert m["vehicle_class"] == "Газель 1.5т"


def test_carrier_eligible_no_vehicle_big_enough():
    assert fleet.carrier_eligible(VEH, CAPS, weight_kg=25000) is None


def test_carrier_eligible_category_not_allowed():
    assert fleet.carrier_eligible(VEH, CAPS, weight_kg=100, category="температурный") is None


def test_carrier_eligible_adr_requires_capability():
    assert fleet.carrier_eligible(VEH, CAPS, weight_kg=100, category="опасный_ADR", adr=True) is not None
    assert fleet.carrier_eligible(VEH, [_C("обычный")], weight_kg=100, adr=True) is None


def test_carrier_eligible_no_category_only_weight():
    m = fleet.carrier_eligible(VEH, [], weight_kg=4000)
    assert m["vehicle_class"] == "Тент 5т"   # Газель мала, Тент 5т подходит и минимальна
