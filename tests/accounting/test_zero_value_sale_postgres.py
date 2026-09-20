"""Isolated PostgreSQL acceptance for additive zero-sale binding."""
# ruff: noqa: F811
import asyncio
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import routes, sales, service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    Account,
    Entry,
    InventorySaleReceipt,
    Line,
    Organization,
    ZeroValueInventoryDisposalReceipt,
)
from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import (
    ZeroValueSaleCommand,
    load_authenticated_zero_value_disposals,
    parse_zero_value_command,
    preview_standalone_zero_value_issue_basis,
    receipt_digest,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_finished_goods_inventory_postgres import (
    _output_cost_command,
    sale_document,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_disposals_postgres import command as issue_command
from tests.accounting.test_zero_value_disposals_postgres import zeroed_output
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def test_zero_sale_migration_empty_roundtrip(pg_factory):
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py"):
            await run_migration(session, revision, "upgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.validate_zero_sale_link(integer)')"))
        await run_migration(session, "0143_zero_value_sales.py", "downgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.validate_zero_sale_link(integer)')")) is None
        await run_migration(session, "0143_zero_value_sales.py", "upgrade")
        await session.commit()


@pytest.mark.parametrize("vat_rate", ["0", "20"])
async def test_zero_sale_persists_revenue_and_quantity_once(pg_factory, pg_book, vat_rate):
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    policy_id, output_id, _ = await zeroed_output(pg_factory, pg_book)
    document = sale_document(policy_id).model_copy(update={"quantity": Decimal("0.5"), "vat_rate": Decimal(vat_rate)})
    async with pg_factory() as session:
        if vat_rate == "20":
            for code, category in (("90.2", "income"), ("68.2", "liability")):
                if not await session.scalar(select(Account.id).where(Account.organization_id == pg_book[0], Account.code == code)):
                    session.add(Account(organization_id=pg_book[0], code=code, title="Synthetic VAT",
                        category=category, valid_from=date(2026, 1, 1), required_dimensions=[],
                        currency_tracking=False, quantity_tracking=False, cash=False, normative_ref="Synthetic"))
            await session.commit()
    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=None, accounting=AccountingService()))

    async def session_dependency():
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    base = f"/accounting/organizations/{pg_book[0]}/sales"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(base + "/posting-preview", json=document.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        prepared = response.json()
        assert prepared["cost"]["issue_cost_byn"] == "0.00"

    async def confirm_once():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(base + "/confirm", json={**document.model_dump(mode="json"),
                "basis_digest": prepared["cost"]["basis_digest"], "digest": prepared["digest"]})
            assert response.status_code == 201, response.text
            return response.json()["id"]

    identifiers = await asyncio.gather(confirm_once(), confirm_once())
    assert identifiers[0] == identifiers[1]
    entry_id = identifiers[0]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0], Entry.source == document.source)) == 1
        assert await session.scalar(select(func.count()).select_from(ZeroValueInventoryDisposalReceipt).where(
            ZeroValueInventoryDisposalReceipt.entry_id == entry_id)) == 1
        receipt = await session.scalar(select(ZeroValueInventoryDisposalReceipt).where(
            ZeroValueInventoryDisposalReceipt.entry_id == entry_id))
        assert receipt.registration_token == entry_id
        lines = (await session.scalars(select(Line).where(Line.entry_id == entry_id))).all()
        assert all(line.quantity is None and line.amount > 0 for line in lines)
        assert [(line.account_code, line.side, line.amount) for line in sorted(lines, key=lambda row: row.id)] == (
            [("62", "debit", 120), ("90.1", "credit", 120), ("90.2", "debit", 20), ("68.2", "credit", 20)]
            if vat_rate == "20" else [("62", "debit", 100), ("90.1", "credit", 100)])
        assert (await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
                                    prepared["digest"], "tester")).id == entry_id
        remaining = await sales.prepare(session, pg_book[0], document.model_copy(update={"source": "sale:zero:next"}))
        assert remaining["cost"]["book_quantity"] == "1.500000"
        await service.post(session, pg_book[0], PostingInput(
            source="sale-zero-late-wip", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Late production cost after zero sale",
            lines=[LineInput(account="20", side="debit", amount="100",
                             dimensions={"department": "SHOP", "order": "ORDER-42"}),
                   LineInput(account="60", side="credit", amount="100")]), "tester")
        revised = await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            await _output_cost_command(session, pg_book[0], output_id), "tester")
        revision_lines = (await session.scalars(select(Line).where(Line.entry_id == revised.entry_id))).all()
        assert {(line.account_code, line.side, line.amount) for line in revision_lines} == {
            ("20", "credit", 100), ("43", "debit", 75), ("90.4", "debit", 25)}
        await session.commit()
    async with pg_factory() as session:
        await sales.verify_receipt(session, pg_book[0], entry_id)
        with pytest.raises(DBAPIError, match="Cannot downgrade 0143"):
            async with session.begin_nested():
                await run_migration(session, "0143_zero_value_sales.py", "downgrade")


