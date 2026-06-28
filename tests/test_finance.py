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


# ───────────────────────── Круг 3 ─────────────────────────


# FIN-C1: claim.resolved → claim_refund (УЖЕ BYN, без fx)


async def test_claim_resolved_creates_claim_refund_credit(session):
    from modules.finance.events import on_claim_resolved

    await on_claim_resolved(
        {
            "claim_id": 11,
            "supplier_id": 555,
            "claim_type": "брак",
            "amount_byn": "350.00",  # СТРОКА, УЖЕ в BYN
            "resolution": "resolved",
            "status": "resolved",
            "entity_ref": "claim:11",
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "claim_refund"))).scalars().one()
    assert p.amount == Decimal("350.00")  # AS-IS, без буфера ×1.10
    assert p.status == "pending"
    assert p.counterparty_ref == "555"  # supplier_id строкой


async def test_claim_rejected_creates_nothing(session):
    from modules.finance.events import on_claim_resolved

    await on_claim_resolved(
        {"claim_id": 12, "supplier_id": 555, "amount_byn": "100", "resolution": "rejected"},
        _ctx(session),
    )
    await session.commit()
    rows = (await session.execute(select(Payment))).scalars().all()
    assert rows == []


async def test_claim_zero_amount_creates_nothing(session):
    from modules.finance.events import on_claim_resolved

    await on_claim_resolved(
        {"claim_id": 13, "supplier_id": 1, "amount_byn": "0", "resolution": "resolved"},
        _ctx(session),
    )
    await session.commit()
    rows = (await session.execute(select(Payment))).scalars().all()
    assert rows == []


# FIN-C2: FX в on_freight_refund (USD/BYN/неизвестная валюта)


async def test_freight_refund_usd_applies_fx_buffer(session):
    from modules.finance.events import on_freight_refund
    from modules.finance.fx import FX_BUFFER, RATES

    await on_freight_refund(
        {"shipment_code": "SH-1", "amount": "50", "currency": "USD", "entity_ref": "audit:1"},
        _ctx(session),
    )
    await session.commit()
    p = (
        await session.execute(select(Payment).where(Payment.kind == "freight_refund"))
    ).scalars().one()
    expected_byn = (Decimal("50") * RATES["USD"] * FX_BUFFER).quantize(Decimal("0.01"))
    assert p.amount == -expected_byn  # хранится ОТРИЦАТЕЛЬНОЙ — кредит против фрахта
    assert p.currency == "USD"
    assert Decimal(str(p.amount_orig)) == Decimal("50")


async def test_freight_refund_byn_keeps_amount_orig_none(session):
    from modules.finance.events import on_freight_refund

    await on_freight_refund(
        {"shipment_code": "SH-2", "amount": "75", "currency": "BYN"}, _ctx(session)
    )
    await session.commit()
    p = (
        await session.execute(select(Payment).where(Payment.kind == "freight_refund"))
    ).scalars().one()
    assert p.amount == Decimal("-75")
    assert p.amount_orig is None and p.currency == "BYN"


async def test_freight_refund_unknown_currency_skips(session):
    from modules.finance.events import on_freight_refund

    await on_freight_refund(
        {"shipment_code": "SH-3", "amount": "10", "currency": "JPY"}, _ctx(session)
    )
    await session.commit()
    rows = (
        await session.execute(select(Payment).where(Payment.kind == "freight_refund"))
    ).scalars().all()
    assert rows == []  # не упало, проводки нет


# FIN-A2: finance.payment.created amount → str (точность денег)


async def test_payment_created_emits_amount_as_string(session):
    from core.domain.models import OutboxEvent
    from modules.finance.events import on_document_posted

    await on_document_posted(
        {"kind": "invoice", "number": "СЧ-D", "amount": "1234.56", "deal_id": 1},
        _ctx(session),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    created = [e for e in events if e.event_type == "finance.payment.created"]
    assert len(created) == 1
    raw_amount = created[0].payload["amount"]
    assert isinstance(raw_amount, str)  # не float!
    # копейки восстанавливаются без дрейфа
    assert Decimal(raw_amount) == Decimal("1234.56")


# FIN-B1: procurement.po.drafted → po_planned (status=planned, due_date=eta)


async def test_po_drafted_creates_planned_payment(session):
    from modules.finance.events import on_po_drafted

    await on_po_drafted(
        {
            "po_ref": "PO-2025-001",
            "supplier_id": 77,
            "planned_amount": "5000.00",
            "currency": "BYN",
            "eta_date": "2026-08-01",
            "deal_id": None,
        },
        _ctx(session),
    )
    await session.commit()
    p = (await session.execute(select(Payment).where(Payment.kind == "po_planned"))).scalars().one()
    assert p.status == "planned"
    assert p.due_date == date(2026, 8, 1)
    assert p.amount == Decimal("5000.00")
    assert p.counterparty_ref == "77"


async def test_po_drafted_zero_amount_skipped(session):
    from modules.finance.events import on_po_drafted

    await on_po_drafted(
        {"po_ref": "PO-X", "supplier_id": 1, "planned_amount": "0"}, _ctx(session)
    )
    await session.commit()
    rows = (await session.execute(select(Payment))).scalars().all()
    assert rows == []


async def test_cashflow_includes_po_planned_in_outflow(session):
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)
    # PO на 800 со сроком в неделе 1 (понедельник 2026-07-06 → 2026-07-08)
    session.add(
        Payment(
            ref="po:PO-A",
            amount=Decimal("800"),
            kind="po_planned",
            status="planned",
            due_date=date(2026, 7, 8),
        )
    )
    await session.commit()
    r = await cashflow_forecast(session, weeks=3, today=today)
    assert r["weeks"][1]["outflow"] == 800.0


