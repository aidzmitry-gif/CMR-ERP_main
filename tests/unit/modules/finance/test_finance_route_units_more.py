from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from modules.finance import balance_sheet, bank_ingest, cashflow_dds, pnl, routes
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from modules.finance.schemas import (
    AllocationCreate,
    BankAccountCreate,
    BankAccountUpdate,
    BankManualMatch,
    PaymentCreate,
    StatusUpdate,
)


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar_value = scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, *results, objects=None):
        self.results = list(results)
        self.objects = objects or {}
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, identity):
        return self.objects.get((model, identity))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 100 + len(self.added)
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


class Bus:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def services(**kwargs):
    return SimpleNamespace(**kwargs)


def payment(payment_id=1, status="pending"):
    return Payment(
        id=payment_id, ref=f"СЧ-{payment_id}", amount=Decimal("100"), status=status,
        kind="receivable", due_date=date(2026, 1, 1), paid_at=None, deal_id=9,
        counterparty_ref="УНП-1", account_id=2,
    )


@pytest.mark.asyncio
async def test_bank_accounts_payments_and_allocation_lifecycle_cover_money_and_events(monkeypatch):
    accounts = [SimpleNamespace(id=1, code="main", title="Основной", currency="BYN", opening_balance=Decimal("100"), opening_at=None, is_active=1)]
    listed = await routes.list_bank_accounts(True, Session(Result(accounts)))
    assert listed[0]["opening_balance"] == "100.00" and listed[0]["is_active"] is True

    created = await routes.create_bank_account(
        BankAccountCreate(code="cash", title="Касса", opening_balance=25),
        Session(Result()),
    )
    assert created["id"] == 100 and created["opening_balance"] == "25.00"
    with pytest.raises(HTTPException, match="уже существует"):
        await routes.create_bank_account(BankAccountCreate(code="main", title="Дубль"), Session(Result([accounts[0]])))

    account = BankAccount(id=1, code="main", title="Основной", currency="BYN", opening_balance=Decimal("100"), opening_at=None, is_active=1)
    changed = await routes.update_bank_account(1, BankAccountUpdate(title="Новый", is_active=False, opening_balance=125), Session(objects={(BankAccount, 1): account}))
    assert (changed["title"], changed["is_active"], changed["opening_balance"]) == ("Новый", False, "125.00")
    dated = await routes.update_bank_account(1, BankAccountUpdate(opening_at=date(2026, 9, 17)), Session(objects={(BankAccount, 1): account}))
    assert dated["opening_at"] == date(2026, 9, 17)
    with pytest.raises(HTTPException, match="Счёт не найден"):
        await routes.update_bank_account(404, BankAccountUpdate(), Session())

    rows = [payment(1), payment(2, "partial")]
    allocations = [(1, Decimal("25")), (2, Decimal("100"))]
    listed_payments = await routes.list_payments(2, Session(Result(rows), Result(allocations)))
    assert listed_payments[0]["outstanding"] == "75.00"
    assert listed_payments[0]["is_overdue"] is True

    allocation = PaymentAllocation(id=4, payment_id=1, amount=Decimal("25"), allocated_at=date(2026, 9, 17))
    detail = await routes.get_payment(1, Session(Result([allocation]), objects={(Payment, 1): rows[0]}))
    assert detail["outstanding"] == "75.00" and detail["allocations"][0]["amount"] == "25.00"
    created_payment = await routes.create_payment(PaymentCreate(ref="СЧ-3", amount=12.5), Session())
    assert created_payment["amount"] == "12.50"

    bus = Bus()
    monkeypatch.setattr(routes, "sum_allocations", AsyncMock(return_value=Decimal("0")))
    updated = await routes.update_payment(1, StatusUpdate(status="paid"), SimpleNamespace(event_bus=bus), Session(objects={(Payment, 1): rows[0]}))
    assert updated["status"] == "paid" and bus.calls[0][1] == "finance.payment.paid"

    received = PaymentAllocation(id=5, payment_id=1, amount=Decimal("100"), allocated_at=date(2026, 9, 17))
    monkeypatch.setattr(routes, "apply_allocation", AsyncMock(return_value=received))
    session = Session(objects={(Payment, 1): rows[0]})
    result = await routes.create_allocation(1, AllocationCreate(amount=100), SimpleNamespace(event_bus=bus), session)
    assert result is received and session.commits == 1
    with pytest.raises(HTTPException, match="> 0"):
        await routes.create_allocation(1, AllocationCreate(amount=0), SimpleNamespace(event_bus=bus), Session(objects={(Payment, 1): rows[0]}))


