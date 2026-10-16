"""Shared immutable intent claims against real source and organization locks."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from core.runtime.app import create_app
from core.services.shipping_payload import shipping_intent_digest
from modules.logistics import shipment_writer
from modules.logistics.models import ShippingExecution
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_logistics_invoice_binding import exact  # noqa: F401
from tests.test_logistics_relay_postgres import pg  # noqa: F401
from tests.test_shipping_payload import payload


async def claim(session, core, exact_invoice, intent=None):
    intent = intent or payload()["intent"]
    await shipment_writer.source(session, core, exact_invoice)
    return await core.services.logistics.claim_execution(session, exact_invoice=exact_invoice, intent=intent,
        expected_digest=shipping_intent_digest(exact_invoice, intent))


async def test_claim_match_conflict_and_rollback(session, api, exact):  # noqa: F811
    core = create_app().state.core
    first = await claim(session, core, exact)
    await session.commit()
    assert await claim(session, core, exact) == first
    with pytest.raises(HTTPException) as error:
        await claim(session, core, exact, {**payload()["intent"], "route_to": "Other"})
    assert error.value.status_code == 409
    await session.rollback()
    assert len(list(await session.scalars(select(ShippingExecution)))) == 1
    row = await session.get(ShippingExecution, first["execution_id"])
    row.intent_digest = "0"*64
    with pytest.raises(ValueError, match="immutable"):
        await session.flush()
    await session.rollback()
    assert (await session.get(ShippingExecution, first["execution_id"])).intent_digest == first["intent_digest"]


async def test_claim_rollback_does_not_publish_execution(session, api, exact):  # noqa: F811
    core = create_app().state.core
    first = await claim(session, core, exact)
    await session.rollback()
    assert await session.get(ShippingExecution, first["execution_id"]) is None


@pytest.mark.parametrize("different", [False, True])
async def test_pg_concurrent_producers_claim_one_execution(pg, different):  # noqa: F811
    async def producer(index):
        async with pg.factory() as session:
            intent = payload()["intent"]
            if different and index:
                intent["route_to"] = "Other"
            try:
                result = await claim(session, pg.core, pg.exact, intent)
                await session.commit()
                return result["execution_id"]
            except HTTPException as exc:
                await session.rollback()
                assert exc.status_code == 409
                return "conflict"
    results = await asyncio.gather(producer(0), producer(1))
    if different:
        assert results.count("conflict") == 1
    else:
        assert results[0] == results[1]
    async with pg.factory() as session:
        assert len(list(await session.scalars(select(ShippingExecution)))) == 1


async def test_pg_execution_immutable_sql_guards(pg):  # noqa: F811
    async with pg.factory() as session:
        first = await claim(session, pg.core, pg.exact)
        await session.commit()
        for sql in ["UPDATE logistics.shipping_execution SET intent_digest='bad'",
                    "DELETE FROM logistics.shipping_execution", "TRUNCATE logistics.shipping_execution"]:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(sql))
            await session.rollback()
        assert (await session.get(ShippingExecution, first["execution_id"])).intent_digest == first["intent_digest"]
