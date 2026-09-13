"""A1 unit contract; no schema writes or cancellation transitions."""
import asyncio
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from modules.sales.invoice_money_basis import evaluate_invoice_money_basis

# Reuse the existing explicit-local-URL PostgreSQL fixtures after integration.
# Deselected for the artifact-only run; these are not executed by this task.
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory


class LockedSession:
    """No database: verifies query scope/refresh and transaction ownership only."""
    def __init__(self, doc, rows):
        self.doc, self.rows = doc, rows
        self.statements = []
        self.active = True

    def in_transaction(self):
        return self.active

    async def get(self, model, identity):
        from modules.sales.invoice_issuance import InvoiceIssuanceReceipt

        assert model is InvoiceIssuanceReceipt and identity == self.doc.id
        return None  # These unit fixtures describe historical, non-ERP invoices.

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.doc

    async def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: list(self.rows))


class BankGateway:
    def __init__(self, facts):
        self.facts = facts
        self.errors = {}
        self.calls = []

    async def invoice_bank_basis(self, session, org, user, document_id):
        self.calls.append(("basis", org, document_id))
        return {"organization_id": org, "document_id": document_id, "entries": [
            {"entry_id": key, "digest": value["digest"], "correction_of": None,
             "fact": copy.deepcopy(value), "blockers": []}
            for key, value in self.facts.items()
            if value["settlement_dimensions"]["settlement_document"] == f"sales:document:{document_id}"]}

    async def bank_settlement(self, session, org, user, entry_id):
        self.calls.append(("fact", org, entry_id))
        if entry_id in self.errors:
            raise HTTPException(self.errors[entry_id], "Synthetic failure")
        return copy.deepcopy(self.facts[entry_id])


def fixture(receipt="100.00", refunds=("40.00", "60.00"), *, status="paid"):
    html = "<p>Synthetic issued invoice</p>"
    doc = SimpleNamespace(id=1, deal_id=2, kind="invoice", status=status, version=1,
        number="A1-SYN", amount=Decimal("100.00"), issued_at=datetime(2026, 9, 1),
        original_html=html, content_sha256=hashlib.sha256(html.encode()).hexdigest(),
        snapshot_json={"currency": "BYN", "amount": "100.00"})
    identity = {"version": 1, "content_sha256": doc.content_sha256, "number": doc.number,
                "amount": "100.00", "currency": "BYN"}
    facts, rows = {}, []
    values = ([] if receipt is None else [(receipt, "receipt", None)])
    values += [(qty, "refund", 1) for qty in refunds]
    for key, (qty, direction, parent) in enumerate(values, 1):
        fact = {"entry_id": key, "digest": f"synthetic-bank-{key}", "amount": qty,
                "currency": "BYN", "direction": direction, "operation_date": "2026-09-01",
                "statement_reference": f"statement-{key}",
                "settlement_dimensions": {"settlement_document": "sales:document:1"}}
        facts[key] = fact
        rows.append(SimpleNamespace(id=key, organization_id=7, document_id=1,
            bank_entry_id=key, amount=Decimal(qty), direction=direction, refund_of=parent,
            snapshot={"invoice": copy.deepcopy(identity), "bank": copy.deepcopy(fact)},
            source_key=f"key-{key}", evidence="Synthetic", actor="test"))
    return doc, rows, BankGateway(facts)


async def evaluate(case):
    doc, rows, gateway = case
    return await evaluate_invoice_money_basis(LockedSession(doc, rows), 7, "test", doc, gateway)


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt,refunds,state", [
    ("100.00", ("40.00", "60.00"), "fully_refunded"),
    ("30.00", ("30.00",), "fully_refunded"),
    ("120.00", ("100.00",), "funds_held"),
    ("100.00", ("40.00",), "funds_held"),
])
async def test_money_states(receipt, refunds, state):
    result = await evaluate(fixture(receipt, refunds))
    assert result.money_state == state
    assert result.per_receipt_remaining[0].remaining == Decimal(receipt) - sum(map(Decimal, refunds))
    assert result.money_conditions_met == (state == "fully_refunded")
    assert result.external_requirements == (
        "history_scope_required", "reconciliation_required", "fulfillment_required")
    assert not hasattr(result, "cancellation_authorized")


@pytest.mark.asyncio
async def test_no_receipts_is_observed_scope_not_external_completeness():
    result = await evaluate(fixture(None, (), status="posted"))
    assert result.money_state == "no_receipts" and result.money_conditions_met
    assert "history_scope_required" in result.external_requirements


