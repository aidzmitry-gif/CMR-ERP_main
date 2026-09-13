"""Real database guards and concurrent explicit client claims, synthetic data only."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty
from core.services.auth import CurrentUser
from modules.accounting.gateway import AccountingService
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import (
    ClientBindingInput,
    DealClientBinding,
    claim_deal_client_binding,
    preview_snapshot,
)
from modules.sales.models import Deal
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory

pytestmark = pytest.mark.integration


async def test_concurrent_claim_and_database_immutability(pg_factory, pg_book):
    org = pg_book[0]
    gateway = AccountingService()
    async with pg_factory() as session:
        deal = Deal(number="PG-CLIENT", title="Synthetic", counterparty="Same name")
        clients = [Counterparty(name="Same name", unp=f"11111111{i}") for i in range(2)]
        session.add_all([deal, *clients])
        await session.flush()
        session.add(DealOwnership(deal_id=deal.id, organization_id=org,
                                  snapshot={}, evidence="Synthetic", actor="tester"))
        await session.flush()
        deal_id = deal.id
        payloads = [ClientBindingInput(counterparty_id=cp.id,
            expected_snapshot=await preview_snapshot(session, org, deal, cp.id),
            evidence="Synthetic exact identity") for cp in clients]
        await session.commit()

    async def writer(payload):
        async with pg_factory() as session:
            actor = await gateway.source_owner_authority(session, org, CurrentUser("tester", ["director"]))
            deal = await session.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
            try:
                await claim_deal_client_binding(org, deal_id, payload, (session, actor, deal))
                await session.commit()
                return 201
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(*(writer(payload) for payload in payloads))) == [201, 409]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(DealClientBinding)) == 1
        binding = await session.get(DealClientBinding, deal_id)
        winner = next(p for p in payloads if p.counterparty_id == binding.counterparty_id)
    assert await writer(winner) == 201

    for sql in (
        "UPDATE sales.deal_client_binding SET evidence = 'changed'",
        "DELETE FROM sales.deal_client_binding",
        "TRUNCATE sales.deal_client_binding",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()
    async with pg_factory() as session:
        cp = await session.get(Counterparty, winner.counterparty_id)
        cp.name = "Renamed later"
        await session.commit()
        binding = await session.get(DealClientBinding, deal_id)
        assert binding.snapshot["client"]["name"] == "Same name"


async def test_database_rejects_forged_client_snapshot(pg_factory, pg_book):
    async with pg_factory() as session:
        deal = Deal(number="PG-FORGED", title="Synthetic", counterparty="Synthetic")
        cp = Counterparty(name="Exact client", unp="123456789")
        session.add_all([deal, cp])
        await session.flush()
        session.add(DealOwnership(deal_id=deal.id, organization_id=pg_book[0],
                                  snapshot={}, evidence="Synthetic", actor="tester"))
        await session.flush()
        snapshot = await preview_snapshot(session, pg_book[0], deal, cp.id)
        snapshot["client"]["name"] = "Forged client"
        session.add(DealClientBinding(deal_id=deal.id, organization_id=pg_book[0],
            counterparty_id=cp.id, snapshot=snapshot, evidence="Synthetic", actor="tester"))
        with pytest.raises(DBAPIError, match="snapshot differs"):
            await session.flush()
        await session.rollback()
