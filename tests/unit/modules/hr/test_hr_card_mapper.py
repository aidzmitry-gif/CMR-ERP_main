from decimal import Decimal

from modules.hr.models import Candidate
from modules.hr.routes import _to_card


def test_candidate_card_maps_business_fields_and_fallback_code():
    card = _to_card(
        Candidate(
            id=7,
            number="",
            name="Анна Петрова",
            position="Менеджер",
            salary=Decimal("3456.70"),
            recruiter="Ирина",
            priority="Высокий",
            next_step="Техническое интервью",
        )
    )

    assert card.model_dump() == {
        "id": 7,
        "code": "CAND-7",
        "title": "Анна Петрова",
        "subtitle": "Менеджер",
        "flag": "",
        "amount": 3456.7,
        "priority": "Высокий",
        "status_tag": "",
        "owner": "Ирина",
        "date": "",
        "progress": None,
        "next_step": "Техническое интервью",
        "insight": "",
        "score": "",
        "state": "",
        "action": "",
        "details": [],
        "tags": [],
    }


def test_candidate_card_keeps_explicit_number_and_zero_salary():
    card = _to_card(
        Candidate(
            id=8,
            number="C-008",
            name="",
            position="",
            salary=Decimal("0"),
            priority="",
            recruiter="",
            next_step="",
        )
    )
    assert card.code == "C-008"
    assert card.amount == 0.0
