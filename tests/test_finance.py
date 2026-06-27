"""Тесты модуля Finance: lifecycle, allocations, aging, cost-center, fx, cashflow, margin, reconcile."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.services.eventbus import EventContext, OutboxEventBus
from modules.finance.models import Payment


def _ctx(session):
    return EventContext(session=session, services=SimpleNamespace(event_bus=OutboxEventBus()))


# ───────────────────────── P1: lifecycle (due_date / paid_at / overdue) ─────────────────────────


async def test_invoice_with_due_date_and_provenance(session):
    from modules.finance.events import on_document_posted

    await on_document_posted(
        {
            "kind": "invoice",
            "number": "СЧ-100",
            "amount": 1000,
            "deal_id": 42,
            "counterparty_ref": "УНП-123",
            "due_date": "2026-07-15",
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment))).scalars().one()
    assert p.deal_id == 42 and p.counterparty_ref == "УНП-123"
    assert p.due_date == date(2026, 7, 15)
    assert p.status == "pending" and p.paid_at is None


async def test_invoice_without_due_date_is_honest_empty(session):
    from modules.finance.events import on_document_posted

    await on_document_posted(
        {"kind": "invoice", "number": "СЧ-101", "amount": 500}, _ctx(session)
    )
    await session.commit()
    p = (await session.execute(select(Payment))).scalars().one()
    assert p.due_date is None  # не выдумываем срок
    assert p.deal_id is None and p.counterparty_ref is None


async def test_payment_paid_sets_paid_at_and_emits(session, api):
    from core.domain.models import OutboxEvent

    session.add(Payment(ref="СЧ-1", amount=Decimal("100"), status="pending", kind="receivable"))
    await session.commit()
    pid = (await session.execute(select(Payment.id))).scalar_one()
    r = await api.patch(f"/finance/payments/{pid}", json={"status": "paid"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paid" and body["paid_at"] is not None
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.paid" in types


async def test_payment_is_overdue_computed_on_read(session, api):
    yesterday = date.today() - timedelta(days=5)
    session.add(
        Payment(
            ref="СЧ-OVERDUE",
            amount=Decimal("200"),
            status="pending",
            kind="receivable",
            due_date=yesterday,
        )
    )
    session.add(
        Payment(
            ref="СЧ-FUTURE",
            amount=Decimal("300"),
            status="pending",
            kind="receivable",
            due_date=date.today() + timedelta(days=30),
        )
    )
    await session.commit()
    r = await api.get("/finance/payments")
    rows = {p["ref"]: p for p in r.json()}
    assert rows["СЧ-OVERDUE"]["is_overdue"] is True
    assert rows["СЧ-FUTURE"]["is_overdue"] is False
    # overdue не хранится в статусе (статус остаётся pending)
    assert rows["СЧ-OVERDUE"]["status"] == "pending"


# ───────────────────────── P2: allocations (частичная оплата) ─────────────────────────


async def test_two_partial_allocations_close_invoice(session, api):
    from core.domain.models import OutboxEvent

    session.add(Payment(ref="СЧ-PART", amount=Decimal("1000"), status="pending", kind="receivable"))
    await session.commit()
    pid = (await session.execute(select(Payment.id))).scalar_one()

    # 1: 400 → partial, события paid нет
    r1 = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": 400})
    assert r1.status_code == 201
    detail1 = (await api.get(f"/finance/payments/{pid}")).json()
    assert detail1["status"] == "partial" and detail1["outstanding"] == 600.0
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.paid" not in types

    # 2: 600 → paid, событие финиш-оплаты
    r2 = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": 600})
    assert r2.status_code == 201
    detail2 = (await api.get(f"/finance/payments/{pid}")).json()
    assert detail2["status"] == "paid" and detail2["outstanding"] == 0.0
    assert len(detail2["allocations"]) == 2
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.paid" in types


async def test_allocation_amount_must_be_positive(session, api):
    session.add(Payment(ref="СЧ-X", amount=Decimal("100"), status="pending", kind="receivable"))
    await session.commit()
    pid = (await session.execute(select(Payment.id))).scalar_one()
    r = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": 0})
    assert r.status_code == 400


# ───────────────────────── P11: landed-маржа из qty+unit / total_landed_byn ─────────────────────────


async def test_landed_uses_total_landed_byn_when_present(session):
    """Закупки эмитят total_landed_byn (предпочтительный путь, точный для landed-маржи)."""
    from modules.finance.events import on_landed_cost

    # реальный payload закупок (procurement/routes.py:230): qty+unit+total строками
    await on_landed_cost(
        {
            "sku_code": "S-X",
            "unit_landed_cost_byn": "15.0000",
            "qty": "10",
            "total_landed_byn": "150.00",  # предпочтительнее, если есть
            "deal_id": 7,
            "entity_ref": "purchase_order:3",
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "landed"))).scalars().one()
    assert float(p.amount) == 150.0 and p.deal_id == 7


async def test_landed_falls_back_to_unit_times_qty(session):
    """Если total нет — используем unit×qty (закупки могут не прислать total в старых эмитах)."""
    from modules.finance.events import on_landed_cost

    await on_landed_cost(
        {"sku_code": "S-Y", "unit_landed_cost_byn": "12", "qty": "5"}, _ctx(session)
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "landed"))).scalars().one()
    assert float(p.amount) == 60.0


# ───────────────────────── P3: AR/AP aging ─────────────────────────


async def _seed_aging(session):
    today = date.today()
    session.add_all([
        # AR
        Payment(ref="AR-CUR", amount=Decimal("100"), kind="receivable", status="pending",
                due_date=today + timedelta(days=10)),
        Payment(ref="AR-15", amount=Decimal("200"), kind="receivable", status="pending",
                due_date=today - timedelta(days=15)),
        Payment(ref="AR-45", amount=Decimal("300"), kind="receivable", status="pending",
                due_date=today - timedelta(days=45)),
        Payment(ref="AR-NO", amount=Decimal("50"), kind="receivable", status="pending"),
        Payment(ref="AR-PAID", amount=Decimal("999"), kind="receivable", status="paid",
                due_date=today - timedelta(days=200)),  # paid → не в aging
        # AP
        Payment(ref="FR-100", amount=Decimal("400"), kind="freight", status="pending",
                due_date=today - timedelta(days=100)),
        Payment(ref="LN-CUR", amount=Decimal("500"), kind="landed", status="pending",
                due_date=today + timedelta(days=5)),
    ])
    await session.commit()


async def test_aging_buckets_split_correctly(session):
    from modules.finance.aging import aging_buckets

    await _seed_aging(session)
    r = await aging_buckets(session)
    assert r["currency"] == "BYN"
    ar = r["ar"]["buckets"]
    assert ar["current"] == 100.0
    assert ar["1-30"] == 200.0
    assert ar["31-60"] == 300.0
    assert ar["no_due"] == 50.0
    assert r["ar"]["total"] == 650.0
    ap = r["ap"]["buckets"]
    assert ap["90+"] == 400.0 and ap["current"] == 500.0


async def test_aging_empty(session):
    from modules.finance.aging import aging_buckets

    r = await aging_buckets(session)
    assert r["ar"]["total"] == 0.0 and r["ap"]["total"] == 0.0


# ───────────────────────── P4: cost center ─────────────────────────


async def test_cost_center_default_from_kind(session):
    from modules.finance.cost_center import group_by_cost_center

    session.add_all([
        Payment(ref="r1", amount=Decimal("1000"), kind="receivable", status="paid"),
        Payment(ref="l1", amount=Decimal("600"), kind="landed", status="pending"),
        Payment(ref="f1", amount=Decimal("100"), kind="freight", status="pending"),
        Payment(ref="x1", amount=Decimal("70"), kind="landed", status="paid", cost_center="Спец"),
    ])
    await session.commit()
    r = await group_by_cost_center(session)
    by = {c["name"]: c for c in r["centers"]}
    assert by["Продажи"]["income"] == 1000.0
    assert by["Закупки"]["expense"] == 600.0
    assert by["Логистика"]["expense"] == 100.0
    assert by["Спец"]["expense"] == 70.0


async def test_cost_center_empty_is_honest(session):
    from modules.finance.cost_center import group_by_cost_center

    r = await group_by_cost_center(session)
    assert r["centers"] == []


# ───────────────────────── P5: FX-буфер ─────────────────────────


def test_fx_byn_is_identity():
    from modules.finance.fx import to_byn

    assert to_byn(100, "BYN") == Decimal("100")
    assert to_byn(50, None) == Decimal("50")  # None == BYN


def test_fx_usd_converted_with_buffer():
    from modules.finance.fx import FX_BUFFER, RATES, to_byn

    # 100 USD × 3.30 × 1.10 = 363.00
    expected = (Decimal("100") * RATES["USD"] * FX_BUFFER).quantize(Decimal("0.01"))
    assert to_byn(100, "USD") == expected


def test_fx_unknown_currency_raises():
    from modules.finance.fx import UnknownCurrency, to_byn

    with pytest.raises(UnknownCurrency):
        to_byn(10, "JPY")


async def test_landed_with_foreign_currency_stores_byn_and_orig(session):
    from modules.finance.events import on_landed_cost
    from modules.finance.fx import FX_BUFFER, RATES

    await on_landed_cost(
        {
            "sku_code": "S1",
            "amount": "100",
            "currency": "USD",
            "entity_ref": "purchase:7",
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "landed"))).scalars().one()
    expected_byn = (Decimal("100") * RATES["USD"] * FX_BUFFER).quantize(Decimal("0.01"))
    assert Decimal(str(p.amount)) == expected_byn
    assert p.currency == "USD" and Decimal(str(p.amount_orig)) == Decimal("100")


async def test_landed_byn_keeps_amount_orig_none(session):
    from modules.finance.events import on_landed_cost

    await on_landed_cost(
        {"sku_code": "S2", "amount": "200", "currency": "BYN"}, _ctx(session)
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "landed"))).scalars().one()
    assert p.amount_orig is None and p.currency == "BYN"


# ───────────────────────── P6: cash-flow forecast ─────────────────────────


async def test_cashflow_forecast_groups_by_week_with_cumulative(session):
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)  # среда
    # opening_balance: оплачено 500 receivable, оплачено 100 freight → 400
    session.add(Payment(ref="paid-in", amount=Decimal("500"), kind="receivable", status="paid"))
    session.add(Payment(ref="paid-out", amount=Decimal("100"), kind="freight", status="paid"))
    # неделя 0 (с понедельника 2026-06-29): inflow 200
    session.add(Payment(ref="in-w0", amount=Decimal("200"), kind="receivable", status="pending",
                        due_date=date(2026, 7, 3)))
    # неделя 1 (2026-07-06): outflow 150
    session.add(Payment(ref="out-w1", amount=Decimal("150"), kind="landed", status="pending",
                        due_date=date(2026, 7, 8)))
    # без срока
    session.add(Payment(ref="no-due", amount=Decimal("777"), kind="receivable", status="pending"))
    await session.commit()
    r = await cashflow_forecast(session, weeks=3, today=today)
    assert r["opening_balance"] == 400.0
    weeks = r["weeks"]
    assert weeks[0]["inflow"] == 200.0 and weeks[0]["outflow"] == 0.0
    assert weeks[0]["net"] == 200.0 and weeks[0]["cumulative"] == 600.0
    assert weeks[1]["outflow"] == 150.0 and weeks[1]["cumulative"] == 450.0
    assert weeks[2]["cumulative"] == 450.0  # пустая неделя — кумулятив сохраняется
    assert r["not_dated"]["inflow"] == 777.0


# ───────────────────────── P7: margin by deal / counterparty ─────────────────────────


async def test_margin_by_deal_ranks_and_isolates_unattributed(session):
    from modules.finance.margin import margin_by_deal

    session.add_all([
        Payment(ref="r-d1", amount=Decimal("1000"), kind="receivable", status="paid", deal_id=1),
        Payment(ref="l-d1", amount=Decimal("400"), kind="landed", status="pending", deal_id=1),
        Payment(ref="f-d1", amount=Decimal("100"), kind="freight", status="pending", deal_id=1),
        Payment(ref="r-d2", amount=Decimal("500"), kind="receivable", status="pending", deal_id=2),
        Payment(ref="l-d2", amount=Decimal("450"), kind="landed", status="pending", deal_id=2),
        Payment(ref="r-na", amount=Decimal("999"), kind="receivable", status="pending"),
    ])
    await session.commit()
    r = await margin_by_deal(session)
    by_key = {row["key"]: row for row in r["items"]}
    # deal 1: 1000 - 400 - 100 = 500 (50%), deal 2: 500 - 450 = 50 (10%)
    assert by_key[1]["gross"] == 500.0 and by_key[1]["pct"] == 50.0
    assert by_key[2]["gross"] == 50.0 and by_key[2]["pct"] == 10.0
    # неатрибутированное — в конце независимо от gross
    assert r["items"][-1]["key"] is None
    assert r["items"][-1]["gross"] == 999.0


async def test_margin_by_counterparty_groups(session):
    from modules.finance.margin import margin_by_counterparty

    session.add_all([
        Payment(ref="r-cp1", amount=Decimal("800"), kind="receivable",
                status="paid", counterparty_ref="УНП-1"),
        Payment(ref="l-cp1", amount=Decimal("300"), kind="landed",
                status="pending", counterparty_ref="УНП-1"),
    ])
    await session.commit()
    r = await margin_by_counterparty(session)
    assert r["items"][0]["key"] == "УНП-1"
    assert r["items"][0]["gross"] == 500.0


# ───────────────────────── P8: reconcile-1c (fail-soft) ─────────────────────────


async def test_reconcile_1c_without_gateway_is_honest(session):
    from modules.finance.reconcile import reconcile_with_onec

    r = await reconcile_with_onec(session, None)
    assert r["source_available"] is False
    assert r["matched"] == [] and r["only_in_erp"] == [] and r["only_in_1c"] == []


async def test_reconcile_1c_with_mock_gateway(session):
    from modules.finance.reconcile import reconcile_with_onec

    session.add_all([
        Payment(ref="СЧ-1", amount=Decimal("100"), kind="receivable",
                status="pending", counterparty_ref="УНП-1"),
        Payment(ref="СЧ-ONLY-ERP", amount=Decimal("200"), kind="receivable", status="pending"),
    ])
    await session.commit()

    class _Mock1C:
        async def fetch_payments(self):
            return [
                {"ref": "СЧ-1", "amount": 100, "counterparty_ref": "УНП-1"},
                {"ref": "СЧ-ONLY-1C", "amount": 50, "counterparty_ref": None},
            ]

    r = await reconcile_with_onec(session, _Mock1C())
    assert r["source_available"] is True
    refs_matched = {m["ref"] for m in r["matched"]}
    refs_only_erp = {m["ref"] for m in r["only_in_erp"]}
    refs_only_1c = {m["ref"] for m in r["only_in_1c"]}
    assert refs_matched == {"СЧ-1"}
    assert refs_only_erp == {"СЧ-ONLY-ERP"}
    assert refs_only_1c == {"СЧ-ONLY-1C"}


async def test_reconcile_1c_failsoft_on_exception(session):
    from modules.finance.reconcile import reconcile_with_onec

    class _Broken:
        async def fetch_payments(self):
            raise RuntimeError("1C down")

    r = await reconcile_with_onec(session, _Broken())
    assert r["source_available"] is False