@pytest.mark.asyncio
async def test_legacy_paid_empty_is_unknown():
    result = await evaluate(fixture(None, ()))
    assert result.money_state == "history_unknown"
    assert "legacy_paid_without_receipts" in result.blockers


@pytest.mark.asyncio
async def test_refund_of_another_receipt_cannot_net_cancel():
    case = fixture()
    case[1][1].refund_of = 999
    result = await evaluate(case)
    assert result.received == result.refunded == 100
    assert result.money_state == "history_unknown"
    assert "refund_receipt_mismatch" in result.blockers
    assert result.per_receipt_remaining[0].remaining == 40


@pytest.mark.asyncio
async def test_overrefund_is_unknown_even_when_bank_amount_valid():
    result = await evaluate(fixture("100.00", ("120.00",)))
    assert result.money_state == "history_unknown"
    assert "refund_exceeds_receipt" in result.blockers


@pytest.mark.asyncio
async def test_two_receipts_cannot_cross_compensate_even_when_total_net_zero():
    case = fixture("100.00", ("150.00", "50.00"))
    second = copy.deepcopy(case[1][0])
    second.id, second.bank_entry_id, second.source_key = 4, 4, "second-receipt"
    second.snapshot["bank"]["entry_id"] = 4
    second.snapshot["bank"]["digest"] = "second-receipt"
    case[1].append(second)
    case[2].facts[4] = copy.deepcopy(second.snapshot["bank"])
    case[1][2].refund_of = 4
    result = await evaluate(case)
    assert result.received == result.refunded == 200
    assert [r.remaining for r in result.per_receipt_remaining] == [-50, 50]
    assert "refund_exceeds_receipt" in result.blockers
    assert not result.money_conditions_met


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 409])
async def test_missing_or_corrected_bank_is_unknown(status):
    case = fixture()
    case[2].errors[2] = status
    result = await evaluate(case)
    assert result.money_state == "history_unknown"
    assert "bank_evidence_invalid" in result.blockers


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 503])
async def test_authorization_or_service_failures_propagate(status):
    case = fixture()
    case[2].errors[1] = status
    with pytest.raises(HTTPException) as error:
        await evaluate(case)
    assert error.value.status_code == status


@pytest.mark.asyncio
async def test_known_unallocated_invoice_bank_is_not_zero():
    case = fixture()
    case[2].facts[4] = {**copy.deepcopy(case[2].facts[1]), "entry_id": 4, "digest": "new",
                         "amount": "10.00"}
    result = await evaluate(case)
    assert result.money_state == "history_unknown"
    assert "known_bank_unallocated" in result.blockers


@pytest.mark.asyncio
async def test_partial_bank_allocation_is_unknown():
    case = fixture()
    case[2].facts[1]["amount"] = "120.00"
    case[1][0].snapshot["bank"]["amount"] = "120.00"
    result = await evaluate(case)
    assert "known_bank_unallocated" in result.blockers


@pytest.mark.asyncio
async def test_unrelated_bank_does_not_change_basis():
    case = fixture()
    before = await evaluate(case)
    case[2].facts[99] = {**copy.deepcopy(case[2].facts[1]), "entry_id": 99,
                         "settlement_dimensions": {"settlement_document": "sales:document:99"}}
    after = await evaluate(case)
    assert before == after
    assert not any(call == ("fact", 7, 99) for call in case[2].calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,blocker", [
    ("version", 2, "invoice_version_mismatch"),
    ("content_sha256", "changed", "invoice_version_mismatch"),
])
async def test_exact_invoice_version(field, value, blocker):
    case = fixture()
    case[1][0].snapshot["invoice"][field] = value
    assert blocker in (await evaluate(case)).blockers


@pytest.mark.asyncio
async def test_cross_org_row_is_not_ignored():
    case = fixture()
    case[1][0].organization_id = 8
    result = await evaluate(case)
    assert result.money_state == "history_unknown"
    assert "settlement_scope_mismatch" in result.blockers


@pytest.mark.asyncio
async def test_bank_snapshot_change_and_wrong_invoice_are_blockers():
    case = fixture()
    case[2].facts[1]["digest"] = "corrected"
    assert "bank_snapshot_mismatch" in (await evaluate(case)).blockers
    case[2].facts[1]["settlement_dimensions"]["settlement_document"] = "sales:document:999"
    result = await evaluate(case)
    assert "bank_evidence_invalid" in result.blockers
    assert "allocated_bank_missing_from_basis" in result.blockers


