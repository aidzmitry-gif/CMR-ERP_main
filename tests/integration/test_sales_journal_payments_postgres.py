"""The payment projection waits for real allocations/refunds and refreshes facts."""
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from core.services.auth import CurrentUser
from modules.accounting.models import Account, Policy
from modules.sales.access import DealAccess
from modules.sales.invoice_settlements import AllocationInput, allocate
from modules.sales.journal_payments import project_journal_payments
from modules.sales.models import Deal, DealDocument
from modules.sales.schemas import InvoiceIssueInput
from tests.accounting.test_invoice_settlements import bank
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_issuance import command, create, seed


@pytest.mark.parametrize("direction", ["receipt", "refund"])
async def test_journal_waits_for_actual_book_transaction(issuance_pg, direction):  # noqa: F811
    api, factory = issuance_pg
    services = api._transport.app.state.core.services
    core = api._transport.app.state.core
    user = CurrentUser("issuer", ["director"])
    async with factory() as session:
        ids, base = await seed(api, session, suffix=uuid4().hex[:8])
        cmd, _ = await command(api, ids, base)
        issued = await create(api, ids, cmd)
        assert issued.status_code == 201, issued.text
        doc_id = issued.json()["document"]["id"]
        policy = Policy(organization_id=ids["org"], effective_from=date(2026, 1, 1),
            reference="TEST ONLY", inventory_method="specific", allocation_basis="direct_cost",
            depreciation_method="straight_line", normative_reference="synthetic",
            normative_verified=True, approved_by="issuer")
        session.add(policy)
        for code, cash in (("51", True), ("62", False)):
            session.add(Account(organization_id=ids["org"], code=code, title="Synthetic", category="asset",
                valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
                quantity_tracking=False, cash=cash, normative_ref="synthetic"))
        await session.commit()
        book = (ids["org"], policy.id)
    incoming = await bank(api, book, doc_id, "journal-lock-in", "240.00")
    refund_of = None
    if direction == "refund":
        receipt = await api.post(f"/sales/organizations/{ids['org']}/invoices/{doc_id}/settlements", json={
            "bank_entry_id": incoming, "source_key": "receipt", "amount": "240.00", "evidence": "Synthetic",
        })
        assert receipt.status_code == 201, receipt.text
        refund_of = receipt.json()["id"]
    entry = incoming if direction == "receipt" else await bank(api, book, doc_id, "journal-lock-out", "240.00", "payment")
    async with factory() as writer, factory() as reader, factory() as observer:
        # Preload identities before the competing transaction. The projection must
        # re-read current settlement facts after it acquires the same book lock.
        deal = await reader.get(Deal, ids["deal"])
        await reader.get(DealDocument, doc_id)
        actor = await services.accounting.source_owner_authority(writer, ids["org"], user)
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        await allocate(ids["org"], doc_id, AllocationInput(bank_entry_id=entry,
            source_key="concurrent", amount="240.00", refund_of=refund_of, evidence="Synthetic"),
            (writer, actor), DealAccess("all"), core, user)
        task = asyncio.create_task(project_journal_payments(reader, services, user, [deal]))
        try:
            async with asyncio.timeout(10):
                while True:
                    await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                    blocked = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))"), {"pid": writer_pid})
                    if blocked:
                        break
                    assert not task.done()
                    await asyncio.sleep(0.02)
            await writer.commit()
            result = await task
            assert result[ids["deal"]].payment == ("paid" if direction == "receipt" else "refunded")
            assert result[ids["deal"]].source == "ledger"
            doc = await reader.scalar(select(DealDocument).where(DealDocument.id == doc_id))
            assert doc.status == "issued" and doc.reserve_status == "reserved"
        finally:
            await writer.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await reader.rollback()


@pytest.mark.parametrize("initial", ["absent", "draft"])
async def test_journal_waits_for_concurrent_first_issue(issuance_pg, monkeypatch, initial):  # noqa: F811
    from modules.sales.invoice_issuance import issue

    api, factory = issuance_pg
    core = api._transport.app.state.core
    user = CurrentUser("issuer", ["director"])
    draft_id = None
    async with factory() as setup:
        ids, base = await seed(api, setup, suffix=uuid4().hex[:8])
        if initial == "draft":
            draft = DealDocument(deal_id=ids["deal"], kind="invoice", number="SYN-DRAFT", status="draft")
            setup.add(draft)
            await setup.commit()
            draft_id = draft.id
    cmd, _ = await command(api, ids, base, doc_id=draft_id)
    ready, release = asyncio.Event(), asyncio.Event()
    async with factory() as writer, factory() as reader, factory() as observer:
        deal = await reader.get(Deal, ids["deal"])
        if draft_id is not None:
            assert (await reader.get(DealDocument, draft_id)).status == "draft"
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        commit = writer.commit

        async def pending_commit():
            ready.set()  # The real issuance has flushed its receipt and holds its book/deal locks.
            await asyncio.wait_for(release.wait(), 15)
            await commit()

        monkeypatch.setattr(writer, "commit", pending_commit)
        issuer = asyncio.create_task(issue(writer, core, user, DealAccess("all"), ids["deal"],
                                          InvoiceIssueInput.model_validate(cmd), draft_id))
        journal = None
        try:
            await asyncio.wait_for(ready.wait(), 10)
            journal = asyncio.create_task(project_journal_payments(reader, core.services, user, [deal]))
            async with asyncio.timeout(10):
                while True:
                    await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                    blocked = await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))"), {"pid": writer_pid})
                    if blocked:
                        break
                    assert not journal.done(), "Journal must wait for the pending real issuance, even without an issued invoice yet"
                    await asyncio.sleep(0.02)
            release.set()
            issued = await issuer
            result = (await journal)[ids["deal"]]
            assert result.payment == "invoiced" and result.source == "ledger"
            assert result.invoice_number == issued["document"]["number"]
        finally:
            release.set()
            if journal is not None:
                if not journal.done():
                    journal.cancel()
                await asyncio.gather(journal, return_exceptions=True)
            await asyncio.gather(issuer, return_exceptions=True)
            await reader.rollback()