@pytest.mark.asyncio
async def test_bank_sync_queue_and_manual_match_are_idempotent_and_fail_soft(monkeypatch):
    monkeypatch.setattr(bank_ingest, "sync_incoming", AsyncMock(return_value={"fetched": 2, "matched": 1}))
    result = await routes.bank_sync(SimpleNamespace(services=services(bank=None), event_bus=Bus()), Session())
    assert result == {"ok": True, "fetched": 2, "matched": 1}
    monkeypatch.setattr(bank_ingest, "sync_incoming", AsyncMock(side_effect=RuntimeError("timeout")))
    with pytest.raises(HTTPException, match="Банк недоступен"):
        await routes.bank_sync(SimpleNamespace(services=services(bank=object()), event_bus=Bus()), Session())

    tx = BankTransaction(id=3, ext_id="ext-3", occurred_on=date(2026, 9, 17), amount=Decimal("40"), currency="BYN", payer_unp="1", payer_name="Альфа", purpose="Счёт СЧ-1", account_code="main", match_status="unmatched", note="x")
    assert await routes.list_bank_transactions("unmatched", Session(Result([tx]))) == [tx]
    p = payment(1)
    alloc = PaymentAllocation(id=9, payment_id=1, amount=Decimal("40"), allocated_at=date(2026, 9, 17))
    monkeypatch.setattr(routes, "apply_allocation", AsyncMock(return_value=alloc))
    matched = await routes.match_bank_transaction(3, BankManualMatch(payment_id=1), SimpleNamespace(event_bus=Bus()), Session(objects={(BankTransaction, 3): tx, (Payment, 1): p}))
    assert (matched.match_status, matched.payment_id, matched.allocation_id) == ("manual", 1, 9)

    tx.match_status = "matched"
    with pytest.raises(HTTPException, match="уже сматчено"):
        await routes.match_bank_transaction(3, BankManualMatch(payment_id=1), SimpleNamespace(event_bus=Bus()), Session(objects={(BankTransaction, 3): tx}))


@pytest.mark.asyncio
async def test_finance_csv_report_routes_delegate_and_render_downloadable_contracts(monkeypatch):
    cash = {
        "inflows": "100.00", "outflows": "20.00", "net_cashflow": "80.00", "bank_balance": "120.00",
        "breakdown": {"receivable": "100.00", "opex": "20.00"},
    }
    monkeypatch.setattr(cashflow_dds, "cashflow_report", AsyncMock(return_value=cash))
    core = SimpleNamespace(services=services(onec=None))
    csv = await routes.get_cashflow("2026-09-01", "2026-09-30", "csv", core, Session())
    assert csv.media_type == "text/csv" and "Поступления,100.00" in csv.body.decode()
    assert (await routes.get_cashflow(None, None, None, core, Session())) == cash

    balance = {
        "as_of": "2026-09-17", "accounts_receivable": "10.00", "cash": None,
        "inventory_value": None, "total_assets": "10.00", "accounts_payable": "4.00",
        "payroll_payable": "0.00", "tax_payable": "0.00", "total_liabilities": "4.00", "equity": "6.00",
    }
    monkeypatch.setattr(balance_sheet, "get_balance_sheet", AsyncMock(return_value=balance))
    balance_csv = await routes.get_balance_sheet("2026-09-17", "csv", core, Session())
    assert "ИТОГО Активы,10.00" in balance_csv.body.decode()
    assert await routes.get_balance_sheet(None, None, core, Session()) == balance
    with pytest.raises(HTTPException, match="as_of"):
        await routes.get_balance_sheet("bad", None, core, Session())

    pnl_data = {
        "revenue": "100.00", "cogs_gross": "20.00", "cogs_claim_refund": "1.00", "cogs_net": "19.00",
        "gross_profit": "81.00", "freight_gross": "5.00", "freight_refund": "1.00", "freight_net": "4.00",
        "payroll": "10.00", "opex": "3.00", "tax": "2.00", "bank_fee": "1.00", "operating_profit": "65.00",
    }
    monkeypatch.setattr(pnl, "pnl_report", AsyncMock(return_value=pnl_data))
    pnl_csv = await routes.get_pnl(None, None, None, "csv", core if False else Session())
    assert "Выручка (признанная),100.00" in pnl_csv.body.decode()
    assert await routes.get_pnl(None, None, None, None, Session()) == pnl_data
    with pytest.raises(HTTPException, match="period_to"):
        await routes.get_pnl(None, "not-date", None, None, Session())


@pytest.mark.asyncio
async def test_finance_delegating_reports_pass_filters_and_reconciliation_dependencies(monkeypatch):
    aging = AsyncMock(return_value={"buckets": []})
    forecast = AsyncMock(return_value={"weeks": 1})
    monkeypatch.setattr("modules.finance.aging.aging_buckets", aging)
    monkeypatch.setattr("modules.finance.cashflow.cashflow_forecast", forecast)
    assert await routes.get_aging(Session()) == {"buckets": []}
    assert await routes.get_cashflow_forecast(weeks=0, mode="other", days=0, account_id=3, session=Session()) == {"weeks": 1}
    forecast.assert_awaited_once()

    cost = AsyncMock(return_value={"rows": []})
    by_deal = AsyncMock(return_value=[])
    by_cp = AsyncMock(return_value=[])
    monkeypatch.setattr("modules.finance.cost_center.group_by_cost_center", cost)
    monkeypatch.setattr("modules.finance.margin.margin_by_deal", by_deal)
    monkeypatch.setattr("modules.finance.margin.margin_by_counterparty", by_cp)
    assert await routes.get_by_cost_center(Session(), "2026-09-01", "2026-09-30") == {"rows": []}
    assert await routes.margin_by_deal(Session()) == []
    assert await routes.margin_by_counterparty(Session()) == []

    monkeypatch.setattr("modules.finance.reconcile.reconcile_with_onec", AsyncMock(return_value={"source_available": False}))
    assert await routes.reconcile_1c(SimpleNamespace(services=services(onec=None)), Session()) == {"source_available": False}