@pytest.mark.asyncio
async def test_refund_date_guard():
    case = fixture()
    case[2].facts[2]["operation_date"] = "2026-08-31"
    case[1][1].snapshot["bank"]["operation_date"] = "2026-08-31"
    assert "refund_predates_receipt" in (await evaluate(case)).blockers


@pytest.mark.asyncio
async def test_canonical_frozen_basis_does_not_alias_mutable_inputs():
    case = fixture()
    before = await evaluate(case)
    case[1].reverse()
    case[2].facts = dict(reversed(list(case[2].facts.items())))
    assert await evaluate(case) == before
    case[1][0].evidence = "Changed review"
    assert (await evaluate(case)).digest != before.digest
    assert json.loads(before.facts_json)["settlements"][0]["evidence"] == "Synthetic"
    with pytest.raises(FrozenInstanceError):
        before.money_state = "no_receipts"


@pytest.mark.asyncio
async def test_cancelled_money_never_mutates_paid_state():
    case = fixture("100.00", (), status="cancelled")
    result = await evaluate(case)
    assert result.money_state == "funds_held"
    assert case[0].status == "cancelled"
    assert "cancelled_invoice_money_review_required" in result.blockers


@pytest.mark.asyncio
async def test_existing_transaction_required_and_locked_reads_refresh():
    doc, rows, gateway = fixture()
    session = LockedSession(doc, rows)
    session.active = False
    with pytest.raises(RuntimeError):
        await evaluate_invoice_money_basis(session, 7, "test", doc, gateway)
    assert not session.statements and not gateway.calls
    session.active = True
    await evaluate_invoice_money_basis(session, 7, "test", doc, gateway)
    assert session.active  # evaluator has no commit/rollback API to call
    for statement in session.statements[:2]:
        assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
        assert statement.get_execution_options()["populate_existing"] is True
    # Diagnostic cross-book reads must not introduce a second book's row locks.
    cross_book = session.statements[2]
    assert "FOR UPDATE" not in str(cross_book.compile(dialect=postgresql.dialect()))
    assert cross_book.get_execution_options()["populate_existing"] is True
    first = session.statements[0].compile(dialect=postgresql.dialect())
    assert 7 in first.params.values() and 1 in first.params.values()


@pytest.mark.asyncio
async def test_basis_is_stable_while_callers_share_org_lock_contract():
    """Orchestration test, NOT proof of PostgreSQL locking; see integration test."""
    case = fixture()
    gate = asyncio.Lock()
    waiting = asyncio.Event()

    async def writer():
        waiting.set()
        async with gate:
            case[2].facts[9] = {**copy.deepcopy(case[2].facts[1]), "entry_id": 9}

    async with gate:
        first = await evaluate(case)
        task = asyncio.create_task(writer())
        await waiting.wait()
        assert not task.done()
        assert (await evaluate(case)).digest == first.digest
    await task
    after = await evaluate(case)
    assert after.digest != first.digest
    assert "known_bank_unallocated" in after.blockers


@pytest.mark.asyncio
async def test_bank_discovery_includes_corrections_with_changed_dimensions():
    from modules.accounting.gateway import AccountingService

    gateway = AccountingService()
    case = fixture()
    calls = []

    async def member(session, org, user):
        calls.append("org-lock")

    async def bank(session, org, user, key):
        raise HTTPException(409, "Corrected or correction bank entry")

    gateway.source_member, gateway.bank_settlement = member, bank
    original_entry = SimpleNamespace(id=1, digest="original", correction_of=None)
    correction = SimpleNamespace(id=4, digest="correction", correction_of=1)

    class DiscoverySession:
        def __init__(self):
            self.values = iter([[1], [original_entry], [4], [correction], []])
            self.statements = []

        async def scalars(self, statement):
            assert calls == ["org-lock"]
            self.statements.append(statement)
            value = next(self.values)
            return SimpleNamespace(all=lambda: value)

    session = DiscoverySession()
    result = await gateway.invoice_bank_basis(session, 7, "test", case[0].id)
    assert [e["entry_id"] for e in result["entries"]] == [1, 4]
    assert all(e["blockers"] == ["bank_evidence_invalid"] for e in result["entries"])
    first = session.statements[0].compile(dialect=postgresql.dialect())
    assert {7, "bank_settlement", "sales:document:1"} <= set(first.params.values())
    for query in session.statements:
        assert "organization_id" in str(query)


