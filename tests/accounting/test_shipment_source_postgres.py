"""Whole-act completeness must require independently verified posting coverage."""

# Imported pytest fixtures are intentionally injected by matching parameter names.
# ruff: noqa: F811

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import SourceControl
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


@pytest.mark.parametrize("mode", ["DEFERRED", "IMMEDIATE"])
async def test_matching_cost_entry_cannot_complete_unverified_whole_shipment(
    pg_factory, pg_book, posting, mode
):
    org, policy = pg_book
    source = f"wms:physical-shipment:{org}:{uuid4()}"
    async with pg_factory() as session:
        session.add(SourceControl(organization_id=org, source=source, version=1, month="2026-09"))
        data = posting(source, "90.4", "60")
        data.policy_id = policy
        entry = await service.post(session, org, data, "tester")
        entry_id = entry.id
        await session.commit()
        with pytest.raises(DBAPIError, match="shipment|receipt"):
            await session.execute(text(f"SET CONSTRAINTS ALL {mode}"))
            await session.execute(
                text(
                    "UPDATE accounting.source_control SET entry_id=:entry WHERE organization_id=:org AND source=:source"
                ),
                {"entry": entry_id, "org": org, "source": source},
            )
            await session.commit()
        await session.rollback()
        assert (
            await session.scalar(
                select(SourceControl.entry_id).where(SourceControl.source == source)
            )
            is None
        )


@pytest.mark.parametrize("version,month", [(2, "2026-09"), (1, "2026-10"), (2, "2026-10")])
async def test_pending_physical_act_identity_cannot_advance_like_mutable_document(
    pg_factory, pg_book, version, month
):
    org, _ = pg_book
    source = f"wms:physical-shipment:{org}:{uuid4()}"
    async with pg_factory() as session:
        session.add(SourceControl(organization_id=org, source=source, version=1, month="2026-09"))
        await session.commit()
        with pytest.raises(DBAPIError, match="shipment|immutable"):
            await session.execute(
                text(
                    "UPDATE accounting.source_control SET version=:version,month=:month WHERE organization_id=:org AND source=:source"
                ),
                {"org": org, "source": source, "version": version, "month": month},
            )
            await session.commit()
        await session.rollback()
        control = await session.scalar(select(SourceControl).where(SourceControl.source == source))
        assert (control.version, control.month, control.entry_id) == (1, "2026-09", None)


async def test_mutable_document_source_can_still_advance(pg_factory, pg_book):
    org, _ = pg_book
    source = "sales:document:123"
    async with pg_factory() as session:
        session.add(SourceControl(organization_id=org, source=source, version=1, month="2026-09"))
        await session.commit()
        await session.execute(
            text(
                "UPDATE accounting.source_control SET version=2,month='2026-10' WHERE organization_id=:org AND source=:source"
            ),
            {"org": org, "source": source},
        )
        await session.commit()
        control = await session.scalar(select(SourceControl).where(SourceControl.source == source))
        assert (control.version, control.month, control.entry_id) == (2, "2026-10", None)
