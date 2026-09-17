from decimal import Decimal

from modules.legal.models import LegalCase
from modules.legal.routes import _fmt_money, _to_card


def test_money_formatter_uses_integer_rubles_and_spaces():
    assert _fmt_money(1234567.89) == "1 234 567 ₽"
    assert _fmt_money(0) == "0 ₽"


def test_claim_card_contains_debt_details_and_action():
    card = _to_card(
        LegalCase(
            id=3,
            company="ООО Альфа",
            title="Просроченный договор",
            amount=Decimal("12500"),
            urgency="Срочно",
            owner="Юрист",
            stage="claim",
            due_date="2026-10-01",
            next_step="Направить претензию",
        )
    )
    assert card.code == "ДЕЛО-3"
    assert card.title == "ООО Альфа"
    assert card.amount == 12500.0
    assert card.action == "Открыть документ →"
    assert card.details == [
        {"k": "Сумма долга", "v": "12 500 ₽"},
        {"k": "Неустойка (пени)", "v": "1 000 ₽"},
        {"k": "Способ", "v": "Почта + ЭДО"},
    ]


def test_non_claim_stage_has_no_claim_details_or_action():
    for stage in ("inbox", "contract", "closed"):
        card = _to_card(
            LegalCase(
                id=4,
                number="L-4",
                company="",
                title="",
                amount=Decimal("100"),
                urgency="",
                owner="",
                stage=stage,
                next_step="",
            )
        )
        assert card.details == []
        assert card.action == ""

    assert (
        _to_card(
            LegalCase(
                id=5,
                company="",
                title="",
                amount=Decimal("0"),
                urgency="",
                owner="",
                stage="claim",
                next_step="",
            )
        ).details
        == []
    )
