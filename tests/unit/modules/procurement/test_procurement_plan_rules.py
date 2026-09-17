from datetime import date

import pytest

from modules.procurement.plan import (
    DEFAULT_METHODS,
    arrival_deadline,
    build_milestone_plan,
    parse_deadline,
    total_transit_days,
)


def test_transit_days_sum_known_method_and_tolerates_missing_stages():
    assert total_transit_days(DEFAULT_METHODS["container"]["durations"]) == 112
    assert total_transit_days({"collection": 2, "unknown": 99}) == 2


def test_milestone_plan_is_reverse_waterfall_in_forward_stage_order():
    plans, start = build_milestone_plan(
        {"collection": 2, "payment": 1, "production": 3, "to_cn_warehouse": 1, "to_minsk": 4, "customs": 2},
        date(2026, 10, 31),
    )
    assert [item["stage"] for item in plans] == ["collection", "payment", "production", "to_cn_warehouse", "to_minsk", "customs"]
    assert [item["seq"] for item in plans] == list(range(6))
    assert plans[-1]["planned_date"] == date(2026, 10, 31)
    assert plans[0]["planned_date"] == date(2026, 10, 20)
    assert start == date(2026, 10, 18)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("", None), ("2026-09-17", date(2026, 9, 17)), ("2026-09-17T12:00", date(2026, 9, 17)), ("17.09.2026", date(2026, 9, 17)), ("17,09,2026", date(2026, 9, 17)), ("17/09/2026", date(2026, 9, 17)), ("31.02.2026", None), ("n/a", None)],
)
def test_deadline_parser_accepts_supported_formats_and_rejects_bad_dates(raw, expected):
    assert parse_deadline(raw) == expected


def test_arrival_deadline_subtracts_last_mile_buffer_and_handles_empty():
    assert arrival_deadline(date(2026, 9, 17)) == date(2026, 9, 14)
    assert arrival_deadline(date(2026, 9, 17), buffer_days=0) == date(2026, 9, 17)
    assert arrival_deadline(None) is None