@pytest.mark.parametrize("failure", ["missing_quantity", "forged_money", "forged_dimensions", "foreign_organization"])
async def test_zero_sale_rejects_partial_or_forged_transaction(pg_factory, pg_book, failure):
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
                         "0142_zero_value_command_dates.py", "0143_zero_value_sales.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    policy_id, _, _ = await zeroed_output(pg_factory, pg_book)
    document = sale_document(policy_id).model_copy(update={"quantity": Decimal("0.5")})
    if failure == "foreign_organization":
        async with pg_factory() as session:
            session.add(Organization(id=990043, name="Synthetic other organization", unp="990000043"))
            await session.commit()
    async with pg_factory() as session:
        prepared = await sales.prepare(session, pg_book[0], document)
        posting = PostingInput.model_validate(prepared["posting"])
        if failure == "forged_money":
            posting = posting.model_copy(update={"lines": [line.model_copy(update={"amount": Decimal("999")})
                                                           for line in posting.lines]})
        if failure == "forged_dimensions":
            posting = posting.model_copy(update={"lines": [posting.lines[0], posting.lines[1].model_copy(
                update={"dimensions": {**posting.lines[1].dimensions, "vat_basis": "Forged basis"}})]})
        digest = service.digest(posting)
        entry = await service.post(session, pg_book[0], posting, "tester", inventory_sale=True)
        session.add(InventorySaleReceipt(entry_id=entry.id, organization_id=pg_book[0],
            command=document.model_dump(mode="json"), cost=json.loads(json.dumps(prepared["cost"], default=str)),
            posting=posting.model_dump(mode="json"), digest=digest, actor="tester"))
        if failure != "missing_quantity":
            command = ZeroValueSaleCommand.model_validate(prepared["zero_value_command"])
            receipt_org = 990043 if failure == "foreign_organization" else pg_book[0]
            session.add(ZeroValueInventoryDisposalReceipt(entry_id=entry.id, organization_id=receipt_org,
                source=command.source, source_version=command.source_version, operation="inventory_sale",
                posting_date=command.posting_date, policy_id=policy_id, command=command.model_dump(mode="json"),
                basis_digest=command.basis_digest, digest=receipt_digest(receipt_org, "tester", command), actor="tester"))
        with pytest.raises(DBAPIError, match="requires its quantity receipt|differs from its monetary terms|another organization"):
            await session.commit()
        await session.rollback()
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Entry).where(
            Entry.organization_id == pg_book[0], Entry.source == document.source)) == 0
        assert await session.scalar(select(func.count()).select_from(ZeroValueInventoryDisposalReceipt).where(
            ZeroValueInventoryDisposalReceipt.organization_id == pg_book[0])) == 0


async def test_0143_preserves_legacy_issue_history(pg_factory, pg_book):
    async with pg_factory() as session:
        for revision in ("0140_zero_value_disposals.py", "0141_zero_value_output_cost.py", "0142_zero_value_command_dates.py"):
            await run_migration(session, revision, "upgrade")
        await session.commit()
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        for version in (1, 2):
            raw = issue_command(policy_id, output_id, line_id, source=f"legacy:issue:{version}").model_dump(mode="json")
            if version == 2:
                raw.update(command_version=2, document_date="2026-10-29", operation_date="2026-10-30")
            command = parse_zero_value_command(raw)
            basis = await preview_standalone_zero_value_issue_basis(session, pg_book[0], command)
            await register_standalone_zero_value_issue(session, pg_book[0], "tester", command.model_copy(update={"basis_digest": basis}))
        await session.commit()
    async with pg_factory() as session:
        before = await load_authenticated_zero_value_disposals(session, pg_book[0])
        await run_migration(session, "0143_zero_value_sales.py", "upgrade")
        await session.commit()
    async with pg_factory() as session:
        after = await load_authenticated_zero_value_disposals(session, pg_book[0])
        assert after == before
        for value in ("3.0", '"3"', "true", "4"):
            with pytest.raises(DBAPIError, match="version"):
                async with session.begin_nested():
                    await session.execute(text("SELECT accounting.validate_zero_value_disposal_command(CAST(:value AS jsonb))"),
                        {"value": '{"command_version":' + value + ',"operation":"inventory_sale","sale_document":{}}'})