async def test_aging_does_not_include_po_planned(session):
    from modules.finance.aging import aging_buckets

    today = date.today()
    session.add(
        Payment(
            ref="po:OLD",
            amount=Decimal("500"),
            kind="po_planned",
            status="planned",
            due_date=today - timedelta(days=120),  # был бы overdue, но не AR/AP
        )
    )
    await session.commit()
    r = await aging_buckets(session)
    assert r["ar"]["total"] == 0.0 and r["ap"]["total"] == 0.0  # planned НЕ в overdue


# FIN-A3: claim_refund в summary и margin; po_planned НЕ в марже


async def test_summary_claim_refund_reduces_net_landed(session):
    from modules.finance.summary import finance_summary

    session.add_all([
        Payment(ref="r1", amount=Decimal("1500"), kind="receivable", status="paid"),
        Payment(ref="l1", amount=Decimal("1000"), kind="landed", status="pending"),
        Payment(ref="c1", amount=Decimal("200"), kind="claim_refund", status="pending"),
    ])
    await session.commit()
    r = await finance_summary(session)
    # net_landed = 1000 − 200 = 800; gross = 1500 − 800 = 700
    assert r["margin"]["landed"] == 800.0
    assert r["margin"]["claim_refund"] == 200.0
    assert r["margin"]["gross"] == 700.0


async def test_margin_by_deal_subtracts_claim_refund_and_excludes_po_planned(session):
    from modules.finance.margin import margin_by_deal

    session.add_all([
        Payment(ref="r-d1", amount=Decimal("1500"), kind="receivable", status="paid", deal_id=1),
        Payment(ref="l-d1", amount=Decimal("1000"), kind="landed", status="pending", deal_id=1),
        Payment(ref="c-d1", amount=Decimal("200"), kind="claim_refund",
                status="pending", deal_id=1),
        # po_planned — НЕ в маржу
        Payment(ref="po-d1", amount=Decimal("999"), kind="po_planned",
                status="planned", deal_id=1, due_date=date(2026, 8, 1)),
    ])
    await session.commit()
    r = await margin_by_deal(session)
    row = next(it for it in r["items"] if it["key"] == 1)
    assert row["landed"] == 800.0  # 1000 − 200
    assert row["gross"] == 700.0  # 1500 − 800 (po_planned игнор)


# FIN-A1: reconcile_deal_margin (finance ↔ facade)


async def test_reconcile_deal_margin_match_when_facade_equals_finance(session):
    from modules.finance.margin import reconcile_deal_margin

    session.add_all([
        Payment(ref="r-1", amount=Decimal("1500"), kind="receivable", status="paid", deal_id=42),
        Payment(ref="l-1", amount=Decimal("1000"), kind="landed", status="pending", deal_id=42),
    ])
    await session.commit()

    class _Facade:
        async def last_landed_cost_batch(self, _s, codes):
            return {c: {"unit_landed_cost_byn": "1000"} for c in codes}

    r = await reconcile_deal_margin(
        session, _Facade(), deal_id=42, items={"SKU-X": Decimal("1")}
    )
    assert r["source_facade_available"] is True
    assert r["finance_landed"] == 1000.0
    assert r["facade_landed"] == 1000.0
    assert r["delta"] == 0.0


async def test_reconcile_deal_margin_mismatch_detected(session):
    from modules.finance.margin import reconcile_deal_margin

    session.add(
        Payment(ref="l-2", amount=Decimal("800"), kind="landed",
                status="pending", deal_id=43)
    )
    await session.commit()

    class _Facade:
        async def last_landed_cost_batch(self, _s, codes):
            return {c: {"unit_landed_cost_byn": "500"} for c in codes}  # 500 vs 800

    r = await reconcile_deal_margin(
        session, _Facade(), deal_id=43, items={"S": Decimal("1")}
    )
    assert r["delta"] == 300.0  # 800 − 500


async def test_reconcile_deal_margin_facade_off_honest(session):
    from modules.finance.margin import reconcile_deal_margin

    session.add(
        Payment(ref="l-3", amount=Decimal("100"), kind="landed",
                status="pending", deal_id=44)
    )
    await session.commit()
    r = await reconcile_deal_margin(session, None, deal_id=44, items={"S": Decimal("1")})
    assert r["source_facade_available"] is False
    assert r["facade_landed"] is None
    assert r["delta"] is None
    assert r["finance_landed"] == 100.0  # finance всё равно отдаётся


