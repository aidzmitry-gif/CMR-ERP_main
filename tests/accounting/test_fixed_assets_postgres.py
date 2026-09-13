"""PostgreSQL evidence for the reviewed fixed-asset register and depreciation."""
# ruff: noqa: F811 -- pytest fixtures are imported for registration.

from __future__ import annotations

import asyncio
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import fixed_assets, service
from modules.accounting.models import (
    Account,
    Entry,
    FixedAssetDepreciationReceipt,
    FixedAssetRegisterEntry,
    Line,
)
from modules.accounting.schemas import PostingInput
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def seed_fixed_asset_accounts(factory, pg_book):
    async with factory() as session:
        await session.execute(text(
            "SELECT setval(pg_get_serial_sequence('accounting.account','id'), "
            "(SELECT max(id) FROM accounting.account))"
        ))
        session.add_all([
            Account(organization_id=pg_book[0], code="01.1", title="Synthetic equipment",
                    category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic fixed-asset evidence"),
            Account(organization_id=pg_book[0], code="02.1", title="Synthetic accumulated depreciation",
                    category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic fixed-asset evidence"),
            Account(organization_id=pg_book[0], code="26", title="Synthetic depreciation expense",
                    category="expense", valid_from=date(2026, 1, 1), required_dimensions=[],
                    currency_tracking=False, quantity_tracking=False, cash=False,
                    normative_ref="Synthetic fixed-asset evidence"),
        ])
        await session.commit()


def acquisition(policy_id: int) -> PostingInput:
    return PostingInput.model_validate({
        "source": "fixed-asset:acquisition:001", "source_version": 1, "operation": "manual",
        "document_date": "2026-09-01", "operation_date": "2026-09-01", "posting_date": "2026-09-01",
        "policy_id": policy_id, "rule_version": "synthetic-fixed-asset-v1",
        "explanation": "Synthetic reviewed fixed-asset acquisition",
        "lines": [
            {"account": "01.1", "side": "debit", "amount": "1200.00"},
            {"account": "60", "side": "credit", "amount": "1200.00"},
        ],
    })


async def register_input(session, pg_book, source):
    line = await session.scalar(select(Line).where(
        Line.entry_id == source.id, Line.side == "debit", Line.account_code == "01.1",
    ))
    return fixed_assets.FixedAssetRegisterInput.model_validate({
        "request_key": "00000000-0000-0000-0000-000000000101",
        "asset_key": "asset:equipment:001", "source_entry_id": source.id,
        "source_line_id": line.id, "expected_source_digest": source.digest,
        "name": "Synthetic станок", "inventory_number": "ОС-001",
        "acquisition_date": "2026-09-01", "commissioning_date": "2026-09-01",
        "depreciation_start": "2026-09-01", "cost": "1200.00", "residual_value": "0.00",
        "useful_life_months": 12, "depreciation_method": "straight_line",
        "asset_account": "01.1", "accumulated_account": "02.1", "expense_account": "26",
        "dimensions": {"department": "ADMIN"},
        "evidence": "Synthetic акт приёма-передачи и карточка ОС проверены бухгалтером",
    })


async def test_fixed_asset_register_and_depreciation_are_replayable_and_immutable(pg_factory, pg_book):
    await seed_fixed_asset_accounts(pg_factory, pg_book)
    async with pg_factory() as session:
        source = await service.post(session, pg_book[0], acquisition(pg_book[1]), "tester")
        await session.commit()

    async with pg_factory() as session:
        data = await register_input(session, pg_book, await session.get(Entry, source.id))
        preview = await fixed_assets.prepare_register(session, pg_book[0], data)
        assert preview["status"] == "reviewed_fixed_asset"
        confirmed = fixed_assets.FixedAssetRegisterConfirmInput.model_validate({
            **data.model_dump(mode="json"), "digest": preview["digest"],
        })

    async def confirm_register_once():
        async with pg_factory() as session:
            try:
                row = await fixed_assets.confirm_register(session, pg_book[0], confirmed, "tester")
                await session.commit()
                return row.id
            except BaseException:
                await session.rollback()
                raise

    first, second = await asyncio.gather(confirm_register_once(), confirm_register_once())
    assert first == second

    async with pg_factory() as session:
        asset = await session.get(FixedAssetRegisterEntry, first)
        assert asset is not None
        depreciation = fixed_assets.FixedAssetDepreciationInput.model_validate({
            "request_key": "00000000-0000-0000-0000-000000000102", "asset_id": asset.id,
            "month": "2026-09", "expected_asset_digest": asset.digest, "policy_id": pg_book[1],
            "posting_date": "2026-09-30", "dimensions": {},
            "evidence": "Synthetic расчёт амортизации за месяц сверил бухгалтер",
        })
        dep_preview = await fixed_assets.prepare_depreciation(session, pg_book[0], depreciation)
        assert dep_preview["posting_available"] is True
        assert dep_preview["calculation"]["amount"] == "100.00"
        dep_confirmed = fixed_assets.FixedAssetDepreciationConfirmInput.model_validate({
            **depreciation.model_dump(mode="json"), "digest": dep_preview["digest"],
        })

    async def confirm_depreciation_once():
        async with pg_factory() as session:
            try:
                row = await fixed_assets.confirm_depreciation(
                    session, pg_book[0], dep_confirmed, "tester"
                )
                await session.commit()
                return row.entry_id
            except BaseException:
                await session.rollback()
                raise

    dep_first, dep_second = await asyncio.gather(confirm_depreciation_once(), confirm_depreciation_once())
    assert dep_first == dep_second

    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(FixedAssetRegisterEntry)) == 1
        assert await session.scalar(select(func.count()).select_from(FixedAssetDepreciationReceipt)) == 1
        entry = await session.get(Entry, dep_first)
        assert entry is not None and entry.operation == "fixed_asset_depreciation"
        lines = (await session.scalars(select(Line).where(Line.entry_id == dep_first).order_by(Line.id))).all()
        assert [(line.account_code, line.side, str(line.amount), line.dimensions) for line in lines] == [
            ("26", "debit", "100.00", {"department": "ADMIN", "asset": "asset:equipment:001"}),
            ("02.1", "credit", "100.00", {"department": "ADMIN", "asset": "asset:equipment:001"}),
        ]
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text(
                "UPDATE accounting.fixed_asset_register_entry SET actor='forged' WHERE id=:asset"
            ), {"asset": first})
        await session.rollback()

    async with pg_factory() as session:
        forged = fixed_assets.FixedAssetDepreciationReceipt(
            entry_id=dep_first, organization_id=pg_book[0], asset_id=first, month="2026-09",
            request_key=str(uuid4()), command={"request_key": str(uuid4()), "month": "2026-09"},
            calculation={"method": "straight_line"}, posting={}, digest="0" * 64, actor="tester",
        )
        session.add(forged)
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()
