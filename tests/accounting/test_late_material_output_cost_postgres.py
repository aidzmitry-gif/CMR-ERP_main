"""Command and prospective SQL checks; full atomic package remains separate."""
# ruff: noqa: F811 -- imported fixtures are registered by pytest.
from copy import deepcopy

import pytest

from modules.accounting.late_cost_posting import ExpenseAccounts, candidate, material_candidate
from modules.accounting.late_cost_preview import calculate
from modules.accounting.late_cost_receipts import (
    LateCostCommand,
    MaterialLateCostCommand,
    PoolLateCostCommand,
    parse_command,
)
from modules.accounting.service import AccountingError
from tests.accounting.test_late_cost_conversion import _data, _history, _policy
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.integration.test_invoice_issuance_postgres import issuance_pg  # noqa: F401


def prepared():
    history = _history("BYN")
    history["lots"][0].update(remaining_quantity="6", production_quantity="4", production_disposals=[{
        "entry_id": 3, "inventory_line": 2, "quantity": "4", "expense_account": "20",
        "expense_dimensions": {"department": "SHOP", "order": "ORDER-1"}}])
    return calculate(42, 9, _data(conversion=None, capitalizable_amount_byn="100"), _policy(), history)


def test_material_candidate_conserves_full_supplier_liability_and_rejects_legacy_enablement():
    result = prepared()
    posting = material_candidate(result, ExpenseAccounts(settlement_account="60"))
    assert [(r.account, r.side, str(r.amount)) for r in posting.lines] == [
        ("41", "debit", "60.00"), ("20", "debit", "40.00"), ("60", "credit", "100.00")]
    with pytest.raises(AccountingError, match="verified cost-layer"):
        candidate(result, ExpenseAccounts(settlement_account="60"))


@pytest.mark.parametrize("change", ["amount", "account", "duplicate"])
def test_material_candidate_rejects_unbound_or_overallocated_origins(change):
    result = deepcopy(prepared())
    share = next(r for r in result["shares"] if r["destination"] == "production")
    origin = share["production_origins"][0]
    if change == "amount":
        origin["amount_byn"] = "39.99"
    elif change == "account":
        origin["expense_account"] = "90.4"
    else:
        share["production_origins"].append(deepcopy(origin))
    with pytest.raises(AccountingError):
        material_candidate(result, ExpenseAccounts(settlement_account="60"))


def test_version_dispatch_preserves_legacy_snapshot_and_rejects_invalid_selection():
    command = LateCostCommand(allocation=_data(), accounts=ExpenseAccounts(settlement_account="60"))
    saved = command.model_dump(mode="json")
    assert parse_command(saved).model_dump(mode="json") == saved
    assert "command_version" not in saved
    for version in [True, 2.0, "2", 3]:
        with pytest.raises(ValueError):
            parse_command({**saved, "command_version": version})
    material = MaterialLateCostCommand.model_validate({**saved, "command_version": 2})
    assert material.material_outputs == []
    with pytest.raises(ValueError):
        MaterialLateCostCommand.model_validate({**saved, "material_outputs": [
            {"output_entry_id": 5, "amount_byn": "1.00"}, {"output_entry_id": 5, "amount_byn": "1.00"}]})


def test_pool_command_is_versioned_and_preserves_signed_output_amounts():
    command = LateCostCommand(allocation=_data(), accounts=ExpenseAccounts(settlement_account="60"))
    saved = command.model_dump(mode="json")
    for version in (True, 3.0, "3", 2):
        with pytest.raises(ValueError):
            PoolLateCostCommand.model_validate({**saved, "command_version": version})
    with pytest.raises(ValueError):
        PoolLateCostCommand.model_validate({**saved, "command_version": 3, "material_outputs": [
            {"output_entry_id": 5, "amount_byn": "0.00"}]})
    pool = PoolLateCostCommand.model_validate({**saved, "command_version": 3, "material_outputs": [
        {"output_entry_id": 5, "amount_byn": "-1.00"}]})
    assert pool.material_outputs[0].amount_byn == -1
    with pytest.raises(ValueError):
        PoolLateCostCommand.model_validate({**saved, "command_version": 3, "material_outputs": [
            {"output_entry_id": 5, "amount_byn": "-1.00"},
            {"output_entry_id": 5, "amount_byn": "1.00"},
        ]})
    with pytest.raises(ValueError):
        parse_command(pool.model_dump(mode="json"))


