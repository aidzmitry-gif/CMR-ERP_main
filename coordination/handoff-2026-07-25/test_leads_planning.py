"""Unit-тесты обратной воронки планирования лидов (чистый расчёт, без I/O).

Опорный пример — металлопрокат из ``leads-planning-plan.md`` (§Обратная воронка):
цель 1 200 000 BYN, чек 20 000, доля сделок 20%, конв. тёплое→готовый 14%, сырой→тёплое 35%.
"""
from decimal import Decimal

import pytest

from modules.leads import planning


# --- Обратная воронка: опорный пример спеки ------------------------------- #
def test_reverse_funnel_metalloprokat_example():
    r = planning.reverse_funnel(
        revenue_target_byn=1_200_000,
        avg_deal_byn=20_000,
        win_rate=0.20,
        conv_mql_sql=0.14,
        conv_raw_mql=0.35,
        workdays=26,
    )
    assert r.deals_needed == 60                    # 1.2M / 20k
    assert r.sql_needed == 300                     # 60 / 0.20
    assert r.mql_needed == 2143                    # 300 / 0.14 = 2142.86 → ceil
    # 2142.86 / 0.35 = 6122.45 → ceil 6123 (нужно НЕ МЕНЬШЕ; спека показывает ≈6122 округлением)
    assert r.raw_needed == 6123
    assert r.raw_per_workday == 236                # 6122.45 / 26 = 235.48 → ceil
    assert r.pipeline_needed_byn == Decimal("6000000.00")  # 1.2M / 0.20 = запас 5×
    assert r.pipeline_multiple == 5.0


def test_reverse_funnel_money_is_decimal_no_float_drift():
    r = planning.reverse_funnel(
        revenue_target_byn="999999.99", avg_deal_byn="17333.33",
        win_rate=0.18, conv_mql_sql=0.12, conv_raw_mql=0.4,
    )
    assert isinstance(r.pipeline_needed_byn, Decimal)
    assert isinstance(r.revenue_target_byn, Decimal)
    # покрытие = цель / доля сделок, ровно 2 знака
    assert r.pipeline_needed_byn == (Decimal("999999.99") / Decimal("0.18")).quantize(Decimal("0.01"))


def test_reverse_funnel_ceil_rounds_up_partial_lead():
    # 100k / 10k = 10 сделок; /0.5 = 20 sql; /0.5 = 40 mql; /0.3 = 133.33 → ceil 134
    r = planning.reverse_funnel(
        revenue_target_byn=100_000, avg_deal_byn=10_000,
        win_rate=0.5, conv_mql_sql=0.5, conv_raw_mql=0.3,
    )
    assert r.deals_needed == 10 and r.sql_needed == 20 and r.mql_needed == 40
    assert r.raw_needed == 134  # 40 / 0.3 = 133.33 → вверх


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, 2.0])
def test_reverse_funnel_rejects_out_of_range_rates(bad):
    # деньги #1: битый коэффициент — честная ошибка, НЕ inf/деление на ноль
    with pytest.raises(ValueError):
        planning.reverse_funnel(
            revenue_target_byn=100_000, avg_deal_byn=10_000,
            win_rate=bad, conv_mql_sql=0.5, conv_raw_mql=0.5,
        )


def test_reverse_funnel_rejects_zero_avg_deal_and_negative_money():
    with pytest.raises(ValueError):
        planning.reverse_funnel(revenue_target_byn=100_000, avg_deal_byn=0,
                                win_rate=0.2, conv_mql_sql=0.2, conv_raw_mql=0.2)
    with pytest.raises(ValueError):
        planning.reverse_funnel(revenue_target_byn=-1, avg_deal_byn=10_000,
                                win_rate=0.2, conv_mql_sql=0.2, conv_raw_mql=0.2)


def test_reverse_funnel_rejects_nonpositive_workdays():
    with pytest.raises(ValueError):
        planning.reverse_funnel(revenue_target_byn=100_000, avg_deal_byn=10_000,
                                win_rate=0.2, conv_mql_sql=0.2, conv_raw_mql=0.2, workdays=0)


# --- Ёмкость снизу вверх (сверка реальности) ------------------------------ #
def test_capacity_check_deficit_matches_spec():
    # 1 лидоруб ≈ 60 сырых/день × 26 = 1560/мес против потребности 6123 → дефицит
    c = planning.capacity_check(required_raw=6123, capacity_per_day=60, workdays=26)
    assert c.capacity_per_month == 1560
    assert c.delta == 4563 and c.is_deficit is True


def test_capacity_check_surplus_not_deficit():
    c = planning.capacity_check(required_raw=1000, capacity_per_day=60, workdays=26)
    assert c.capacity_per_month == 1560
    assert c.delta == -560 and c.is_deficit is False


def test_capacity_check_ramp_factor_floors_capacity():
    # новичок на 50% разгона: floor(60 × 26 × 0.5) = 780
    c = planning.capacity_check(required_raw=1000, capacity_per_day=60, workdays=26, ramp_factor=0.5)
    assert c.capacity_per_month == 780 and c.is_deficit is True


@pytest.mark.parametrize("ramp", [0.0, -0.2, 1.5])
def test_capacity_check_rejects_bad_ramp(ramp):
    with pytest.raises(ValueError):
        planning.capacity_check(required_raw=100, capacity_per_day=60, ramp_factor=ramp)
