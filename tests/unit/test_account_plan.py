"""Unit-проверки состава типового плана счетов РБ.

Проверяем только статическую структуру классификатора: без БД, миграций и HTTP.
Загрузка в SQLite/Postgres остаётся обязанностью ``scripts/seed.py``.
"""

import re

import pytest

from core.reference.account_plan import (
    ACCOUNT_DEFS,
    ACCOUNT_PLAN_EFFECTIVE_FROM,
    ACCOUNT_PLAN_SOURCE,
)


def _by_code() -> dict[str, tuple[str, str, str | None]]:
    return {code: (title, kind, parent) for code, title, kind, parent in ACCOUNT_DEFS}


def test_account_plan_has_unique_codes_and_non_empty_titles():
    codes = [code for code, _title, _kind, _parent in ACCOUNT_DEFS]
    assert len(codes) == len(set(codes))
    assert all(title.strip() for _code, title, _kind, _parent in ACCOUNT_DEFS)


def test_account_plan_parent_links_are_resolvable_and_acyclic():
    by_code = _by_code()
    for code, _title, _kind, parent in ACCOUNT_DEFS:
        if parent is not None:
            assert parent in by_code, f"{code} points to missing parent {parent}"
            assert code.startswith(parent + ".")

    for start in by_code:
        seen: set[str] = set()
        current = start
        while current is not None:
            assert current not in seen, f"cycle through {current}"
            seen.add(current)
            current = by_code[current][2]


@pytest.mark.parametrize(
    "code",
    ["01", "10", "41", "50", "51", "60", "62", "68", "70", "80", "90", "99"],
)
def test_plan_contains_core_synthetic_accounts(code):
    assert code in _by_code()


@pytest.mark.parametrize("code", ["10.1", "41.1", "55.1", "66.1", "68.2", "90.1", "91.4"])
def test_plan_contains_standard_subaccounts(code):
    title, _kind, parent = _by_code()[code]
    assert title
    assert parent is not None


def test_plan_contains_named_off_balance_accounts():
    by_code = _by_code()
    off_balance = {code for code, (_title, kind, _parent) in by_code.items() if kind == "забалансовый"}
    assert {"001", "002", "003", "004", "005", "006", "007", "008", "009"} <= off_balance
    assert {"011", "014", "016", "017"} <= off_balance


def test_plan_codes_are_synthetic_subaccounts_or_off_balance():
    pattern = re.compile(r"^(?:\d{2,3}|\d{2}\.\d{1,2})$")
    assert all(pattern.fullmatch(code) for code, _title, _kind, _parent in ACCOUNT_DEFS)


def test_plan_source_and_effective_date_are_pinned():
    assert "№50" in ACCOUNT_PLAN_SOURCE
    assert "№126" in ACCOUNT_PLAN_SOURCE
    assert ACCOUNT_PLAN_EFFECTIVE_FROM.isoformat() == "2026-01-01"
