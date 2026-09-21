"""PostgreSQL evidence that opening receipts cannot bind another organization."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import Account, OpeningImportReceipt, Organization, Policy
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


pytestmark = pytest.mark.integration


async def test_opening_import_guard_rejects_foreign_entry_and_keeps_valid_receipt_immutable(
    pg_factory, pg_book, posting
):
    """A receipt may only bind opening entries from its own legal entity."""
    async with pg_factory() as session:
        for table in ("organization", "account", "policy"):
            await session.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('accounting.{table}', 'id'), "
                    f"(SELECT max(id) FROM accounting.{table}))"
                )
            )
        organization = Organization(
            name="Synthetic foreign opening company",
            unp="888888888",
        )
        session.add(organization)
        await session.flush()

        policy = Policy(
            organization_id=organization.id,
            effective_from=date(2026, 1, 1),
            reference="Synthetic foreign opening policy",
            inventory_method="specific",
            allocation_basis="direct_cost",
            depreciation_method="straight_line",
            normative_reference="Synthetic opening guard fixture",
            normative_verified=True,
            approved_by="tester",
        )
        session.add(policy)
        session.add_all(
            [
                Account(
                    organization_id=organization.id,
                    code="51",
                    title="Foreign settlement account",
                    category="asset",
                    valid_from=date(2026, 1, 1),
                    required_dimensions=[],
                    currency_tracking=True,
                    quantity_tracking=False,
                    cash=True,
                    normative_ref="Synthetic opening guard fixture",
                ),
                Account(
                    organization_id=organization.id,
                    code="80",
                    title="Foreign equity",
                    category="equity",
                    valid_from=date(2026, 1, 1),
                    required_dimensions=[],
                    currency_tracking=True,
                    quantity_tracking=False,
                    cash=False,
                    normative_ref="Synthetic opening guard fixture",
                ),
            ]
        )
        await session.flush()

        own_data = posting("own-opening", "51", "80", "100.00", opening=True)
        own_entry = await service.post(session, pg_book[0], own_data, "tester")
        foreign_data = posting("foreign-opening", "51", "80", "100.00", opening=True)
        foreign_data.policy_id = policy.id
        foreign_entry = await service.post(session, organization.id, foreign_data, "tester")

        valid_receipt = OpeningImportReceipt(
            organization_id=pg_book[0],
            request_key="00000000-0000-0000-0000-000000000701",
            batch="pg-opening-valid",
            protocol_version="opening-balance-v1",
            source_system="1c-export",
            source_digest="a" * 64,
            cutover_date=own_data.posting_date,
            entry_count=1,
            line_count=2,
            debit_total=Decimal("100.00"),
            credit_total=Decimal("100.00"),
            command_digest="b" * 64,
            evidence="Synthetic valid opening import evidence",
            entry_ids=[own_entry.id],
            snapshot={"entries": [{"entry_id": own_entry.id}]},
            digest="c" * 64,
            actor="tester",
        )
        session.add(valid_receipt)
        await session.flush()
        valid_receipt_id = valid_receipt.id
        foreign_entry_id = foreign_entry.id
        await session.commit()

    async with pg_factory() as session:
        forged_receipt = OpeningImportReceipt(
            organization_id=pg_book[0],
            request_key="00000000-0000-0000-0000-000000000702",
            batch="pg-opening-forged",
            protocol_version="opening-balance-v1",
            source_system="1c-export",
            source_digest="d" * 64,
            cutover_date=date(2026, 9, 1),
            entry_count=1,
            line_count=2,
            debit_total=Decimal("100.00"),
            credit_total=Decimal("100.00"),
            command_digest="e" * 64,
            evidence="Synthetic forged opening import evidence",
            entry_ids=[foreign_entry_id],
            snapshot={"entries": [{"entry_id": foreign_entry_id}]},
            digest="f" * 64,
            actor="tester",
        )
        session.add(forged_receipt)
        await session.flush()

        with pytest.raises(DBAPIError, match="same-organization opening entries"):
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.rollback()

    async with pg_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                text("UPDATE accounting.opening_import_receipt SET actor = 'forged' WHERE id = :id"),
                {"id": valid_receipt_id},
            )
        await session.rollback()
