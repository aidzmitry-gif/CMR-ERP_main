import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401
from tests.test_invoice_issuance import erp_money_flow
from tests.test_invoice_on_order import on_order_flow


async def test_pg_on_order_without_reserve_and_no_fake_digest(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        await on_order_flow(api, session)
        with pytest.raises(DBAPIError, match="reservation mode mismatch"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO sales.invoice_issuance_receipt
                    SELECT document_id, deal_id, organization_id, document_version, content_sha256,
                           snapshot_digest, repeat('a',64), request_key, request_hash, response, actor, created_at
                    FROM sales.invoice_issuance_receipt
                """))


async def test_pg_on_order_bank_receipt_and_refund(issuance_pg):  # noqa: F811
    api, factory = issuance_pg
    async with factory() as session:
        await erp_money_flow(api, session, reserve_mode="on_order")