@pytest.mark.integration
@pytest.mark.parametrize("accounting_pg_revision", ["0150"], indirect=True)
async def test_0151_and_0152_registered_empty_roundtrip(pg_factory):
    import asyncio
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import text

    async with pg_factory() as session:
        target = session.bind.url.render_as_string(hide_password=False)
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == "0150"
        assert await session.scalar(text("SELECT to_regclass('accounting.late_material_package')")) is None

    async def migrate(action, revision):
        result = await asyncio.to_thread(
            subprocess.run, [sys.executable, "-m", "alembic", action, revision],
            env={**os.environ, "AIOS_DATABASE_URL": target, "AIOS_ENVIRONMENT": "dev"},
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr[-3000:]
        async with pg_factory() as session:
            assert await session.scalar(text("SELECT version_num FROM alembic_version")) == revision

    signed = text("SELECT to_regprocedure('accounting.preview_output_cost_with_signed_wip(integer,integer,date,integer,jsonb,integer)')")
    await migrate("upgrade", "0152")
    async with pg_factory() as session:
        assert await session.scalar(signed) is not None
    # Follow the registered dependency order:0152 down,then0151 down.
    await migrate("downgrade", "0150")
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT to_regclass('accounting.late_material_package')")) is None
        assert await session.scalar(signed) is None
    await migrate("upgrade", "0152")
    await migrate("downgrade", "0151")
    async with pg_factory() as session:
        assert await session.scalar(text("SELECT to_regclass('accounting.late_material_package')")) is not None
        assert await session.scalar(signed) is None
    await migrate("upgrade", "0152")
    async with pg_factory() as session:
        assert await session.scalar(signed) is not None


@pytest.mark.integration
@pytest.mark.parametrize("dispose_half", [False, True])
@pytest.mark.parametrize("delta_amount", ["2.00", "-2.00"])
async def test_prospective_wip_matrix_matches_real_ledger_without_preview_writes(pg_factory, pg_book, dispose_half, delta_amount, issuance_pg):
    import json
    from decimal import Decimal

    from sqlalchemy import text

    from modules.accounting import service
    from modules.accounting.production_output_transfer import (
        ProductionOutputTransferConfirmInput,
        confirm_output_transfer,
        prepare_output_transfer,
    )
    from modules.accounting.schemas import LineInput, PostingInput
    from tests.accounting.test_inventory_allocation_cost_stream_postgres import (
        accepted_production_outputs,
    )
    from tests.accounting.test_production_output_transfer_postgres import (
        _seed_production_book,
        _seed_wip,
        transfer_input,
    )

    policy_id = await _seed_production_book(pg_factory, pg_book)
    await _seed_wip(pg_factory, pg_book, policy_id, [("SHOP", "ORDER-42", "12.50")])
    production, warehouse, documents, identities = await accepted_production_outputs(
        issuance_pg[0], pg_factory, pg_book, same_lot=False, order_ids=(42,), lot_by_order={42: "LOT-1"})
    async with pg_factory() as session:
        data = transfer_input(policy_id).model_copy(update={"output_document_ids": [documents[42]]})
        preview = await prepare_output_transfer(session, pg_book[0], "2026-10", data, production, warehouse)
        row = await confirm_output_transfer(session, pg_book[0], "2026-10",
            ProductionOutputTransferConfirmInput.model_validate({**data.model_dump(mode="json"),
                "basis_digest": preview["basis_digest"], "digest": preview["digest"]}), "tester",
            production=production, warehouse_gateway=warehouse)
        await session.commit()
        if dispose_half:
            from modules.accounting.inventory_issues import confirm, prepare
            from modules.accounting.schemas import InventoryIssueDocument

            issue = InventoryIssueDocument(source="prospective-half-disposal", source_version=1,
                document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
                policy_id=policy_id, account="43", warehouse="Main", sku="SYN-WIDGET", lot="LOT-1",
                quantity="1", expense_account="90.4", expense_dimensions={}, explanation="Synthetic half disposal",
                **identities)
            cost, posting = await prepare(session, pg_book[0], issue)
            await confirm(session, pg_book[0], issue, cost["basis_digest"], service.digest(posting), "tester")
            await session.commit()
        counts = await session.scalar(text("SELECT count(*) FROM accounting.entry"))
        generation = await session.scalar(text("SELECT generation FROM accounting.organization WHERE id=:org"), {"org": pg_book[0]})
        params = {"org": pg_book[0], "output": row.id,
                  "delta": json.dumps([{"account": "20", "dimensions": {"department": "SHOP", "order": "ORDER-42"}, "amount_byn": delta_amount}])}
        predicted = json.loads(await session.scalar(text(
            "SELECT accounting.preview_output_cost_with_signed_wip(:org,:output,'2026-10-31',NULL,CAST(:delta AS jsonb),NULL)::text"), params), parse_float=Decimal)
        assert await session.scalar(text("SELECT count(*) FROM accounting.entry")) == counts
        assert await session.scalar(text("SELECT generation FROM accounting.organization WHERE id=:org"), params) == generation
        signed = Decimal(delta_amount)
        expected_matrix = {("20", "credit" if signed > 0 else "debit", abs(signed)),
                           ("43", "debit" if signed > 0 else "credit", abs(signed) / (2 if dispose_half else 1))}
        if dispose_half:
            expected_matrix.add(("90.4", "debit" if signed > 0 else "credit", abs(signed) / 2))
        assert {(r["account"], r["side"], Decimal(str(r["amount"]))) for r in predicted["matrix"]} == expected_matrix
        await service.post(session, pg_book[0], PostingInput(
            source="prospective-wip-proof", source_version=1, operation="manual",
            document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Prospective evidence comparison",
            lines=[LineInput(account="20", side="debit" if signed > 0 else "credit", amount=abs(signed), dimensions={"department": "SHOP", "order": "ORDER-42"}),
                   LineInput(account="60", side="credit" if signed > 0 else "debit", amount=abs(signed))]), "tester")
        actual = json.loads(await session.scalar(text(
            "SELECT accounting.output_cost_revision_evidence(:org,:output,'2026-10-31',NULL)::text"), params), parse_float=Decimal)
        assert actual["matrix"] == predicted["matrix"]
        assert actual["allocation"] == predicted["allocation"]
        with pytest.raises(Exception, match="cannot be negative"):
            async with session.begin_nested():
                await session.scalar(text(
                    "SELECT accounting.preview_output_cost_with_signed_wip(:org,:output,'2026-10-31',NULL,"
                    "CAST(:delta AS jsonb),NULL)::text"), {**params, "delta": json.dumps([{
                        "account": "20", "dimensions": {"department": "SHOP", "order": "ORDER-42"},
                        "amount_byn": "-20.00"}])})
