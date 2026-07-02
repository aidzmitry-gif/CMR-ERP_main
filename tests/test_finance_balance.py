"""Тесты Finance Р7 — Баланс: GET /finance/balance-sheet."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from modules.finance.models import Payment

# ───────────────────────── assets ─────────────────────────


async def test_assets_receivable_recognized_and_pending(session, api):
    """accounts_receivable = SUM receivable WHERE status IN (recognized, pending)."""
    session.add(Payment(ref="r1", amount=Decimal("500"), status="pending", kind="receivable"))
    session.add(Payment(ref="r2", amount=Decimal("300"), status="recognized", kind="receivable"))
    # paid — НЕ должен входить в дебиторку
    session.add(Payment(ref="r3", amount=Decimal("9999"), status="paid", kind="receivable"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["accounts_receivable"] == "800.00"


async def test_total_assets_sum(session, api):
    """total_assets = accounts_receivable + cash(0 при mock) + inventory(0 при mock)."""
    session.add(Payment(ref="ar", amount=Decimal("1000"), status="pending", kind="receivable"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    # cash=None, inventory=None → обе считаются 0
    assert body["total_assets"] == body["accounts_receivable"]


# ───────────────────────── liabilities ─────────────────────────


async def test_liabilities_by_kind_and_status(session, api):
    """Пассивы: po_planned/freight/landed/payroll/tax только при status=pending."""
    session.add(Payment(ref="ap1", amount=Decimal("200"), status="pending", kind="po_planned"))
    session.add(Payment(ref="ap2", amount=Decimal("150"), status="pending", kind="freight"))
    session.add(Payment(ref="ap3", amount=Decimal("400"), status="pending", kind="landed"))
    session.add(Payment(ref="pw1", amount=Decimal("80"), status="pending", kind="payroll"))
    session.add(Payment(ref="tx1", amount=Decimal("50"), status="pending", kind="tax"))
    # paid — НЕ в пассивах
    session.add(Payment(ref="x1", amount=Decimal("9999"), status="paid", kind="landed"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["accounts_payable"] == "750.00"  # 200+150+400
    assert body["payroll_payable"] == "80.00"
    assert body["tax_payable"] == "50.00"
    assert body["total_liabilities"] == "880.00"  # 750+80+50


async def test_total_liabilities_sum(session, api):
    """total_liabilities = ap + payroll + tax."""
    session.add(Payment(ref="ap", amount=Decimal("100"), status="pending", kind="po_planned"))
    session.add(Payment(ref="pw", amount=Decimal("30"), status="pending", kind="payroll"))
    session.add(Payment(ref="tx", amount=Decimal("20"), status="pending", kind="tax"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["total_liabilities"] == "150.00"


# ───────────────────────── equity ─────────────────────────


async def test_equity_assets_minus_liabilities(session, api):
    """equity = total_assets − total_liabilities."""
    session.add(Payment(ref="ar1", amount=Decimal("2000"), status="pending", kind="receivable"))
    session.add(Payment(ref="ap1", amount=Decimal("500"), status="pending", kind="landed"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assets = Decimal(body["total_assets"])
    liabilities = Decimal(body["total_liabilities"])
    equity = Decimal(body["equity"])
    assert equity == assets - liabilities
    assert body["equity"] == "1500.00"


async def test_equity_negative_when_liabilities_exceed(session, api):
    """Отрицательный капитал — не 500."""
    session.add(Payment(ref="ap1", amount=Decimal("5000"), status="pending", kind="landed"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["equity"]) < 0


# ───────────────────────── cash / inventory = None при mock ─────────────────────────


async def test_cash_is_none_in_mock(session, api):
    """cash = null при mock-режиме (нет OneCGateway) — не 500."""
    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["cash"] is None


async def test_inventory_is_none_in_mock(session, api):
    """inventory_value = null при mock-режиме — не 500."""
    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["inventory_value"] is None


# ───────────────────────── суммы — str, не float ─────────────────────────


async def test_amounts_are_strings(session, api):
    """Денежные поля — строки (не float), без float-дрейфа."""
    session.add(Payment(ref="ar", amount=Decimal("100.50"), status="pending", kind="receivable"))
    await session.commit()

    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "accounts_receivable",
        "total_assets",
        "accounts_payable",
        "payroll_payable",
        "tax_payable",
        "total_liabilities",
        "equity",
    ):
        assert isinstance(body[field], str), f"{field} не строка: {type(body[field])}"


# ───────────────────────── as_of — дата ─────────────────────────


async def test_bad_date_returns_400(session, api):
    """as_of=невалидная_дата → 400."""
    r = await api.get("/finance/balance-sheet?as_of=not-a-date")
    assert r.status_code == 400


async def test_valid_as_of_date(session, api):
    """?as_of=YYYY-MM-DD работает без ошибок."""
    r = await api.get("/finance/balance-sheet?as_of=2025-01-01")
    assert r.status_code == 200
    assert r.json()["as_of"] == "2025-01-01"


async def test_default_as_of_is_today(session, api):
    """Без as_of — используется сегодняшняя дата."""
    today = date.today().isoformat()
    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    assert r.json()["as_of"] == today


# ───────────────────────── CSV ─────────────────────────


async def test_balance_csv_format(session, api):
    """?format=csv → Content-Type text/csv."""
    r = await api.get("/finance/balance-sheet?format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")


# ───────────────────────── пустая БД — нули, не 500 ─────────────────────────


async def test_empty_db_zeros(session, api):
    """Пустая БД → все суммы = 0.00, cash/inventory = None, не 500."""
    r = await api.get("/finance/balance-sheet")
    assert r.status_code == 200
    body = r.json()
    assert body["accounts_receivable"] == "0.00"
    assert body["total_assets"] == "0.00"
    assert body["total_liabilities"] == "0.00"
    assert body["equity"] == "0.00"
    assert body["cash"] is None
    assert body["inventory_value"] is None
