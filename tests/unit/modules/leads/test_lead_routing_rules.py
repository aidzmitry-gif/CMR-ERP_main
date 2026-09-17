from datetime import datetime
from types import SimpleNamespace

import pytest

from modules.leads.leads import (
    cancel_pending_wake,
    choose_funnel,
    companies_conflict,
    is_key_lead,
    lead_priority,
    phone_tail,
    route_lead,
    working_minutes_between,
)
from modules.leads.models import Lead


def test_route_lead_uses_conversion_history_and_key_lead_bypasses_load_penalty():
    lead = Lead(source="site")
    performance = {"Иванов И.И.": 0.80, "Сидоров С.С.": 0.75}
    loads = {"Иванов И.И.": 10, "Сидоров С.С.": 0}
    assert route_lead(lead, loads, False, performance=performance, key=False)[0] == "Сидоров С.С."
    assert route_lead(lead, loads, False, performance=performance, key=True)[0] == "Иванов И.И."


def test_route_lead_falls_back_to_least_loaded_candidate_without_history():
    lead = Lead(source="site", product="оборудование")
    manager, funnel = route_lead(lead, {"Петров П.П.": 2, "Сидоров С.С.": 1}, False)
    assert manager == "Петров П.П."
    assert funnel == "new"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime(2026, 9, 17, 6), datetime(2026, 9, 17, 15), 540.0),
        (datetime(2026, 9, 17, 5), datetime(2026, 9, 17, 16), 540.0),
            (datetime(2026, 9, 17, 23), datetime(2026, 9, 18, 9, 10), 190.0),
        (datetime(2026, 9, 19, 9), datetime(2026, 9, 21, 10), 600.0),
        (datetime(2026, 9, 17, 10), datetime(2026, 9, 17, 9), 0.0),
    ],
)
def test_working_minutes_between_respects_work_window_weekend_and_reverse_interval(start, end, expected):
    assert working_minutes_between(start, end) == expected


@pytest.mark.parametrize(
    ("phone", "expected"),
    [("+375 (29) 123-45-67", "291234567"), ("123456", ""), (None, ""), ("12 345 678", "12345678")],
)
def test_phone_tail_requires_a_meaningful_contact_suffix(phone, expected):
    assert phone_tail(phone) == expected


def test_companies_conflict_allows_blank_or_parent_child_names():
    assert companies_conflict(None, "ООО Альфа") is False
    assert companies_conflict("Ромашка", "ООО Ромашка") is False
    assert companies_conflict("Ромашка", "Стройторг") is True
    assert companies_conflict(" Альфа ", "альфа") is False


def test_cancel_pending_wake_only_clears_snoozed_not_now_rejection():
    snoozed = SimpleNamespace(reject_reason="не сейчас", snooze_until=datetime(2026, 10, 1))
    assert cancel_pending_wake(snoozed) is True
    assert snoozed.snooze_until is None
    assert cancel_pending_wake(SimpleNamespace(reject_reason="дубль", snooze_until=datetime.now())) is False
    assert cancel_pending_wake(None) is False


@pytest.mark.parametrize("score,expected", [(70, "Высокий"), (69, "Средний"), (50, "Средний"), (49, "Низкий")])
def test_lead_priority_boundaries(score, expected):
    assert lead_priority(score) == expected


def test_key_lead_predicate_covers_score_source_customer_and_volume_signals():
    assert is_key_lead(Lead(source="site", score=70)) is True
    assert is_key_lead(Lead(source="tender", score=0)) is True
    assert is_key_lead(Lead(source="site", score=0, customer_kind="regular")) is True
    assert is_key_lead(Lead(source="site", score=0, product="крупный объём")) is True
    assert is_key_lead(Lead(source="site", score=0, product="обычный", message="коротко")) is False


def test_choose_funnel_prioritizes_tender_then_project_then_customer_kind():
    assert choose_funnel(Lead(source="tender", product="проект"), False) == "tender"
    assert choose_funnel(Lead(source="site", product="проектная поставка"), False) == "project"
    assert choose_funnel(Lead(source="site"), True) == "regular"
