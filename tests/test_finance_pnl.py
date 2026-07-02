"""Тесты Finance Р5 — P&L: hr.payroll.*, sales.deal.handoff, /finance/pnl."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from core.services.eventbus import EventContext, OutboxEventBus
from modules.finance.models import Payment


def _ctx(session):
    return EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


# ───────────────────────── HR: payroll ─────────────────────────


async def test_payroll_accrued_creates_pending_payment(session):
    """hr.payroll.accrued → Payment(kind=payroll, status=pending)."""
    from modules.finance.events import on_payroll_accrued

    await on_payroll_accrued(
        {
            "employee_id": 1,
            "employee_name": "Иванов И.И.",
            "period": "2026-06",
            "amount_byn": "3500.00",
            "entity_ref": "payroll:42",
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "payroll"))).scalars().one()
    assert p.status == "pending"
    assert p.amount == Decimal("3500.00")
    assert p.entity_ref == "payroll:42"
    assert "Иванов" in (p.description or "")


async def test_payroll_paid_closes_by_entity_ref(session):
    """hr.payroll.paid → находит Payment по entity_ref и переводит в paid."""
    from modules.finance.events import on_payroll_accrued, on_payroll_paid

    ctx = _ctx(session)
    await on_payroll_accrued(
        {
            "employee_id": 2,
            "employee_name": "Петров П.П.",
            "period": "2026-06",
            "amount_byn": "2000.00",
            "entity_ref": "payroll:55",
        },
        ctx,
    )
    await session.commit()

    await on_payroll_paid(
        {"employee_id": 2, "period": "2026-06", "amount_byn": "2000.00", "entity_ref": "payroll:55"},
        ctx,
    )
    await session.commit()

    p = (
        await session.execute(select(Payment).where(Payment.entity_ref == "payroll:55"))
    ).scalars().one()
    assert p.status == "paid"


async def test_payroll_paid_missing_entity_ref_is_noop(session):
    """hr.payroll.paid без совпадающего entity_ref — тихо игнорируем."""
    from modules.finance.events import on_payroll_paid

    await on_payroll_paid(
        {"employee_id": 99, "period": "2026-06", "amount_byn": "0", "entity_ref": "payroll:9999"},
        _ctx(session),
    )
    await session.commit()
    rows = (await session.execute(select(Payment))).scalars().all()
    assert len(rows) == 0


# ───────────────────────── Sales: deal.handoff (accrual) ─────────────────────────


async def test_deal_handoff_creates_revenue_recognized(session):
    """sales.deal.handoff → Payment(kind=revenue_recognized, status=pending, entity_ref=deal:<id>)."""
    from modules.finance.events import on_deal_handoff

    await on_deal_handoff(
        {"deal_id": 10, "amount": 50000.0, "number": "СД-10"},
        _ctx(session),
    )
    await session.commit()
    p = (
        await session.execute(select(Payment).where(Payment.kind == "revenue_recognized"))
    ).scalars().one()
    assert p.amount == Decimal("50000.00")
    assert p.entity_ref == "deal:10"
    assert p.deal_id == 10


async def test_deal_handoff_idempotent_no_duplicate(session):
    """Повторный sales.deal.handoff с тем же deal_id не создаёт дубль."""
    from modules.finance.events import on_deal_handoff

    ctx = _ctx(session)
    payload = {"deal_id": 20, "amount": "12000.50", "number": "СД-20"}
    await on_deal_handoff(payload, ctx)
    await session.commit()
    await on_deal_handoff(payload, ctx)  # второй раз
    await session.commit()

    rows = (
        await session.execute(
            select(Payment).where(
                Payment.entity_ref == "deal:20", Payment.kind == "revenue_recognized"
            )
        )
    ).scalars().all()
    assert len(rows) == 1  # ровно одна запись


async def test_deal_handoff_zero_amount_ignored(session):
    """Нулевая сумма handoff — игнор (honest-empty)."""
    from modules.finance.events import on_deal_handoff

    await on_deal_handoff({"deal_id": 30, "amount": 0}, _ctx(session))
    await session.commit()
    rows = (await session.execute(select(Payment))).scalars().all()
    assert len(rows) == 0


# ───────────────────────── /finance/pnl агрегат ─────────────────────────


async def test_pnl_aggregates_correctly(session, api):
    """GET /finance/pnl суммирует статьи верно и возвращает строки."""
    # Выручка (accrual, kind=revenue_recognized)
    session.add(
        Payment(ref="h1", amount=Decimal("100000"), status="pending", kind="revenue_recognized")
    )
    # Себестоимость (landed)
    session.add(Payment(ref="l1", amount=Decimal("60000"), status="pending", kind="landed"))
    # Фрахт
    session.add(Payment(ref="f1", amount=Decimal("5000"), status="pending", kind="freight"))
    # Возврат фрахта (отрицательный)
    session.add(Payment(ref="fr1", amount=Decimal("-1000"), status="pending", kind="freight_refund"))
    # ФОТ
    session.add(
        Payment(
            ref="p1",
            amount=Decimal("10000"),
            status="pending",
            kind="payroll",
            entity_ref="payroll:1",
        )
    )
    # Opex
    session.add(Payment(ref="o1", amount=Decimal("2000"), status="pending", kind="opex"))
    # Налог
    session.add(Payment(ref="t1", amount=Decimal("1500"), status="pending", kind="tax"))
    # Банк
    session.add(Payment(ref="b1", amount=Decimal("300"), status="pending", kind="bank_fee"))
    await session.commit()

    r = await api.get("/finance/pnl?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()

    # revenue = 100000; cogs = 60000; freight = 5000 + (-1000) = 4000
    # payroll = 10000; opex = 2000; tax = 1500; bank_fee = 300
    # op_profit = 100000 - 60000 - 4000 - 10000 - 2000 - 1500 - 300 = 22200
    assert body["revenue"] == "100000.00"
    assert body["cogs"] == "60000.00"
    assert body["freight"] == "4000.00"
    assert body["payroll"] == "10000.00"
    assert body["opex"] == "2000.00"
    assert body["tax"] == "1500.00"
    assert body["bank_fee"] == "300.00"
    assert body["operating_profit"] == "22200.00"


async def test_pnl_values_are_strings_not_floats(session, api):
    """Деньги в /finance/pnl — строки (не float)."""
    session.add(
        Payment(ref="h2", amount=Decimal("1000"), status="pending", kind="revenue_recognized")
    )
    await session.commit()

    r = await api.get("/finance/pnl?period_from=2000-01-01&period_to=2099-12-31")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "revenue",
        "cogs",
        "freight",
        "payroll",
        "opex",
        "tax",
        "bank_fee",
        "operating_profit",
    ):
        assert isinstance(body[field], str), f"{field} не строка: {type(body[field])}"


async def test_pnl_empty_period_returns_zeros(session, api):
    """Нет данных за период → все нули (honest-empty)."""
    r = await api.get("/finance/pnl?period_from=2000-01-01&period_to=2000-01-31")
    assert r.status_code == 200
    body = r.json()
    assert body["revenue"] == "0.00"
    assert body["operating_profit"] == "0.00"


async def test_pnl_bad_date_returns_400(session, api):
    """Некорректная дата → 400."""
    r = await api.get("/finance/pnl?period_from=bad&period_to=2026-12-31")
    assert r.status_code == 400


async def test_pnl_csv_format(session, api):
    """?format=csv возвращает Content-Type text/csv."""
    r = await api.get("/finance/pnl?period_from=2000-01-01&period_to=2099-12-31&format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
