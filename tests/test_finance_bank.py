"""Тесты банк-импорта оплат клиентов (Альфа host-to-host, слайс 1): матчинг + идемпотентность.

Матчер и проводка гоняются напрямую (``sync_incoming`` с фейковым шлюзом) — без сети.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from core.domain.models import OutboxEvent
from core.services.eventbus import OutboxEventBus
from modules.finance.allocation import sum_allocations
from modules.finance.bank_ingest import sync_incoming
from modules.finance.models import BankTransaction, Payment, PaymentAllocation
from modules.finance.official_fx import BankAmountInvalid, bank_source_amount
from tests.test_finance import finance_api as finance_api
from tests.test_finance import finance_org as finance_org


class FakeBank:
    """Шлюз-двойник: отдаёт заранее заданные зачисления."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0

    async def fetch_incoming(self, since=None) -> list[dict]:
        self.calls += 1
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


async def test_legacy_incoming_without_organization_owner_stays_unmatched(session, finance_org):
    pid = await _receivable(session)
    bus = OutboxEventBus()
    summary = await sync_incoming(
        session, FakeBank([_tx("A1", "1000", "Оплата по счёту СЧ-100 за товар")]), bus
    )
    await session.commit()
    assert summary == {"source_available": True, "fetched": 1, "new": 1, "matched": 0, "unmatched": 1}
    p = await session.get(Payment, pid)
    assert p.status == "pending"
    tx = (await session.execute(select(BankTransaction))).scalar_one()
    assert tx.match_status == "unmatched" and "владельцы организаций" in (tx.note or "")
    assert tx.payment_id is None and tx.allocation_id is None
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    # A confirmed payment owner still cannot establish ownership of this channel.
    owned = Payment(organization_id=finance_org, ref="SYN-OWNED-CHANNEL", amount=Decimal("100"),
                    kind="receivable", status="pending", counterparty_ref="191234567")
    session.add(owned)
    await session.commit()
    second = await sync_incoming(session, FakeBank([_tx("SYN-OWNED-CHANNEL", "100", "SYN-OWNED-CHANNEL")]), bus)
    await session.commit()
    assert second == {"source_available": True, "fetched": 1, "new": 1, "matched": 0, "unmatched": 1}
    await session.refresh(owned)
    row = await session.scalar(select(BankTransaction).where(BankTransaction.ext_id == "SYN-OWNED-CHANNEL"))
    assert owned.status == "pending" and "владельцы организаций" in row.note
    assert row.match_status == "unmatched" and row.payment_id is None and row.allocation_id is None
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_idempotent_double_sync_no_double_allocation(session):
    pid = await _receivable(session)
    gw = FakeBank([_tx("A1", "1000", "Оплата счёт СЧ-100")])
    bus = OutboxEventBus()
    await sync_incoming(session, gw, bus)
    await session.commit()
    second = await sync_incoming(session, gw, bus)  # тот же ext_id
    await session.commit()
    assert second["new"] == 0 and second["matched"] == 0
    # Legacy запись не была проведена и повторный опрос не создаёт вторую.
    allocated = await sum_allocations(session, pid)
    assert allocated == Decimal("0")
    cnt = (await session.execute(select(func.count()).select_from(BankTransaction))).scalar_one()
    assert cnt == 1


async def test_legacy_partial_payment_without_owner_keeps_payment_pending(session):
    pid = await _receivable(session, amount="1000")
    bus = OutboxEventBus()
    await sync_incoming(session, FakeBank([_tx("A1", "400", "СЧ-100 частично")]), bus)
    await session.commit()
    p = await session.get(Payment, pid)
    assert p.status == "pending"
    assert (Decimal("1000") - await sum_allocations(session, pid)) == Decimal("1000")


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


@pytest.mark.parametrize(
    "raw",
    [None, "", "NaN", "Infinity", "-Infinity", "0", "-1", "12.345", 1.5, True],
)
def test_invalid_bank_amount_is_rejected_explicitly(raw):
    with pytest.raises(BankAmountInvalid):
        bank_source_amount(raw)


async def test_alfa_client_without_creds_returns_empty():
    from modules.integrations.alfa import AlfaBankClient

    assert await AlfaBankClient().fetch_incoming() == []
    assert AlfaBankClient().configured is False


# ───────────────────────── API-обвязка ─────────────────────────


async def test_bank_sync_endpoint_wired_and_honest_empty(finance_api):
    bank = FakeBank([])
    finance_api._transport.app.state.core.services.bank = bank
    r = await finance_api.post("/finance/bank/sync")
    assert r.status_code == 503
    assert "принадлежность канала" in r.json()["detail"]
    assert bank.calls == 0  # Unconfirmed channel must not be queried.
    r2 = await finance_api.get("/finance/bank/transactions")
    assert r2.status_code == 200 and r2.json() == []


async def test_bank_sync_invalid_amount_rolls_back_prior_rows(session):
    pid = await _receivable(session)
    bank = FakeBank([
        _tx("A-VALID", "1000", "Оплата по счёту СЧ-100"),
        _tx("A-INVALID", "NaN", "Оплата по счёту СЧ-100"),
    ])

    # The scoped API rejects unconfirmed channels before ingest. Keep the
    # malformed-row transaction oracle on the actual ingest entry point.
    with pytest.raises(BankAmountInvalid):
        await sync_incoming(session, bank, OutboxEventBus())
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(BankTransaction)) == 0
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    payment = await session.get(Payment, pid)
    assert payment is not None and payment.status == "pending"


