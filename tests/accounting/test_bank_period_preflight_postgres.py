"""Detect legacy inconsistencies without changing or masking them."""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from modules.accounting import service
from modules.accounting.models import SourceBinding
from modules.accounting.schemas import CloseInput
from modules.finance.models import BankTransaction
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_preflight_reports_legacy_closed_bank_source_without_mutation(pg_factory, pg_book):  # noqa: F811
    query = text(Path("modules/accounting/bank_period_preflight.sql").read_text(encoding="utf-8"))
    async with pg_factory() as session:
        await service.close_period(session, pg_book[0], "2026-09", CloseInput(
            expected_generation=0, evidence={key: "Synthetic preflight fixture" for key in service.CLOSE_STEPS}), "tester")
        await session.commit()
        # Reproduce the old SQL behavior before the additive bank triggers.
        source = BankTransaction(ext_id="LEGACY-CLOSED-BANK", occurred_on=date(2026, 9, 1), amount="120.00", currency="BYN")
        future = BankTransaction(ext_id="FUTURE-BANK", occurred_on=date(2026, 10, 1), amount="1.00", currency="BYN")
        session.add_all([source, future])
        await session.flush()
        source_id = source.id
        for row in [source, future]:
            session.add(SourceBinding(organization_id=pg_book[0], source_type="finance_bank_transaction", source_id=row.id,
                                      ownership="own", evidence="Legacy SQL fixture", actor="tester"))
        await session.commit()
        rows = (await session.execute(query)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["issue"] == "closed_period_unposted_bank"
        assert rows[0]["month"] == "2026-09"
        assert rows[0]["source_transaction_id"] == source_id
        assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-09'"), {"org": pg_book[0]}) is True
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_binding")) == 2
        assert (await session.execute(query)).mappings().all() == rows
