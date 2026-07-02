"""Тесты Finance Р6 — ДДС: /finance/cashflow (cash-basis)."""
from __future__ import annotations

from decimal import Decimal

from modules.finance.models import Payment

# ───────────────────────── inflows ─────────────────────────


async def test_inflows_only_paid_or_received(session, api):
    """Поступления считаются только для paid/received receivable."""
    # paid → должен войти в inflows
    session.add(Payment(ref="r1", amount=Decimal("1000"), status="paid", kind="receivable"))
    # received → тоже
    session.add(Payment(ref="r2", amount=Decimal("500"), status="received", kind="receivable"))
    # pending → НЕ входит
    session.add(Payment(ref="r3", amount=Decimal("9999"), status="pending", kind="receivable"))
    await session.commit()

    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    assert body["inflows"] == "1500.00"
    assert body["breakdown"]["receivable"] == "1500.00"


# ───────────────────────── outflows ─────────────────────────


async def test_outflows_by_kinds(session, api):
    """Выбытия агрегируются по kind (только status=paid)."""
    session.add(Payment(ref="p1", amount=Decimal("300"), status="paid", kind="payroll"))
    session.add(Payment(ref="o1", amount=Decimal("150"), status="paid", kind="opex"))
    session.add(Payment(ref="t1", amount=Decimal("80"), status="paid", kind="tax"))
    session.add(Payment(ref="b1", amount=Decimal("20"), status="paid", kind="bank_fee"))
    session.add(Payment(ref="f1", amount=Decimal("70"), status="paid", kind="freight"))
    session.add(Payment(ref="l1", amount=Decimal("400"), status="paid", kind="landed"))
    session.add(Payment(ref="po1", amount=Decimal("200"), status="paid", kind="po_planned"))
    # planned payroll — НЕ в outflows (статус не paid)
    session.add(Payment(ref="p2", amount=Decimal("9999"), status="planned", kind="payroll"))
    await session.commit()

    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    total_out = 300 + 150 + 80 + 20 + 70 + 400 + 200
    assert body["outflows"] == f"{total_out:.2f}"
    assert body["breakdown"]["payroll"] == "300.00"
    assert body["breakdown"]["opex"] == "150.00"
    assert body["breakdown"]["tax"] == "80.00"
    assert body["breakdown"]["bank_fee"] == "20.00"
    assert body["breakdown"]["freight"] == "70.00"
    assert body["breakdown"]["landed"] == "400.00"
    assert body["breakdown"]["po_planned"] == "200.00"


# ───────────────────────── net ─────────────────────────


async def test_net_cashflow_inflows_minus_outflows(session, api):
    """Нетто = inflows − outflows."""
    session.add(Payment(ref="in1", amount=Decimal("1000"), status="paid", kind="receivable"))
    session.add(Payment(ref="out1", amount=Decimal("600"), status="paid", kind="payroll"))
    await session.commit()

    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    assert body["net_cashflow"] == "400.00"


# ───────────────────────── bank_balance ─────────────────────────


async def test_bank_balance_none_in_mock(session, api):
    """bank_balance = null при mock-режиме (OneCGateway.base_url=None) — не 500."""
    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    assert body["bank_balance"] is None  # mock → честный None


# ───────────────────────── CSV ─────────────────────────


async def test_cashflow_csv_format(session, api):
    """?format=csv возвращает Content-Type text/csv."""
    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31&format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")


# ───────────────────────── типы сумм — str, не float ─────────────────────────


async def test_cashflow_amounts_are_strings(session, api):
    """Деньги в /finance/cashflow — строки (не float)."""
    session.add(Payment(ref="x1", amount=Decimal("100"), status="paid", kind="receivable"))
    await session.commit()

    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    for field in ("inflows", "outflows", "net_cashflow"):
        assert isinstance(body[field], str), f"{field} не строка: {type(body[field])}"
    for kind, val in body["breakdown"].items():
        assert isinstance(val, str), f"breakdown[{kind}] не строка: {type(val)}"


# ───────────────────────── пустой период → нули ─────────────────────────


async def test_cashflow_empty_period_zeros(session, api):
    """Нет данных → нули (не 500)."""
    r = await api.get("/finance/cashflow?period_from=2000-01-01&period_to=2000-01-31")
    assert r.status_code == 200
    body = r.json()
    assert body["inflows"] == "0.00"
    assert body["outflows"] == "0.00"
    assert body["net_cashflow"] == "0.00"
    assert body["bank_balance"] is None
