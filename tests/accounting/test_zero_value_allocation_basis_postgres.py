"""V4 historical DB evidence; does not enable receipt persistence."""
# ruff: noqa: F811
from copy import deepcopy

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
    receipt_digest,
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
async def test_v4_basis_binds_multiple_origins_cutoff_and_preserves_disabled_write_path(pg_factory, pg_book, method):
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
        changed_date = deepcopy(snapshot)
        changed_date["document_date"] = changed_date["document"]["document_date"] = "2026-10-28"
        assert await basis(session, pg_book[0], changed_date) != original
        for mutation, message in (("duplicate", "repeats an origin"), ("quantity", "not conserved"),
                                  ("foreign", "prior authenticated output"), ("version", "versioned command"),
                                  ("operation_null", "versioned command"), ("method_null", "versioned command")):
            changed = deepcopy(snapshot)
            if mutation == "duplicate":
                changed["inventory_layers"][1] = deepcopy(changed["inventory_layers"][0])
            elif mutation == "quantity":
                changed["document"]["quantity"] = "3.2"
            elif mutation == "foreign":
                changed["inventory_layers"][0]["source_entry_id"] += 100000
            elif mutation == "operation_null":
                changed["operation"] = None
            elif mutation == "method_null":
                changed["valuation_method"] = None
            else:
                changed["command_version"] = 4.0
            with pytest.raises(DBAPIError, match=message):
                async with session.begin_nested():
                    await basis(session, pg_book[0], changed)
        verified = command.model_copy(update={"basis_digest": original})
        with pytest.raises(DBAPIError, match="Zero-value|Zero sale"):
            async with session.begin_nested():
                session.add(ZeroValueInventoryDisposalReceipt(organization_id=pg_book[0], source=verified.source,
                    source_version=1, operation="inventory_issue", entry_id=None, posting_date=verified.posting_date,
                    policy_id=policy_id, command=verified.model_dump(mode="json"), basis_digest=original,
                    digest=receipt_digest(pg_book[0], "tester", verified), actor="tester"))
                await session.flush()
        # A later value registration invalidates current approval, not its original cutoff.
        await service.post(session, pg_book[0], PostingInput(source="zero-v4-later-wip", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Synthetic later output expense", lines=[
                LineInput(account="20", side="debit", amount="1.00", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="1.00")]), "tester")
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            await _output_cost_command(session, pg_book[0], outputs[0]), "tester")
        assert await basis(session, pg_book[0], snapshot) != original
        assert await basis(session, pg_book[0], snapshot, cutoff) == original
        await run_migration(session, "0146_zero_value_allocation_basis.py", "downgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.zero_value_allocation_basis(integer,jsonb,integer)')")) is None
        await run_migration(session, "0146_zero_value_allocation_basis.py", "upgrade")
        assert await basis(session, pg_book[0], snapshot, cutoff) == original