async def test_bank_endpoint_forbidden_for_non_finance_role(api):
    # деньги: чужая роль (продажи) не имеет доступа к /finance → 403 middleware
    r = await api.post("/finance/bank/sync", headers={"X-User-Roles": "sales"})
    assert r.status_code == 403


async def test_manual_legacy_match_without_organization_owner_cannot_allocate(finance_api, session):
    pid = await _receivable(session)
    tx = BankTransaction(
        ext_id="LEGACY-MANUAL-UNOWNED", amount=Decimal("1000"), currency="BYN",
        purpose="Оплата счёт СЧ-100", match_status="unmatched",
    )
    session.add(tx)
    await session.commit()

    response = await finance_api.post(f"/finance/bank/transactions/{tx.id}/match", json={"payment_id": pid})

    assert response.status_code == 404
    await session.refresh(tx)
    payment = await session.get(Payment, pid)
    assert tx.match_status == "unmatched" and tx.payment_id is None and tx.allocation_id is None
    assert payment is not None and payment.status == "pending"
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_matched_legacy_history_replay_is_a_noop(session):
    pid = await _receivable(session)
    allocation = PaymentAllocation(payment_id=pid, amount=Decimal("1000"))
    session.add(allocation)
    await session.flush()
    tx = BankTransaction(
        ext_id="LEGACY-MATCHED-HISTORY", amount=Decimal("1000"), currency="BYN",
        purpose="Оплата счёт СЧ-100", match_status="matched", payment_id=pid,
        allocation_id=allocation.id,
    )
    session.add(tx)
    payment = await session.get(Payment, pid)
    payment.status = "paid"
    await session.commit()
    before = (tx.match_status, tx.payment_id, tx.allocation_id, tx.amount)

    summary = await sync_incoming(
        session, FakeBank([_tx("LEGACY-MATCHED-HISTORY", "1000", "Оплата счёт СЧ-100")]), OutboxEventBus()
    )
    await session.commit()

    await session.refresh(tx)
    payment = await session.get(Payment, pid)
    assert summary == {"source_available": True, "fetched": 1, "new": 0, "matched": 0, "unmatched": 0}
    assert (tx.match_status, tx.payment_id, tx.allocation_id, tx.amount) == before
    assert payment is not None and payment.status == "paid"
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_bank_source_binding_owns_queue_and_manual_match(session, finance_api, finance_org):
    from modules.accounting.models import SourceBinding

    own = BankTransaction(ext_id="SYN-BIND-OWN", amount=Decimal("60"), currency="BYN")
    foreign = BankTransaction(ext_id="SYN-BIND-FOREIGN", amount=Decimal("70"), currency="BYN")
    legacy = BankTransaction(ext_id="SYN-BIND-LEGACY", amount=Decimal("80"), currency="BYN")
    full = BankTransaction(ext_id="SYN-BIND-FULL", amount=Decimal("90"), currency="BYN",
                           source_provider="synthetic", source_external_id="full-1")
    payment = Payment(organization_id=finance_org, ref="SYN-OWN-PAYMENT", amount=Decimal("100"))
    other = Payment(organization_id=900002, ref="SYN-FOREIGN-PAYMENT", amount=Decimal("100"))
    session.add_all([own, foreign, legacy, full, payment, other])
    await session.flush()
    for tx, org in ((own, finance_org), (foreign, 900002), (full, finance_org)):
        session.add(SourceBinding(organization_id=org, source_type="finance_bank_transaction",
                                  source_id=tx.id, ownership="own", evidence="Synthetic evidence", actor="yi-finance"))
    await session.commit()
    queue = await finance_api.get("/finance/bank/transactions")
    assert queue.status_code == 200
    assert [row["id"] for row in queue.json()] == [own.id]
    for tx in (foreign, legacy):
        denied = await finance_api.post(f"/finance/bank/transactions/{tx.id}/match", json={"payment_id": payment.id})
        assert denied.status_code == 404
    assert (await finance_api.post(f"/finance/bank/transactions/{full.id}/match",
                                   json={"payment_id": payment.id})).status_code == 409
    assert (await finance_api.post(f"/finance/bank/transactions/{own.id}/match",
                                   json={"payment_id": other.id})).status_code == 404
    for status, kind, ref in (("cancelled", "receivable", "document:cancelled"),
                              ("superseded", "receivable", "document:superseded"),
                              ("recorded", "landed", "landed-receipt:synthetic")):
        prohibited = Payment(organization_id=finance_org, ref="SYN-PROHIBITED-" + status,
                             amount=Decimal("100"), kind=kind, status=status, entity_ref=ref)
        session.add(prohibited)
        await session.commit()
        denied = await finance_api.post(f"/finance/bank/transactions/{own.id}/match",
                                        json={"payment_id": prohibited.id})
        assert denied.status_code == 409
        await session.refresh(prohibited)
        await session.refresh(own)
        assert prohibited.status == status
        assert own.match_status == "unmatched" and own.payment_id is None and own.allocation_id is None
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    accepted = await finance_api.post(f"/finance/bank/transactions/{own.id}/match", json={"payment_id": payment.id})
    assert accepted.status_code == 200, accepted.text
    replay = await finance_api.post(f"/finance/bank/transactions/{own.id}/match", json={"payment_id": payment.id})
    assert replay.status_code == 409
    await session.refresh(payment)
    assert payment.status == "partial" and payment.organization_id == finance_org
    assert await session.scalar(select(func.count()).select_from(PaymentAllocation)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
