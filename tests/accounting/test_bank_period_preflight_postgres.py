"""Detect legacy inconsistencies without changing or masking them."""
import asyncio
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from modules.accounting import service
from modules.accounting.models import Organization, Period, SourceBinding
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("accounting_pg_revision", ["0133"], indirect=True)
async def test_preflight_reports_legacy_closed_bank_source_without_mutation(pg_factory):  # noqa: F811
    query = text(Path("modules/accounting/bank_period_preflight.sql").read_text(encoding="utf-8"))
    async with pg_factory() as session:
        # Reproduce history on the real pre-0134 schema. Current API/model
        # fixtures include later columns and correctly refuse this history.
        organization = Organization(name="Synthetic bank preflight", unp="000000133")
        session.add(organization)
        await session.flush()
        organization_id = organization.id
        # Use only policy columns present at 0133, with the same synthetic
        # settings as the normal book fixture. Keep its closing guards active.
        await session.execute(text(
            "INSERT INTO accounting.policy (organization_id, effective_from, reference, "
            "inventory_method, allocation_basis, depreciation_method, normative_reference, "
            "normative_verified, approved_by) VALUES (:org, :effective_from, 'TEST ONLY', "
            "'specific', 'direct_cost', 'straight_line', 'synthetic control fixture', true, 'tester')"
        ), {"org": organization_id, "effective_from": date(2026, 1, 1)})
        period = Period(organization_id=organization_id, month="2026-09", closed=False,
                        generation=0, closed_generation=None, evidence={})
        session.add(period)
        await session.flush()
        period.closed = True
        period.closed_generation = 0
        period.evidence = {key: "Synthetic preflight fixture" for key in service.CLOSE_STEPS}
        await session.flush()
        source_ids = []
        for ext_id, occurred_on, amount in [
            ("LEGACY-CLOSED-BANK", date(2026, 9, 1), "120.00"),
            ("FUTURE-BANK", date(2026, 10, 1), "1.00"),
        ]:
            source_id = await session.scalar(text(
                "INSERT INTO finance.bank_transaction (ext_id, occurred_on, amount, currency) "
                "VALUES (:ext_id, :occurred_on, :amount, 'BYN') RETURNING id"
            ), {"ext_id": ext_id, "occurred_on": occurred_on, "amount": amount})
            source_ids.append(source_id)
            session.add(SourceBinding(organization_id=organization_id, source_type="finance_bank_transaction", source_id=source_id,
                                      ownership="own", evidence="Legacy SQL fixture", actor="tester"))
        await session.commit()
        rows = (await session.execute(query)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["issue"] == "closed_period_unposted_bank"
        assert rows[0]["month"] == "2026-09"
        assert rows[0]["source_transaction_id"] == source_ids[0]
        assert await session.scalar(text("SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-09'"), {"org": organization_id}) is True
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_binding")) == 2
        assert (await session.execute(query)).mappings().all() == rows
        bank_rows = (await session.execute(text(
            "SELECT id, ext_id, occurred_on, amount, currency FROM finance.bank_transaction ORDER BY id"
        ))).all()

    # Installation must reject the same inconsistency without advancing the
    # registered schema or mutating the legacy rows it is asking us to review.
    async with pg_factory() as session:
        target = session.bind.url.render_as_string(hide_password=False)
    result = await asyncio.to_thread(
        subprocess.run, [sys.executable, "-m", "alembic", "upgrade", "0134"],
        env={**os.environ, "AIOS_DATABASE_URL": target, "AIOS_ENVIRONMENT": "dev"},
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "Bank period guard preflight failed" in result.stderr
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0133"
        assert (await session.execute(query)).mappings().all() == rows
        assert (await session.execute(text(
            "SELECT id, ext_id, occurred_on, amount, currency FROM finance.bank_transaction ORDER BY id"
        ))).all() == bank_rows
        assert await session.scalar(text("SELECT count(*) FROM accounting.source_binding")) == 2
        assert await session.scalar(text(
            "SELECT closed FROM accounting.period WHERE organization_id=:org AND month='2026-09'"
        ), {"org": organization_id}) is True
