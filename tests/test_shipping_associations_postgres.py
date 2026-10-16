"""Frozen unallocated DDL on a fresh database; no runtime migration allocation."""
# ruff: noqa: F811 -- pytest imports the shared isolated database fixture
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_fresh_database_cleanup_after_schema_setup_failure(monkeypatch):
    from tests.accounting import test_postgres as fixtures

    real_engine = fixtures.create_async_engine
    allocated = []
    admin_url = []

    def capture_engine(url, **kwargs):
        from sqlalchemy.engine import make_url

        parsed = make_url(url)
        if parsed.database.startswith("acc_test_"):
            allocated.append(parsed.database)
        else:
            admin_url.append(parsed)
        return real_engine(url, **kwargs)

    def broken_schema(*args, **kwargs):
        raise RuntimeError("synthetic proposal setup failure")

    monkeypatch.setattr(fixtures, "create_async_engine", capture_engine)
    monkeypatch.setattr(fixtures.runpy, "run_path", broken_schema)
    generator = fixtures.pg_factory.__wrapped__()
    with pytest.raises(RuntimeError, match="synthetic proposal setup failure"):
        await anext(generator)
    await generator.aclose()
    assert len(allocated) == len(admin_url) == 1
    observer = real_engine(admin_url[0])
    try:
        async with observer.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                                           {"name": allocated[0]}) == 0
    finally:
        await observer.dispose()


async def test_shipping_history_statement_guards(pg_factory):
    tables = (
        "sales.shipping_envelope",
        "sales.order_invoice_association",
        "office.shipping_request",
        "office.office_invoice_association",
        "office.shipping_review_assignment",
    )
    async with pg_factory() as session:
        for table in tables:
            assert await session.scalar(text("SELECT to_regclass(:name)"), {"name": table}) == table
            await session.rollback()
            for statement in (f"UPDATE {table} SET id=id", f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"):
                # Even zero affected rows and cascade truncation cannot bypass
                # append-only history. The fixture owns this entire fresh DB.
                with pytest.raises(DBAPIError, match="Shipping history is immutable"):
                    await session.execute(text(statement))
                await session.rollback()
