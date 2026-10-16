"""V4 service admission, historical verification and late-cost arithmetic on PostgreSQL."""
# ruff: noqa: F811
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import ZeroValueInventoryDisposalReceipt
from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import (
    AllocatedZeroValueDisposalCommand,
    canonical_json,
    load_authenticated_zero_value_disposals,
    preview_standalone_zero_value_issue_basis,
    receipt_digest,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_finished_goods_inventory_postgres import _output_cost_command
from tests.accounting.test_inventory_allocation_api_postgres import output_sources
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_output_cost_postgres import run_migration

pytestmark = pytest.mark.integration


async def basis(session, org, command, cutoff=2147483647):
    return await session.scalar(text("SELECT accounting.zero_value_allocation_basis(:org,CAST(:c AS jsonb),:cutoff)"),
        {"org": org, "c": canonical_json(command), "cutoff": cutoff})


@pytest.mark.parametrize("method", ["fifo", "weighted_average"])
async def test_v4_issue_replays_complete_sources_and_late_cost(pg_factory, pg_book, method):
    policy_id, outputs = await output_sources(pg_factory, pg_book, method)
    async with pg_factory() as session:
        await service.post(session, pg_book[0], PostingInput(source="zero-v4-reverse-wip", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Synthetic zero output cost", lines=[
                LineInput(account="60", side="debit", amount="0.02"),
                *[LineInput(account="20", side="credit", amount="0.01", dimensions={"department": "SHOP", "order": order})
                  for order in ("ORDER-42", "ORDER-43")]]), "tester")
        for output_id in outputs:
            await confirm_output_cost_correction(session, pg_book[0], "2026-10",
                await _output_cost_command(session, pg_book[0], output_id), "tester")
        await run_migration(session, "0146_zero_value_allocation_basis.py", "upgrade")
        await run_migration(session, "0147_zero_value_allocation_runtime.py", "upgrade")
        await run_migration(session, "0147_zero_value_allocation_runtime.py", "downgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.zero_value_allocation_runtime_version()')")) is None
        await run_migration(session, "0147_zero_value_allocation_runtime.py", "upgrade")
        source_rows = (await session.execute(text("SELECT entry_id,id,dimensions FROM accounting.line WHERE entry_id IN (:a,:b) AND side='debit' ORDER BY entry_id,id"),
            {"a": outputs[0], "b": outputs[1]})).all()
        document = {"source": "zero-v4-basis", "source_version": 1, "document_date": "2026-10-29",
            "operation_date": "2026-10-30", "posting_date": "2026-10-31", "policy_id": policy_id,
            "account": "43", "warehouse": "Main", "sku": "SYN-WIDGET", "lot": "", "quantity": "3.1",
            "expense_account": "90.4", "expense_dimensions": {}, "explanation": "Synthetic complete zero allocation"}
        command = AllocatedZeroValueDisposalCommand(**{key: document[key] for key in (
            "source", "source_version", "document_date", "operation_date", "posting_date", "policy_id", "explanation")},
            command_version=4, operation="inventory_issue", valuation_method=method, document=document,
            basis_digest="0" * 64, destination_account="90.4", destination_dimensions={},
            inventory_layers=[{"source_entry_id": row.entry_id, "source_line_id": row.id, "inventory_account": "43",
                "inventory_dimensions": row.dimensions, "quantity": quantity}
                for row, quantity in zip(source_rows, ("2", "1.1"), strict=True)])
        snapshot = command.model_dump(mode="json")
        # Entryless revisions also consume the shared registration sequence.
        cutoff = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('accounting.entry','id'))"))
        original = await basis(session, pg_book[0], snapshot, cutoff)
        assert len(original) == 64 and original == await basis(session, pg_book[0], snapshot)
        wrong_selection = command.model_dump(mode="json")
        wrong_selection["inventory_layers"][0]["quantity"] = "1.1"
        wrong_selection["inventory_layers"][1]["quantity"] = "2"
        wrong_command = AllocatedZeroValueDisposalCommand.model_validate(wrong_selection)
        with pytest.raises(service.AccountingError, match="historical policy-selected"):
            await preview_standalone_zero_value_issue_basis(session, pg_book[0], wrong_command)
        savepoint = await session.begin_nested()
        try:
            forged_basis = await basis(session, pg_book[0], wrong_selection)
            forged = wrong_command.model_copy(update={"basis_digest": forged_basis})
            session.add(ZeroValueInventoryDisposalReceipt(organization_id=pg_book[0], source=forged.source,
                source_version=1, operation="inventory_issue", posting_date=forged.posting_date,
                policy_id=policy_id, command=forged.model_dump(mode="json"), basis_digest=forged_basis,
                digest=receipt_digest(pg_book[0], "tester", forged), actor="tester"))
            await session.flush()
            with pytest.raises(service.AccountingError, match="historical policy-selected"):
                await _output_cost_command(session, pg_book[0], outputs[0])
        finally:
            await savepoint.rollback()
        assert await preview_standalone_zero_value_issue_basis(session, pg_book[0], command) == original
        verified = command.model_copy(update={"basis_digest": original})
        receipt = await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified)
        assert (await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified)).id == receipt.id
        portions = (await session.execute(text("SELECT * FROM accounting.zero_allocation_cost_stream(:org,'43','Main','SYN-WIDGET','2026-10-31',NULL)"), {"org": pg_book[0]})).mappings().all()
        assert [r["quantity"] for r in portions] == [Decimal("2"), Decimal("1.1")]
        assert len({r["event_key"] for r in portions}) == 2
        assert all(r["receipt_id"] == receipt.id for r in portions)
        loaded = await load_authenticated_zero_value_disposals(session, pg_book[0])
        assert len(loaded) == 1 and loaded[0].receipt_id == receipt.id
        # A later value registration invalidates current approval, not its original cutoff.
        await service.post(session, pg_book[0], PostingInput(source="zero-v4-later-wip", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Synthetic later output expense", lines=[
                LineInput(account="20", side="debit", amount="1.00", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="1.00")]), "tester")
        correction = await _output_cost_command(session, pg_book[0], outputs[0])
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", correction, "tester")
        allocation = revision.preview["ledger_evidence"]["allocation"]
        disposed = [r for r in allocation if r["key"].startswith("zeroallocation:")]
        remaining = [r for r in allocation if r["key"].startswith("remaining")]
        assert sum(Decimal(str(r["desired"])) for r in disposed) == (Decimal("1.00") if method == "fifo" else Decimal("0.78"))
        assert sum(Decimal(str(r["desired"])) for r in remaining) == (Decimal("0.00") if method == "fifo" else Decimal("0.22"))
        assert (await confirm_output_cost_correction(session, pg_book[0], "2026-10", correction, "tester")).id == revision.id
        assert (await load_authenticated_zero_value_disposals(session, pg_book[0]))[0].receipt_id == receipt.id
        assert (await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified)).id == receipt.id
        assert await basis(session, pg_book[0], snapshot, cutoff) == original
        with pytest.raises(DBAPIError, match="Cannot downgrade"):
            async with session.begin_nested():
                await run_migration(session, "0147_zero_value_allocation_runtime.py", "downgrade")