@pytest.mark.asyncio
async def test_bank_discovery_revalidates_fact_and_propagates_denied_access():
    from modules.accounting.gateway import AccountingService

    gateway = AccountingService()
    case = fixture()

    async def member(session, org, user):
        return "test"

    async def bank(session, org, user, key):
        return copy.deepcopy(case[2].facts[key])

    gateway.source_member, gateway.bank_settlement = member, bank

    class DiscoverySession:
        def __init__(self):
            entry = SimpleNamespace(id=1, digest="bank", correction_of=None)
            self.values = iter([[1], [entry], []])

        async def scalars(self, statement):
            value = next(self.values)
            return SimpleNamespace(all=lambda: value)

    result = await gateway.invoice_bank_basis(DiscoverySession(), 7, "test", 1)
    assert result["entries"][0]["fact"] == case[2].facts[1]

    async def denied(session, org, user, key):
        raise HTTPException(403, "Denied")

    gateway.bank_settlement = denied
    with pytest.raises(HTTPException) as exc:
        await gateway.invoice_bank_basis(DiscoverySession(), 7, "test", 1)
    assert exc.value.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_basis_holds_against_concurrent_known_bank_insert(pg_factory, pg_book):
    """Real PG evidence for the caller-lock contract; not run in artifact-only work."""
    from sqlalchemy import text

    from core.services.auth import CurrentUser
    from modules.accounting import service
    from modules.accounting.documents import BankDocument
    from modules.accounting.gateway import AccountingService
    from modules.sales.access import DealAccess
    from modules.sales.accounting_ownership import DealOwnership
    from modules.sales.documents import lock_deal
    from modules.sales.invoice_settlements import AllocationInput, allocate
    from modules.sales.models import Deal, DealDocument
    from tests.accounting.test_bank_documents import document

    gateway, user = AccountingService(), CurrentUser("tester", ["director"])
    org = pg_book[0]
    doc_value = fixture()[0]
    core = SimpleNamespace(services=SimpleNamespace(accounting=gateway))

    def bank_input(source, qty, direction):
        return BankDocument(**document(source=source, statement_reference=source,
            policy_id=pg_book[1], amount=qty, direction=direction,
            settlement_dimensions={"settlement_document": "sales:document:1"}))

    async with pg_factory() as session:
        await gateway.source_owner_authority(session, org, user)
        session.add(Deal(id=2, number="A1-SYN", title="Synthetic", counterparty="Synthetic"))
        await session.flush()
        doc = DealDocument(**vars(doc_value))
        session.add_all([doc, DealOwnership(deal_id=2, organization_id=org,
            snapshot={}, evidence="Synthetic", actor="tester")])
        await session.flush()
        receipt_id = None
        for index, (qty, direction) in enumerate([
            ("100.00", "receipt"), ("40.00", "payment"), ("60.00", "payment"),
        ]):
            entry = await service.post(session, org, bank_input(f"a1-{index}", qty, direction).posting(), "tester")
            result = await allocate(org, 1, AllocationInput(source_key=f"a1-{index}",
                bank_entry_id=entry.id, amount=qty, refund_of=receipt_id if index else None,
                evidence="Synthetic"), (session, "tester"), DealAccess("all"), core, user)
            if index == 0:
                receipt_id = result["id"]
        await session.commit()

    ready = asyncio.Event()
    writer_pid = []

    async def writer():
        async with pg_factory() as session:
            writer_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            await service.lock_organization(session, org)
            await service.post(session, org, bank_input("a1-late", "10.00", "receipt").posting(), "tester")
            await session.commit()

    task = None
    try:
        async with pg_factory() as reader:
            await gateway.source_owner_authority(reader, org, user)
            await lock_deal(reader, 2)
            await reader.execute(text("SELECT id FROM sales.deal_document WHERE id=1 FOR UPDATE"))
            reader_pid = await reader.scalar(text("SELECT pg_backend_pid()"))
            first = await evaluate_invoice_money_basis(reader, org, user, doc_value, gateway)
            assert first.money_state == "fully_refunded"
            task = asyncio.create_task(writer())
            await asyncio.wait_for(ready.wait(), 5)

            async def blocked():
                while True:
                    blockers = await reader.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid[0]})
                    if reader_pid in blockers:
                        return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(blocked(), 5)
            assert (await evaluate_invoice_money_basis(reader, org, user, doc_value, gateway)).digest == first.digest
            await reader.commit()
        await asyncio.wait_for(task, 5)
        async with pg_factory() as reader:
            await gateway.source_owner_authority(reader, org, user)
            await lock_deal(reader, 2)
            await reader.execute(text("SELECT id FROM sales.deal_document WHERE id=1 FOR UPDATE"))
            after = await evaluate_invoice_money_basis(reader, org, user, doc_value, gateway)
            assert after.digest != first.digest
            assert "known_bank_unallocated" in after.blockers
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
