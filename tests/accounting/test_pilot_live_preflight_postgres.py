"""A PostgreSQL read-only snapshot can use the normal OSV exporter safely."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from modules.accounting import reconciliation
from scripts import accounting_pilot_live_preflight as live_preflight
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_erp_osv_in_repeatable_read_only_transaction(pg_factory, pg_book):
    async with pg_factory() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        session.info["accounting_read_only_snapshot"] = True
        raw = await reconciliation.erp_snapshot(
            session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30),
        )
        parsed = reconciliation.parse_snapshot(raw)
        assert parsed["organization_id"] == str(pg_book[0])
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        assert await session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        await session.rollback()


async def test_live_runner_opens_a_database_enforced_read_only_transaction(
        pg_factory, pg_book, monkeypatch):
    async def probe(session, manifest_path):
        assert manifest_path == Path("synthetic-manifest.json")
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"
        raw = await reconciliation.erp_snapshot(
            session, pg_book[0], date(2026, 9, 1), date(2026, 9, 30),
        )
        return {"ok": True, "bytes": len(raw)}

    monkeypatch.setattr(live_preflight, "verify_live", probe)
    url = pg_factory.kw["bind"].url.render_as_string(hide_password=False)
    result = await live_preflight._run(Path("synthetic-manifest.json"), url)
    assert result["ok"] is True
    assert result["bytes"] > 0
