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
    assert detail1["status"] == "partial" and detail1["outstanding"] == "600.00"
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.paid" not in types

    # 2: 600 → paid, событие финиш-оплаты
    r2 = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": 600})
    assert r2.status_code == 201
    detail2 = (await api.get(f"/finance/payments/{pid}")).json()
    assert detail2["status"] == "paid" and detail2["outstanding"] == "0.00"
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
    assert ar["current"] == "100.00"
    assert ar["1-30"] == "200.00"
    assert ar["31-60"] == "300.00"
    assert ar["no_due"] == "50.00"
    assert r["ar"]["total"] == "650.00"
    ap = r["ap"]["buckets"]
    assert ap["90+"] == "400.00" and ap["current"] == "500.00"


async def test_aging_empty(session):
    from modules.finance.aging import aging_buckets

    r = await aging_buckets(session)
    assert r["ar"]["total"] == "0.00" and r["ap"]["total"] == "0.00"


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
    assert by["Продажи"]["income"] == "1000.00"
    assert by["Закупки"]["expense"] == "600.00"
    assert by["Логистика"]["expense"] == "100.00"
    assert by["Спец"]["expense"] == "70.00"


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
    assert r["opening_balance"] == "400.00"
    weeks = r["weeks"]
    assert weeks[0]["inflow"] == "200.00" and weeks[0]["outflow"] == "0.00"
    assert weeks[0]["net"] == "200.00" and weeks[0]["cumulative"] == "600.00"
    assert weeks[1]["outflow"] == "150.00" and weeks[1]["cumulative"] == "450.00"
    assert weeks[2]["cumulative"] == "450.00"  # пустая неделя — кумулятив сохраняется
    assert r["not_dated"]["inflow"] == "777.00"


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
    assert by_key[1]["gross"] == "500.00" and by_key[1]["pct"] == 50.0
    assert by_key[2]["gross"] == "50.00" and by_key[2]["pct"] == 10.0
    # неатрибутированное — в конце независимо от gross
    assert r["items"][-1]["key"] is None
    assert r["items"][-1]["gross"] == "999.00"


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
    assert r["items"][0]["gross"] == "500.00"


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

    # РЕАЛЬНЫЙ контракт закупок: статус урегулирования — в `status`, а `resolution` — свободный
    # текст «как урегулировано» (String(500)). Гард обязан сверять `status`, не `resolution`.
    await on_claim_resolved(
        {
            "claim_id": 11,
            "supplier_id": 555,
            "claim_type": "брак",
            "amount_byn": "350.00",  # СТРОКА, УЖЕ в BYN
            "resolution": "возврат брака деньгами",  # свободный текст, НЕ 'resolved'
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


async def test_claim_rejected_no_refund(session):
    """rejected-претензия НЕ создаёт приток, даже если в свободном resolution оказалось 'resolved'."""
    from modules.finance.events import on_claim_resolved

    await on_claim_resolved(
        {
            "claim_id": 12,
            "supplier_id": 555,
            "amount_byn": "999.00",
            "resolution": "resolved",  # ловушка: свободный текст не должен срабатывать
            "status": "rejected",
            "entity_ref": "claim:12",
        },
        _ctx(session),
    )
    await session.commit()
    n = (await session.execute(select(Payment).where(Payment.kind == "claim_refund"))).scalars().all()
    assert n == []  # отклонённая претензия → притока нет


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
    assert r["weeks"][1]["outflow"] == "800.00"


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
    assert r["ar"]["total"] == "0.00" and r["ap"]["total"] == "0.00"  # planned НЕ в overdue


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
    assert r["margin"]["landed"] == "800.00"
    assert r["margin"]["claim_refund"] == "200.00"
    assert r["margin"]["gross"] == "700.00"


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
    assert row["landed"] == "800.00"  # 1000 − 200
    assert row["gross"] == "700.00"  # 1500 − 800 (po_planned игнор)


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
    assert r["finance_landed"] == "1000.00"
    assert r["facade_landed"] == "1000.00"
    assert r["delta"] == "0.00"


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
    assert r["delta"] == "300.00"  # 800 − 500


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
    assert r["finance_landed"] == "100.00"  # finance всё равно отдаётся


async def test_reconcile_deal_margin_no_items_honest(session):
    from modules.finance.margin import reconcile_deal_margin

    class _Facade:
        async def last_landed_cost_batch(self, _s, codes):
            return {}

    r = await reconcile_deal_margin(session, _Facade(), deal_id=99, items={})
    assert r["source_facade_available"] is False  # без sku → нечего сверять
    assert r["finance_landed"] == "0.00"  # сделки не было → 0 honest


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
    assert by["Закупки"]["expense"] == "1000.00"
    assert by["Закупки"]["income"] == "200.00"


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
    assert by_date["2026-07-02"]["inflow"] == "300.00"
    assert by_date["2026-07-05"]["outflow"] == "100.00"
    # кумулятив растёт на приток, уменьшается на отток (деньги — строки, сравниваем как Decimal)
    assert Decimal(by_date["2026-07-02"]["cumulative"]) == Decimal(
        by_date["2026-07-01"]["cumulative"]
    ) + 300


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


# ───────────────────────── Круг 4 B2: reference.*.changed → recompute landed ─────────────────────────


def _ref_ctx(session, sku_master=None):
    """EventContext с подменой sku_master фасада (для landed_inputs_batch контекста)."""
    services = SimpleNamespace(event_bus=OutboxEventBus(), sku_master=sku_master)
    return EventContext(session=session, services=services)


class _StubSkuMaster:
    """Мок фасада ядра ``core.services.sku_master`` (REF3-1) — отдаёт фиксированные inputs."""

    def __init__(self, mapping: dict[str, dict | None]):
        self.mapping = mapping
        self.calls: list[list[str]] = []

    async def landed_inputs_batch(self, _session, sku_codes):
        self.calls.append(list(sku_codes))
        return {c: self.mapping.get(c) for c in sku_codes}


async def test_reference_sku_changed_emits_recompute(session):
    """sku.changed (entity_ref='sku:S-1') → один recompute с этим sku_code и inputs."""
    from core.domain.models import OutboxEvent
    from modules.finance.events import on_reference_changed

    stub = _StubSkuMaster({"S-1": {"duty_pct": 5.0, "vat_rate": 20.0}})
    await on_reference_changed(
        {
            "action": "version",
            "ref_key": "core.skus",
            "entity_ref": "sku:S-1",
            "value_hint": "weight_kg",
            "actor": "ops",
        },
        _ref_ctx(session, sku_master=stub),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    assert len(recompute) == 1
    p = recompute[0].payload
    assert p["sku_codes"] == ["S-1"]
    assert p["ref_key"] == "core.skus"
    assert p["entity_ref"] == "sku:S-1"
    assert p["inputs"]["S-1"]["duty_pct"] == 5.0
    assert stub.calls == [["S-1"]]


async def test_reference_tnved_changed_resolves_affected_sku(session):
    """ref_tnved.changed → ищем все Sku где tnved_code совпадает; recompute со списком кодов."""
    from core.domain.models import OutboxEvent, Sku
    from modules.finance.events import on_reference_changed

    session.add_all([
        Sku(code="A-1", title="A1", tnved_code="8418400000"),
        Sku(code="A-2", title="A2", tnved_code="8418400000"),
        Sku(code="B-1", title="B1", tnved_code="9999000000"),  # не затронут
    ])
    await session.commit()
    stub = _StubSkuMaster({"A-1": {"duty_pct": 5}, "A-2": {"duty_pct": 5}})
    await on_reference_changed(
        {
            "action": "version",
            "ref_key": "core.tnved",
            "entity_ref": "ref_tnved:8418400000",
            "value_hint": "duty_rate",
            "actor": "ops",
        },
        _ref_ctx(session, sku_master=stub),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    assert len(recompute) == 1
    assert recompute[0].payload["sku_codes"] == ["A-1", "A-2"]  # отсортировано, без B-1


async def test_reference_vat_changed_resolves_affected_sku(session):
    from core.domain.models import OutboxEvent, Sku
    from modules.finance.events import on_reference_changed

    session.add_all([
        Sku(code="V-1", title="V1", vat_code="20"),
        Sku(code="V-2", title="V2", vat_code="10"),
    ])
    await session.commit()
    await on_reference_changed(
        {
            "action": "version",
            "ref_key": "core.vat_rates",
            "entity_ref": "ref_vat_rate:20",
            "actor": "ops",
        },
        _ref_ctx(session),  # без stub — inputs={} honest
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    assert recompute[0].payload["sku_codes"] == ["V-1"]
    assert recompute[0].payload["inputs"] == {}  # фасад не подключён — honest


async def test_reference_currency_rate_changed_emits_fx_signal(session):
    """FX-курс — отдельный канал finance.fx.recompute_requested (затронуты все не-BYN landed)."""
    from core.domain.models import OutboxEvent
    from modules.finance.events import on_reference_changed

    await on_reference_changed(
        {
            "action": "version",
            "ref_key": "core.currency_rates",
            "entity_ref": "ref_currency_rate:USD",
            "value_hint": "rate",
            "actor": "ops",
        },
        _ref_ctx(session),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    fx = [e for e in events if e.event_type == "finance.fx.recompute_requested"]
    assert len(fx) == 1
    assert fx[0].payload["currency_code"] == "USD"
    # И НЕ должно быть landed.recompute (для FX отдельный сигнал)
    assert all(e.event_type != "finance.landed.recompute_requested" for e in events)


async def test_reference_no_affected_sku_is_honest_silent(session):
    """ТН ВЭД не привязан ни к одному SKU → НЕТ recompute (honest-empty, не мусорим в outbox)."""
    from core.domain.models import OutboxEvent
    from modules.finance.events import on_reference_changed

    await on_reference_changed(
        {"ref_key": "core.tnved", "entity_ref": "ref_tnved:0000000000"},
        _ref_ctx(session),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert all(e.event_type != "finance.landed.recompute_requested" for e in events)


async def test_reference_unknown_kind_is_ignored(session):
    """Незнакомый справочник → пропустить, НЕ падать (honest-empty)."""
    from core.domain.models import OutboxEvent
    from modules.finance.events import on_reference_changed

    await on_reference_changed(
        {"ref_key": "core.something_else", "entity_ref": "ref_x:1"}, _ref_ctx(session)
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert events == []


async def test_reference_cascade_one_recompute_per_event_dedupes_sku(session):
    """КАСКАД: 3 reference-эмита подряд → ровно 3 recompute, sku_codes дедуплицированы внутри.

    Защита от: «массовая правка справочника = шквал событий» (см. ТЗ B2 — дебаунс/идемпотентность).
    Каждый эмит даёт ОДИН outbox-сигнал, дедуп sku — внутри payload (set→sorted list).
    """
    from core.domain.models import OutboxEvent, Sku
    from modules.finance.events import on_reference_changed

    # 2 SKU на одном коде ТН ВЭД + 1 на другом
    session.add_all([
        Sku(code="C-1", title="C1", tnved_code="TN-A"),
        Sku(code="C-2", title="C2", tnved_code="TN-A"),
        Sku(code="C-3", title="C3", tnved_code="TN-B"),
    ])
    await session.commit()

    ctx = _ref_ctx(session)
    # 3 reference-эмита подряд (каскад): один и тот же TN-A 2 раза + TN-B 1 раз
    for entity_ref in ("ref_tnved:TN-A", "ref_tnved:TN-A", "ref_tnved:TN-B"):
        await on_reference_changed(
            {"ref_key": "core.tnved", "entity_ref": entity_ref}, ctx
        )
    await session.commit()

    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    # 3 входа → 3 recompute (each event idempotent, dedup на стороне читателя через
    # entity_ref + sku_codes); внутри payload — отсортированный список без дублей
    assert len(recompute) == 3
    payloads_a = [e.payload for e in recompute if e.payload["entity_ref"] == "ref_tnved:TN-A"]
    assert len(payloads_a) == 2
    for p in payloads_a:
        assert p["sku_codes"] == ["C-1", "C-2"]  # дедуп + сортировка внутри
    payload_b = [e.payload for e in recompute if e.payload["entity_ref"] == "ref_tnved:TN-B"][0]
    assert payload_b["sku_codes"] == ["C-3"]


async def test_reference_facade_failure_is_failsoft(session):
    """Фасад sku_master упал → сигнал всё равно эмитим с inputs={} (fail-soft, B2 хвост)."""
    from core.domain.models import OutboxEvent, Sku
    from modules.finance.events import on_reference_changed

    session.add(Sku(code="F-1", title="F1", tnved_code="FX-1"))
    await session.commit()

    class _Broken:
        async def landed_inputs_batch(self, _s, _codes):
            raise RuntimeError("facade down")

    await on_reference_changed(
        {"ref_key": "core.tnved", "entity_ref": "ref_tnved:FX-1"},
        _ref_ctx(session, sku_master=_Broken()),
    )
    await session.commit()
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    assert len(recompute) == 1
    assert recompute[0].payload["sku_codes"] == ["F-1"]
    assert recompute[0].payload["inputs"] == {}  # fail-soft


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
    assert by["2026-07-02"]["inflow"] == "500.00"  # только main
    # opening_balance = paid_recv(0) − paid_out(0) + BankAccount.opening(1000) = 1000
    assert r_main["opening_balance"] == "1000.00"

    # Без фильтра — все три (общий кэш + main + cny)
    r_all = await cashflow_forecast(session, days=5, mode="day", today=today)
    by_all = {b["bucket_start"]: b for b in r_all["buckets"]}
    assert by_all["2026-07-02"]["inflow"] == "1699.00"  # 500 + 200 + 999


# ═════════════════════════ Круг 5 — тест-харднинг и edge-cases ═════════════════════════


# К5-1: reconcile fetch_payments edge — дубли ref / нет counterparty_ref / запятая в сумме
# (см. ТЗ круг 5: матчинг не должен схлопывать дубли в один ключ и не падать на «100,00»)


async def test_reconcile_duplicate_ref_does_not_collapse(session):
    """Два ERP-платежа с одинаковыми ref+counterparty НЕ должны схлопываться в один.

    Это РЕАЛЬНЫЕ деньги (счёт и его исправление; пересчёт; задвоение из 1С) — теряя
    одного из них в выдаче, мы скрываем разницу. Сейчас reconcile собирает `dict[key→p]`,
    что схлопывает дубли — тест падает на старом коде.
    """
    from modules.finance.reconcile import reconcile_with_onec

    session.add_all([
        Payment(ref="СЧ-DUP", amount=Decimal("100"), kind="receivable",
                status="pending", counterparty_ref="УНП-1"),
        Payment(ref="СЧ-DUP", amount=Decimal("200"), kind="receivable",
                status="pending", counterparty_ref="УНП-1"),  # дубль ref+cp с другой суммой
    ])
    await session.commit()

    class _Mock1C:
        async def fetch_payments(self):
            # 1С имеет ОДИН платёж по этому ref+cp — должно совпасть с ОДНИМ из ERP,
            # второй должен оказаться в only_in_erp (а не потеряться).
            return [{"ref": "СЧ-DUP", "amount": 100, "counterparty_ref": "УНП-1"}]

    r = await reconcile_with_onec(session, _Mock1C())
    # 2 ERP всего: 1 в matched + 1 в only_in_erp (или distinct по сумме) — главное НЕ потерять
    erp_total = len(r["matched"]) + len(r["only_in_erp"])
    assert erp_total == 2, f"дубль ref потерян: {r}"


async def test_reconcile_no_counterparty_does_not_collapse_unrelated(session):
    """Несколько платежей БЕЗ counterparty_ref с одинаковым ref — не должны схлопываться.

    Старый ключ `f"{ref}|{cp or ''}"` для двух Payment(ref="X", cp=None) даёт один ключ "X|" —
    второй платёж выпадает. Тест падает.
    """
    from modules.finance.reconcile import reconcile_with_onec

    session.add_all([
        Payment(ref="СЧ-A", amount=Decimal("50"), kind="receivable", status="pending"),
        Payment(ref="СЧ-A", amount=Decimal("70"), kind="receivable", status="pending"),
    ])
    await session.commit()
    r = await reconcile_with_onec(session, None)  # без 1С — все ERP → only_in_erp
    assert len(r["only_in_erp"]) == 2, f"оба ERP-платежа должны остаться: {r}"


async def test_reconcile_amount_with_comma_does_not_crash(session):
    """1С может прислать сумму строкой '100,00' (русская локаль) — НЕ должно крашить reconcile.

    Сейчас: `float(r.get("amount", 0))` упадёт ValueError на '100,00'. Тест падает.
    """
    from modules.finance.reconcile import reconcile_with_onec

    class _Mock1C:
        async def fetch_payments(self):
            return [{"ref": "СЧ-RUB", "amount": "100,00", "counterparty_ref": None}]

    # НЕ должно крашить — fail-soft по контракту 1С (см. CLAUDE.md финансы)
    r = await reconcile_with_onec(session, _Mock1C())
    assert r["source_available"] is True
    # парсинг должен дать корректное число (100.00) либо безопасный 0 (но не исключение)
    parsed_amount = r["only_in_1c"][0]["amount"] if r["only_in_1c"] else None
    assert parsed_amount is not None, f"платёж с '100,00' потерян: {r}"


# К5-2: B2 recompute каскад смешанных типов справочников — дедуп по объединению SKU


async def test_b2_cascade_mixed_kinds_dedupes_by_sku(session):
    """3 события РАЗНЫХ типов (ref_tnved + sku + vat), пересекающие SKU → 3 recompute,
    каждый со своим dedup-набором; объединение всех уникальных SKU из payloads
    покрывает ровно затронутые позиции, без дублей."""
    from core.domain.models import OutboxEvent, Sku
    from modules.finance.events import on_reference_changed

    # X-1: tnved=T1, vat=V1; X-2: tnved=T1, vat=V2; X-3: tnved=T2, vat=V1
    session.add_all([
        Sku(code="X-1", title="X1", tnved_code="T1", vat_code="V1"),
        Sku(code="X-2", title="X2", tnved_code="T1", vat_code="V2"),
        Sku(code="X-3", title="X3", tnved_code="T2", vat_code="V1"),
    ])
    await session.commit()

    ctx = _ref_ctx(session)
    # Каскад: смена T1 (затрагивает X-1+X-2), сменa SKU X-1 (один), смена V1 (X-1+X-3)
    await on_reference_changed(
        {"ref_key": "core.tnved", "entity_ref": "ref_tnved:T1"}, ctx
    )
    await on_reference_changed(
        {"ref_key": "core.skus", "entity_ref": "sku:X-1"}, ctx
    )
    await on_reference_changed(
        {"ref_key": "core.vat_rates", "entity_ref": "ref_vat_rate:V1"}, ctx
    )
    await session.commit()

    events = (await session.execute(select(OutboxEvent))).scalars().all()
    recompute = [e for e in events if e.event_type == "finance.landed.recompute_requested"]
    assert len(recompute) == 3

    # дедуп ВНУТРИ каждого payload (sorted unique)
    by_ref = {e.payload["entity_ref"]: e.payload["sku_codes"] for e in recompute}
    assert by_ref["ref_tnved:T1"] == ["X-1", "X-2"]
    assert by_ref["sku:X-1"] == ["X-1"]
    assert by_ref["ref_vat_rate:V1"] == ["X-1", "X-3"]

    # объединение всех уникальных SKU из всех payloads = реально затронутые позиции
    union = set()
    for codes in by_ref.values():
        union.update(codes)
    assert union == {"X-1", "X-2", "X-3"}  # X-1 встречался в 3-х, но в union один


# К5-3: платёжный календарь — edge параметры (days вне 1-90, account_id у Payment None)


async def test_cashflow_negative_days_does_not_explode(session):
    """days=-5 / 0 / 200 — кламп безопасный, не исключение."""
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)
    for bad in (-5, 0, 200):
        r = await cashflow_forecast(session, days=bad, mode="day", today=today)
        # должен вернуть результат с КЛАМП-длиной (1..90), не падать
        assert isinstance(r["buckets"], list)
        assert 1 <= len(r["buckets"]) <= 90


async def test_cashflow_payment_with_null_account_id_works(session):
    """Платёж без account_id (FK ON DELETE SET NULL — счёт удалён) не должен ронять прогноз.

    Случай: BankAccount удалили, Payment.account_id → None по FK. Запрос без account-фильтра
    должен учитывать; запрос с account_id=X — пропускать (общий кэш не принадлежит ни одному).
    """
    from modules.finance.cashflow import cashflow_forecast

    today = date(2026, 7, 1)
    session.add(
        Payment(
            ref="orphan",
            amount=Decimal("123"),
            kind="receivable",
            status="pending",
            due_date=date(2026, 7, 3),
            account_id=None,
        )
    )
    await session.commit()
    # без фильтра — попадает в общий
    r_all = await cashflow_forecast(session, days=10, mode="day", today=today)
    by = {b["bucket_start"]: b for b in r_all["buckets"]}
    assert by["2026-07-03"]["inflow"] == "123.00"
    # с фильтром по несуществующему account_id — НЕ должно крашить и НЕ включать orphan
    r_filt = await cashflow_forecast(
        session, days=10, mode="day", today=today, account_id=99999
    )
    by_f = {b["bucket_start"]: b for b in r_filt["buckets"]}
    assert by_f["2026-07-03"]["inflow"] == "0.00"


# К5-4: money-выходы — СТРОКИ, не float (деньги собственника не проходят через float).
# Фикс закрыт полосой finance-money-str: xfail СНЯТ, скан теперь ЗЕЛЁНЫЙ и охраняет контракт.


async def test_money_outputs_use_str_not_float_scan(session, api):
    """Деньго-сканер: money-поля во всех finance-ответах — строки, не float.

    Float дрейфует копейки на собственнике (приоритет №1 PLATFORM.md). Проверяем
    compute-слой (summary/cashflow) напрямую + API-схемы (PaymentOut/AllocationOut/
    BankAccountOut) через реальную сериализацию. ``pct`` (процент) — намеренно НЕ деньги.
    """
    from modules.finance.cashflow import cashflow_forecast
    from modules.finance.summary import finance_summary

    session.add(Payment(ref="X", amount=Decimal("1234.56"), kind="receivable",
                        status="pending", due_date=date(2026, 7, 3)))
    await session.commit()

    # 1) summary — маржа + касса + затраты
    s = await finance_summary(session)
    for key in ("revenue", "landed", "landed_gross", "claim_refund", "freight", "gross"):
        assert isinstance(s["margin"][key], str), f"margin.{key} — не str"
    for key in ("inflow", "outflow", "net", "received", "pending_receivable", "freight_refund"):
        assert isinstance(s["cash"][key], str), f"cash.{key} — не str"
    for c in s["costs"]:
        assert isinstance(c["amount"], str), f"costs[{c['kind']}].amount — не str"

    # 2) cashflow — opening_balance + бакеты
    cf = await cashflow_forecast(session, days=10, mode="day", today=date(2026, 7, 1))
    assert isinstance(cf["opening_balance"], str)
    for b in cf["buckets"]:
        for key in ("inflow", "outflow", "net", "cumulative"):
            assert isinstance(b[key], str), f"cashflow bucket.{key} — не str"

    # 3) API-схемы: PaymentOut.amount/outstanding, BankAccountOut.opening_balance, AllocationOut.amount
    payments = (await api.get("/finance/payments")).json()
    assert payments and isinstance(payments[0]["amount"], str), "PaymentOut.amount — не str"
    assert isinstance(payments[0]["outstanding"], str), "PaymentOut.outstanding — не str"

    acc = (await api.post("/finance/bank-accounts", json={
        "code": "scan", "title": "Скан", "currency": "BYN", "opening_balance": "10.00"
    })).json()
    assert isinstance(acc["opening_balance"], str), "BankAccountOut.opening_balance — не str"

    pid = payments[0]["id"]
    alloc = (await api.post(f"/finance/payments/{pid}/allocations", json={"amount": "1.00"})).json()
    assert isinstance(alloc["amount"], str), "AllocationOut.amount — не str"


# ───────────────────────── finance-money-str: точечные контракты money=str ─────────────────────────


async def test_payment_api_amount_is_string(session, api):
    """PaymentOut.amount — строка, не float."""
    session.add(Payment(ref="T-STR", amount=Decimal("999.99"), kind="receivable", status="pending"))
    await session.commit()
    r = await api.get("/finance/payments")
    rows = r.json()
    assert len(rows) == 1
    assert isinstance(rows[0]["amount"], str), "amount должен быть строкой"
    assert rows[0]["amount"] == "999.99"


async def test_bank_account_opening_balance_is_string(session, api):
    """BankAccountOut.opening_balance — строка."""
    r = await api.post("/finance/bank-accounts", json={
        "code": "test-main", "title": "Тест", "currency": "BYN", "opening_balance": "5000.00"
    })
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["opening_balance"], str), "opening_balance должен быть строкой"
    assert body["opening_balance"] == "5000.00"


async def test_allocation_amount_is_string(session, api):
    """AllocationOut.amount — строка."""
    session.add(Payment(ref="T-ALLOC", amount=Decimal("200.00"), kind="receivable", status="pending"))
    await session.commit()
    pid = (await session.execute(select(Payment.id))).scalar_one()
    r = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": "100.00"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["amount"], str), "allocation amount должен быть строкой"


async def test_payment_amount_roundtrip_no_float_error(session, api):
    """Деньги проходят сквозь API без float-дрейфа."""
    precise = "1234567.89"
    session.add(Payment(ref="T-PRECISE", amount=Decimal(precise), kind="receivable", status="pending"))
    await session.commit()
    r = await api.get("/finance/payments")
    row = r.json()[0]
    assert Decimal(row["amount"]) == Decimal(precise), "float-дрейф недопустим для денег собственника"
