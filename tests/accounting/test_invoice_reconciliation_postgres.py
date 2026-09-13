import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.sales.access import DealAccess
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.documents import digest
from modules.sales.invoice_reconciliation import (
    InvoiceMoneyReconciliation,
    ReconciliationInput,
    confirm,
    preview,
)
from modules.sales.models import Deal, DealDocument
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory

pytestmark = pytest.mark.integration


async def test_concurrent_attestation_replay_and_database_immutability(pg_factory, pg_book):
    gateway = AccountingService()
    core = SimpleNamespace(services=SimpleNamespace(accounting=gateway))
    user = CurrentUser("tester", ["director"])
    async with pg_factory() as session:
        deal = Deal(number="PG-RECON", title="Synthetic", counterparty="Synthetic")
        session.add(deal)
        await session.flush()
        doc = DealDocument(deal_id=deal.id, kind="invoice", number="PG-RECON", status="posted",
            amount="100.00", issued_at=datetime(2026, 9, 1), original_html="Synthetic",
            content_sha256=digest("Synthetic"), snapshot_json={"currency": "BYN", "amount": "100.00"})
        session.add_all([doc, DealOwnership(deal_id=deal.id, organization_id=pg_book[0],
            snapshot={}, evidence="Synthetic", actor="tester")])
        await session.commit()
        doc_id = doc.id
        await gateway.source_owner_authority(session, pg_book[0], user)
        facts = await preview(pg_book[0], doc_id, (session, "tester"), DealAccess("all"), core, user)
        data = ReconciliationInput(source_key="PG-RECON", expected_basis_digest=facts["basis_digest"],
            history_from=facts["required_history_from"], history_through=date.today(),
            evidence="Synthetic reviewed source statements", source_references=["Synthetic statement register"],
            all_money_sources_checked=True)
        await session.commit()

    async def writer():
        async with pg_factory() as session:
            actor = await gateway.source_owner_authority(session, pg_book[0], user)
            result = await confirm(pg_book[0], doc_id, data, (session, actor), DealAccess("all"), core, user)
            await session.commit()
            return result["id"]

    first, second = await asyncio.gather(writer(), writer())
    assert first == second
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(InvoiceMoneyReconciliation)) == 1
    for statement in (
        "UPDATE sales.invoice_money_reconciliation SET actor='other'",
        "DELETE FROM sales.invoice_money_reconciliation",
        # Reach the immutable trigger despite the dependent fulfillment FK.
        # This runs only inside pg_factory's disposable acc_test_* database.
        "TRUNCATE sales.invoice_money_reconciliation CASCADE",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
            assert await session.scalar(select(func.count()).select_from(InvoiceMoneyReconciliation)) == 1
