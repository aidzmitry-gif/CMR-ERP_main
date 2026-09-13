import asyncio
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from core.services.auth import CurrentUser
from modules.accounting import seller_profiles
from modules.accounting.gateway import AccountingService
from modules.accounting.models import SellerProfile
from modules.accounting.schemas import SellerProfileInput
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory
from tests.accounting.test_seller_profiles import payload

pytestmark = pytest.mark.integration


async def test_concurrent_profile_editions_and_sql_immutability(pg_factory, pg_book):
    gateway = AccountingService()
    user = CurrentUser("tester", ["director"])
    org = pg_book[0]

    async def save(key):
        async with pg_factory() as session:
            await gateway.source_owner_authority(session, org, user)
            try:
                result = await seller_profiles.create(
                    session, org, SellerProfileInput(**payload(source_key=key)), "tester")
                await session.commit()
                return 201, result
            except HTTPException as exc:
                await session.rollback()
                return exc.status_code, None

    results = await asyncio.gather(save("first"), save("second"))
    assert sorted(code for code, _ in results) == [201, 409]
    expected = next(row for code, row in results if code == 201)
    async with pg_factory() as session:
        assert len((await session.scalars(select(SellerProfile))).all()) == 1
        assert await gateway.invoice_seller(session, org, user, date(2026, 9, 1), "BYN") == expected
    for statement in (
        "UPDATE accounting.seller_profile SET evidence='changed'",
        "DELETE FROM accounting.seller_profile",
        "TRUNCATE accounting.seller_profile",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement))
            await session.rollback()