async def test_reconcile_deal_margin_no_items_honest(session):
    from modules.finance.margin import reconcile_deal_margin

    class _Facade:
        async def last_landed_cost_batch(self, _s, codes):
            return {}

    r = await reconcile_deal_margin(session, _Facade(), deal_id=99, items={})
    assert r["source_facade_available"] is False  # без sku → нечего сверять
    assert r["finance_landed"] == 0.0  # сделки не было → 0 honest


# FIN-C5: cost_center учитывает claim_refund (доход в центр Закупки) и игнорит po_planned


async def test_cost_center_includes_claim_refund_and_excludes_po_planned(session):
    from modules.finance.cost_center import group_by_cost_center

    session.add_all([
        Payment(ref="l", amount=Decimal("1000"), kind="landed", status="pending"),
        Payment(ref="c", amount=Decimal("200"), kind="claim_refund", status="pending"),
        Payment(ref="po", amount=Decimal("9999"), kind="po_planned", status="planned"),
    ])
    await session.commit()
    r = await group_by_cost_center(session)
    by = {c["name"]: c for c in r["centers"]}
    # Закупки: expense=1000, income=200 (компенсация); po_planned игнорится
    assert by["Закупки"]["expense"] == 1000.0
    assert by["Закупки"]["income"] == 200.0


# ───────────────────────── Круг 4: Платёжный календарь ─────────────────────────


# FIN-R4-1: дневной режим cashflow + кумулятив


async def test_cashflow_day_mode_buckets_by_date(session):
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)
    session.add(
        Payment(ref="in-d1", amount=Decimal("300"), kind="receivable", status="pending",
                due_date=date(2026, 7, 2))
    )
    session.add(
        Payment(ref="out-d4", amount=Decimal("100"), kind="landed", status="pending",
                due_date=date(2026, 7, 5))
    )
    await session.commit()
    r = await cashflow_forecast(session, days=10, mode="day", today=today)
    assert r["mode"] == "day"
    assert r["bucket_size_days"] == 1
    by_date = {b["bucket_start"]: b for b in r["buckets"]}
    assert by_date["2026-07-02"]["inflow"] == 300.0
    assert by_date["2026-07-05"]["outflow"] == 100.0
    # кумулятив растёт на приток, уменьшается на отток
    assert by_date["2026-07-02"]["cumulative"] == by_date["2026-07-01"]["cumulative"] + 300.0


async def test_cashflow_week_mode_backward_compatible(session):
    """Старый клиент с `weeks` алиасом не сломается (мы рендерим week_start в weeks[])."""
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)
    r = await cashflow_forecast(session, weeks=4, mode="week", today=today)
    assert r["mode"] == "week"
    assert r["bucket_size_days"] == 7
    assert len(r["weeks"]) == 4
    assert "week_start" in r["weeks"][0]  # legacy field
    assert "bucket_start" in r["buckets"][0]  # canonical


# FIN-R4-2/3: BankAccount + account_id фильтр


async def test_cashflow_account_filter(session):
    from modules.finance.cashflow import cashflow_forecast
    from modules.finance.models import BankAccount

    acc_main = BankAccount(code="main", title="Основной", currency="BYN",
                           opening_balance=Decimal("1000"))
    acc_cny = BankAccount(code="cny", title="Валюта", currency="CNY")
    session.add_all([acc_main, acc_cny])
    await session.flush()

    today = date(2026, 7, 1)
    # Счёт main: 500 приток
    session.add(
        Payment(ref="m-in", amount=Decimal("500"), kind="receivable", status="pending",
                due_date=date(2026, 7, 2), account_id=acc_main.id)
    )
    # Счёт cny: 200 приток (не должен попасть в выборку main)
    session.add(
        Payment(ref="c-in", amount=Decimal("200"), kind="receivable", status="pending",
                due_date=date(2026, 7, 2), account_id=acc_cny.id)
    )
    # Без счёта: 999 — общий кэш, не суммируется в main
    session.add(
        Payment(ref="no-acc", amount=Decimal("999"), kind="receivable", status="pending",
                due_date=date(2026, 7, 2))
    )
    await session.commit()

    r_main = await cashflow_forecast(
        session, days=5, mode="day", today=today, account_id=acc_main.id
    )
    by = {b["bucket_start"]: b for b in r_main["buckets"]}
    assert by["2026-07-02"]["inflow"] == 500.0  # только main
    # opening_balance = paid_recv(0) − paid_out(0) + BankAccount.opening(1000) = 1000
    assert r_main["opening_balance"] == 1000.0

    # Без фильтра — все три (общий кэш + main + cny)
    r_all = await cashflow_forecast(session, days=5, mode="day", today=today)
    by_all = {b["bucket_start"]: b for b in r_all["buckets"]}
    assert by_all["2026-07-02"]["inflow"] == 1699.0  # 500 + 200 + 999
