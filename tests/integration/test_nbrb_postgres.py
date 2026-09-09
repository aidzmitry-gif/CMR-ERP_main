"""Run only against the disposable NBRB database, never a configured ERP database."""
import asyncio
import os
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.domain.models import AuditLog
from core.domain.reference import CurrencyRate
from core.services import nbrb
from core.services.nbrb_sync import sync_currency

pytestmark = pytest.mark.skipif(os.getenv("NBRB_TEST_POSTGRES") != "1", reason="isolated NBRB database only")


async def test_concurrent_rate_fetch_and_reference_sync():
    engine = create_async_engine("postgresql+psycopg://nbrb_test:nbrb_local_test@127.0.0.1:15437/nbrb_test")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    day = date(2026, 9, 2)
    calls = []

    async def handle(request):
        calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"Cur_Abbreviation": "USD", "Date": str(day),
                                        "Cur_OfficialRate": "3.1234", "Cur_Scale": 1})

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            async def fetch():
                async with factory() as session:
                    rate = await nbrb.quote(session, "USD", day, client=client)
                    await session.commit()
                    return rate

            results = await asyncio.gather(fetch(), fetch())
            assert results[0] == results[1]
            assert len(calls) <= 1

        async def sync():
            async with factory() as session:
                await sync_currency(session, "USD", day)
                await session.commit()

        await asyncio.gather(sync(), sync())
        async with factory() as session:
            assert (await session.execute(select(func.count()).select_from(AuditLog).where(
                AuditLog.action == nbrb.ACTION, AuditLog.entity_ref == f"nbrb:USD:{day}"
            ))).scalar_one() == 1
            assert (await session.execute(select(func.count()).select_from(CurrencyRate).where(
                CurrencyRate.currency_code == "USD", CurrencyRate.start_date == day
            ))).scalar_one() == 1
    finally:
        await engine.dispose()
