"""Allocated zero-sale migration and durable workflow acceptance."""
# ruff: noqa: F811
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import sales, service, zero_value_disposals
from modules.accounting.models import Account, Entry
from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import load_authenticated_zero_value_disposals
from tests.accounting.test_finished_goods_inventory_postgres import (
    _output_cost_command,
    sale_document,
)
from tests.accounting.test_inventory_allocation_api_postgres import application, output_sources
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def test_allocated_sale_migration_empty_roundtrip(pg_factory):
    async with pg_factory() as session:
        for revision in (
            "0140_zero_value_disposals.py", "0141_zero_value_output_cost.py",
            "0142_zero_value_command_dates.py", "0143_zero_value_sales.py",
            "0144_inventory_explicit_allocation_guards.py", "0145_inventory_allocation_cost_stream.py",
            "0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
            "0148_zero_value_allocated_sales.py",
        ):
            await run_migration(session, revision, "upgrade")
        assert await session.scalar(text("SELECT accounting.zero_value_allocated_sale_version()")) == 4
        await run_migration(session, "0148_zero_value_allocated_sales.py", "downgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.zero_value_allocated_sale_version()')")) is None
        assert await session.scalar(text("SELECT accounting.zero_value_allocation_runtime_version()")) == 4
        await run_migration(session, "0148_zero_value_allocated_sales.py", "upgrade")


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
@pytest.mark.parametrize("vat_rate", ["0", "20"])
async def test_allocated_zero_sale_has_one_quantity_and_real_revenue(pg_factory, pg_book, method, vat_rate, monkeypatch):
    policy_id, outputs = await output_sources(pg_factory, pg_book, method)
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(source="zero-sale-reverse-wip", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Synthetic zero output cost", lines=[
                LineInput(account="60", side="debit", amount="0.02"),
                *[LineInput(account="20", side="credit", amount="0.01", dimensions={"department": "SHOP", "order": order})
                  for order in ("ORDER-42", "ORDER-43")]]), "tester")
        for output_id in outputs:
            await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                await _output_cost_command(session, pg_book[0], output_id), "tester")
        for revision in ("0146_zero_value_allocation_basis.py", "0147_zero_value_allocation_runtime.py",
                         "0148_zero_value_allocated_sales.py"):
            await run_migration(session, revision, "upgrade")
        if vat_rate == "20":
            for code, category in (("90.2", "income"), ("68.2", "liability")):
                if not await session.scalar(select(Account.id).where(Account.organization_id == pg_book[0], Account.code == code)):
                    session.add(Account(organization_id=pg_book[0], code=code, title="Synthetic VAT", category=category,
                        valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=False,
                        quantity_tracking=False, cash=False, normative_ref="Synthetic"))
            await session.flush()
        document = sale_document(policy_id).model_copy(update={"lot": "", "quantity": Decimal("3.1"), "vat_rate": Decimal(vat_rate)})
        await session.commit()
        base = f"/accounting/organizations/{pg_book[0]}/sales"
        async with AsyncClient(transport=ASGITransport(app=application(pg_factory)), base_url="http://test") as client:
            response = await client.post(base + "/posting-preview", json=document.model_dump(mode="json"))
            assert response.status_code == 200, response.text
            prepared = response.json()
            confirmation = {**document.model_dump(mode="json"), "basis_digest": prepared["cost"]["basis_digest"],
                            "digest": prepared["digest"]}
            response = await client.post(base + "/confirm", json=confirmation)
            assert response.status_code == 201, response.text
            entry_id = response.json()["id"]
            retry = await client.post(base + "/confirm", json=confirmation)
            assert retry.status_code == 201 and retry.json()["id"] == entry_id, retry.text
            changed = await client.post(base + "/confirm", json={**confirmation, "quantity": "3.0"})
            assert changed.status_code == 422, changed.text
            foreign = await client.post(f"/accounting/organizations/{pg_book[0] + 1000}/sales/posting-preview",
                                        json=document.model_dump(mode="json"))
            assert foreign.status_code in {403, 404}, foreign.text
        assert prepared["zero_value_command"]["command_version"] == 4
        assert len(prepared["zero_value_command"]["inventory_layers"]) == 2
        assert "source_allocation_version" not in prepared["cost"]
        entry = await session.get(Entry, entry_id)
        assert (await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
            prepared["digest"], "tester", source_allocations=True)).id == entry.id
        zeros = await load_authenticated_zero_value_disposals(session, pg_book[0])
        assert len(zeros) == 1 and zeros[0].registration_token == entry.id
        assert await session.scalar(text("SELECT count(*) FROM accounting.line WHERE entry_id=:id"), {"id": entry.id}) == (2 if vat_rate == "0" else 4)
        assert await session.scalar(text("SELECT count(*) FROM accounting.inventory_zero_value_disposal_receipt WHERE entry_id=:id"), {"id": entry.id}) == 1
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        if method == "fifo" and vat_rate == "0":
            # Orchestration proof: an incorrect server-selected allocation must
            # fail an existing V4 retry through its historical loader.
            original_loader = zero_value_disposals.load_authenticated_zero_value_disposals

            async def rejected_loader(current_session, current_org, *, before_registration_token=None):
                assert current_session is session and current_org == pg_book[0]
                if before_registration_token == entry.id:
                    return await original_loader(current_session, current_org,
                                                 before_registration_token=before_registration_token)
                assert before_registration_token == entry.id + 1
                raise service.AccountingError("historical policy-selected quantities differ")

            monkeypatch.setattr(zero_value_disposals, "load_authenticated_zero_value_disposals", rejected_loader)
            with pytest.raises(service.AccountingError, match="historical policy-selected"):
                await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
                                    prepared["digest"], "tester", source_allocations=True)
            monkeypatch.setattr(zero_value_disposals, "load_authenticated_zero_value_disposals", original_loader)
        await service.post(session, pg_book[0], PostingInput(source="zero-sale-late-wip", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Synthetic late expense", lines=[
                LineInput(account="20", side="debit", amount="1.00", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="1.00")]), "tester")
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            await _output_cost_command(session, pg_book[0], outputs[0]), "tester")
        disposed = [r for r in revision.preview["ledger_evidence"]["allocation"] if r["key"].startswith("zeroallocation:")]
        assert sum(Decimal(str(r["desired"])) for r in disposed) == (Decimal("1.00") if method == "fifo" else Decimal("0.78"))
        assert (await sales.confirm(session, pg_book[0], document, prepared["cost"]["basis_digest"],
            prepared["digest"], "tester", source_allocations=True)).id == entry.id
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with pytest.raises(DBAPIError, match="Cannot downgrade allocated sale history"):
            async with session.begin_nested():
                await run_migration(session, "0148_zero_value_allocated_sales.py", "downgrade")
