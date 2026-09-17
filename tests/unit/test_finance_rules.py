"""Unit-тесты чистых финансовых правил ERP: деньги, FX, aging и сверка."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from modules.finance.aging import _bucket
from modules.finance.bank_ingest import _digits, _ref_in_purpose
from modules.finance.cost_center import resolve_center
from modules.finance.fx import UnknownCurrency, to_byn
from modules.finance.margin import _parse_items, _row
from modules.finance.reconcile import _onec_key, _safe_amount
from modules.finance.schemas import money_str


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("10.005", "BYN", Decimal("10.005")),
        ("10.00", None, Decimal("10.00")),
        ("100", "USD", Decimal("363.00")),
    ],
)
def test_to_byn_uses_base_currency_and_buffer(amount, currency, expected):
    assert to_byn(amount, currency) == expected


def test_to_byn_rejects_unknown_currency_instead_of_guessing():
    with pytest.raises(UnknownCurrency):
        to_byn("100", "ZZZ")


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (None, "no_due"),
        (date(2026, 9, 17), "current"),
        (date(2026, 9, 16), "1-30"),
        (date(2026, 8, 17), "31-60"),
        (date(2026, 7, 18), "61-90"),
        (date(2026, 6, 17), "90+"),
    ],
)
def test_aging_buckets_preserve_boundary_semantics(due, expected):
    assert _bucket(due, date(2026, 9, 17)) == expected


@pytest.mark.parametrize(
    ("kind", "explicit", "expected"),
    [
        ("receivable", None, "Продажи"),
        ("landed", None, "Закупки"),
        ("freight", None, "Логистика"),
        ("unknown", None, "Прочее"),
        ("receivable", "Ключевые клиенты", "Ключевые клиенты"),
    ],
)
def test_resolve_center_honors_explicit_override(kind, explicit, expected):
    payment = SimpleNamespace(kind=kind, cost_center=explicit)
    assert resolve_center(payment) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("100,00", 100.0), ("100 000", 100000.0), ("", 0.0), ("not-money", 0.0), (None, 0.0)],
)
def test_reconcile_amount_parser_is_locale_safe_and_fail_soft(raw, expected):
    assert _safe_amount(raw) == expected


def test_parse_items_skips_bad_tokens_without_losing_valid_items():
    assert _parse_items("SKU-1:2,broken,SKU-2: 1.5, :4,SKU-3:nope") == {
        "SKU-1": Decimal("2"),
        "SKU-2": Decimal("1.5"),
    }


def test_margin_row_subtracts_claim_refund_and_excludes_planned_amounts():
    row = _row(
        42,
        {
            "receivable": Decimal("1000"),
            "landed": Decimal("400"),
            "claim_refund": Decimal("50"),
            "freight": Decimal("100"),
            "freight_refund": Decimal("-20"),
        },
    )
    assert row["landed"] == "350.00"
    assert row["freight"] == "80.00"
    assert row["gross"] == "570.00"
    assert row["pct"] == 57.0


def test_bank_reference_matching_requires_meaningful_token():
    assert _digits("УНП 1 234 567") == "1234567"
    assert _ref_in_purpose("СЧ-100", "ОПЛАТА СЧ100 ПО ДОГОВОРУ") is True
    assert _ref_in_purpose("СЧ", "ОПЛАТА СЧ") is False
    assert _ref_in_purpose("СЧ-100", "ОПЛАТА СЧ101") is False


def test_finance_money_and_one_c_key_are_deterministic():
    assert money_str(Decimal("1.005")) == "1.00"
    assert _onec_key({"ref": "INV-1", "counterparty_ref": None}) == "INV-1|"
