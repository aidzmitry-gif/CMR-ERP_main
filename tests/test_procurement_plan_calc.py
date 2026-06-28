"""Тесты чистого расчёта плана сбора машины (без БД): обратный waterfall + итог транзита.

Модель из реального плана заказчика «Перевозка»: Контейнер 112 дн / Машина 83 дн; план
считается ОТ дедлайна «В Минске до» назад. Логика — ``modules.procurement.plan`` (чистые функции).
"""
from __future__ import annotations

from datetime import date, timedelta

from modules.procurement.plan import (
    DEFAULT_METHODS,
    LAST_MILE_BUFFER_DAYS,
    STAGE_ORDER,
    arrival_deadline,
    build_milestone_plan,
    parse_deadline,
    total_transit_days,
)


def test_total_transit_days_matches_customer_plan():
    assert total_transit_days(DEFAULT_METHODS["container"]["durations"]) == 112
    assert total_transit_days(DEFAULT_METHODS["truck"]["durations"]) == 83


def test_backward_waterfall_container():
    target = date(2026, 10, 1)
    plans, start = build_milestone_plan(DEFAULT_METHODS["container"]["durations"], target)
    by = {p["stage"]: p for p in plans}
    # последний этап (растоможка) завершается ровно в «В Минске до»
    assert by["customs"]["planned_date"] == target
    # старт = target − итог (112); сбор завершается через свою длительность после старта
    assert start == target - timedelta(days=112)
    # КАЖДЫЙ этап (не только концы цепочки) — иначе off-by-one в середине прошёл бы незаметно.
    # offset = сумма длительностей этапов ПОСЛЕ данного; end-of-stage = target − offset.
    expected_offset = {
        "customs": 0, "to_minsk": 7, "to_cn_warehouse": 49,
        "production": 56, "payment": 77, "collection": 84,
    }
    for stage, off in expected_offset.items():
        assert by[stage]["planned_date"] == target - timedelta(days=off), stage
    # порядок этапов и seq — прямой
    assert [p["stage"] for p in plans] == STAGE_ORDER
    assert [p["seq"] for p in plans] == list(range(len(STAGE_ORDER)))


def test_backward_waterfall_truck_faster_than_container():
    target = date(2026, 10, 1)
    _, start_truck = build_milestone_plan(DEFAULT_METHODS["truck"]["durations"], target)
    _, start_cont = build_milestone_plan(DEFAULT_METHODS["container"]["durations"], target)
    # фура быстрее → её можно стартовать позже под тот же дедлайн (83 vs 112)
    assert start_truck == target - timedelta(days=83)
    assert start_truck > start_cont


def test_unknown_stage_duration_treated_as_zero():
    """Этап без длительности в шаблоне → 0 дней (не падаем); итог считается по известным."""
    durations = {"collection": 10}  # остальные этапы отсутствуют
    plans, start = build_milestone_plan(durations, date(2026, 10, 1))
    assert total_transit_days(durations) == 10
    assert start == date(2026, 10, 1) - timedelta(days=10)


def test_parse_deadline_formats():
    assert parse_deadline("2026-12-31") == date(2026, 12, 31)  # ISO
    assert parse_deadline("31.12.2026") == date(2026, 12, 31)  # DD.MM.YYYY
    assert parse_deadline("31,12,2026") == date(2026, 12, 31)  # DD,MM,YYYY (как в таблице)
    assert parse_deadline("01/10/2026") == date(2026, 10, 1)   # DD/MM/YYYY
    assert parse_deadline("") is None
    assert parse_deadline(None) is None
    assert parse_deadline("24 июля 2026") is None  # неразобранное → None (honest-empty)


def test_arrival_deadline_subtracts_buffer():
    assert arrival_deadline(date(2026, 12, 31)) == date(2026, 12, 31) - timedelta(days=LAST_MILE_BUFFER_DAYS)
    assert arrival_deadline(date(2026, 12, 31), buffer_days=0) == date(2026, 12, 31)
    assert arrival_deadline(None) is None
