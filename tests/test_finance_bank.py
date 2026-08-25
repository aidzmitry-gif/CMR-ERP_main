"""Тесты банк-импорта оплат клиентов (Альфа host-to-host, слайс 1): матчинг + идемпотентность.

Матчер и проводка гоняются напрямую (``sync_incoming`` с фейковым шлюзом) — без сети.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from core.services.eventbus import OutboxEventBus
from modules.finance.allocation import sum_allocations
from modules.finance.bank_ingest import sync_incoming
from modules.finance.models import BankTransaction, Payment, PaymentAllocation


class FakeBank:
    """Шлюз-двойник: отдаёт заранее заданные зачисления."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def fetch_incoming(self, since=None) -> list[dict]:
        return self.rows


def _tx(ext_id: str, amount: str, purpose: str, unp: str | None = "191234567") -> dict:
    return {
        "ext_id": ext_id, "date": "2026-07-19", "amount": amount, "currency": "BYN",
        "payer_unp": unp, "payer_name": "ООО Аккумулятор", "purpose": purpose,
        "account_code": "BY15ALFA",
    }


async def _receivable(session, ref="СЧ-100", amount="1000", unp="191234567") -> int:
    p = Payment(ref=ref, amount=Decimal(amount), status="pending", kind="receivable",
                counterparty_ref=unp, deal_id=42)
    session.add(p)
    await session.commit()
    return p.id


async def test_match_by_purpose_and_unp_auto_allocates(session):
    pid = await _receivable(session)
    bus = OutboxEventBus()
    summary = await sync_incoming(
        session, FakeBank([_tx("A1", "1000", "Оплата по счёту СЧ-100 за товар")]), bus
    )
    await session.commit()
    assert summary == {"source_available": True, "fetched": 1, "new": 1, "matched": 1, "unmatched": 0}
    p = await session.get(Payment, pid)
    assert p.status == "paid"
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert tx.match_status == "matched" and tx.payment_id == pid and tx.allocation_id is not None
    from core.domain.models import OutboxEvent
    types = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
    assert "finance.payment.received" in types and "finance.payment.paid" in types


async def test_idempotent_double_sync_no_double_allocation(session):
    pid = await _receivable(session)
    gw = FakeBank([_tx("A1", "1000", "Оплата счёт СЧ-100")])
    bus = OutboxEventBus()
    await sync_incoming(session, gw, bus)
    await session.commit()
    second = await sync_incoming(session, gw, bus)  # тот же ext_id
    await session.commit()
    assert second["new"] == 0 and second["matched"] == 0
    # ровно одно поступление — деньги клиента НЕ задвоены
    allocated = await sum_allocations(session, pid)
    assert allocated == Decimal("1000")
    cnt = (await session.execute(select(func.count()).select_from(BankTransaction))).scalar_one()
    assert cnt == 1


async def test_partial_payment_sets_partial_status(session):
    pid = await _receivable(session, amount="1000")
    bus = OutboxEventBus()
    await sync_incoming(session, FakeBank([_tx("A1", "400", "СЧ-100 частично")]), bus)
    await session.commit()
    p = await session.get(Payment, pid)
    assert p.status == "partial"
    assert (Decimal("1000") - await sum_allocations(session, pid)) == Decimal("600")


async def test_no_invoice_ref_goes_to_unmatched_queue(session):
    await _receivable(session)
    bus = OutboxEventBus()
    summary = await sync_incoming(
        session, FakeBank([_tx("A1", "1000", "Пополнение без указания счёта")]), bus
    )
    await session.commit()
    assert summary["unmatched"] == 1 and summary["matched"] == 0
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert tx.match_status == "unmatched" and tx.note
    # счёт не тронут
    assert (await session.execute(select(func.count()).select_from(PaymentAllocation))).scalar_one() == 0


async def test_unp_mismatch_queues_not_auto_match(session):
    await _receivable(session, unp="191234567")
    bus = OutboxEventBus()
    # назначение указывает на СЧ-100, но УНП плательщика другой → не проводим (ручной разбор)
    summary = await sync_incoming(
        session, FakeBank([_tx("A1", "1000", "Оплата счёт СЧ-100", unp="190000009")]), bus
    )
    await session.commit()
    assert summary["matched"] == 0 and summary["unmatched"] == 1
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert "УНП" in (tx.note or "")


async def test_ambiguous_multiple_candidates_queues(session):
    await _receivable(session, ref="СЧ-100", amount="1000")
    await _receivable(session, ref="СЧ-100", amount="500")  # тот же номер — неоднозначно
    bus = OutboxEventBus()
    summary = await sync_incoming(session, FakeBank([_tx("A1", "300", "Оплата СЧ-100")]), bus)
    await session.commit()
    assert summary["matched"] == 0 and summary["unmatched"] == 1
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert "кандидат" in (tx.note or "")


async def test_no_gateway_is_honest_empty(session):
    summary = await sync_incoming(session, None, OutboxEventBus())
    assert summary == {"source_available": False, "fetched": 0, "new": 0, "matched": 0, "unmatched": 0}


async def test_non_finite_amount_goes_to_unmatched_queue(session):
    await _receivable(session)
    summary = await sync_incoming(
        session, FakeBank([_tx("A-NAN", "NaN", "Оплата счёт СЧ-100")]), OutboxEventBus()
    )
    await session.commit()
    assert summary["matched"] == 0 and summary["unmatched"] == 1
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert tx.amount == Decimal("0") and tx.note == "нет суммы зачисления"


async def test_alfa_client_without_creds_returns_empty():
    from modules.integrations.alfa import AlfaBankClient

    assert await AlfaBankClient().fetch_incoming() == []
    assert AlfaBankClient().configured is False


# ───────────────────────── API-обвязка ─────────────────────────


async def test_bank_sync_endpoint_wired_and_honest_empty(api):
    r = await api.post("/finance/bank/sync")
    assert r.status_code == 200
    body = r.json()
    # реальный шлюз без кредов → пусто (не выдумываем оплаты)
    assert body["ok"] and body["fetched"] == 0
    r2 = await api.get("/finance/bank/transactions")
    assert r2.status_code == 200 and r2.json() == []


async def test_bank_endpoint_forbidden_for_non_finance_role(api):
    # деньги: чужая роль (продажи) не имеет доступа к /finance → 403 middleware
    r = await api.post("/finance/bank/sync", headers={"X-User-Roles": "sales"})
    assert r.status_code == 403
