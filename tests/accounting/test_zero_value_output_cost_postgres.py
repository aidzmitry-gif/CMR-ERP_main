"""Migration smoke evidence for 0141 zero-value output-cost integration."""
# ruff: noqa: F811
import json
import runpy
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import ProductionOutputTransferReceipt
from modules.accounting.production_output_cost_workflow import (
    ProductionOutputCostConfirmInput,
    ProductionOutputCostPreviewInput,
    confirm_output_cost_correction,
    preview_output_cost_correction,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import (
    preview_standalone_zero_value_issue_basis,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_postgres import (
    pg_book,  # noqa: F401
    pg_factory,  # noqa: F401
)
from tests.accounting.test_zero_value_disposals_postgres import command, zeroed_output

pytestmark = pytest.mark.integration


async def run_migration(session, revision, action):
    def run(connection):
        migration = runpy.run_path(f"migrations/versions/{revision}")
        with Operations.context(MigrationContext.configure(connection)):
            migration[action]()
    await (await session.connection()).run_sync(run)


async def test_0141_up_down_up_without_zero_history(pg_factory):
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await run_migration(session, "0141_zero_value_output_cost.py", "upgrade")
        await session.commit()
        assert await session.scalar(text("SELECT pronargdefaults FROM pg_proc WHERE oid='accounting.output_cost_revision_evidence(integer,integer,date,integer,integer)'::regprocedure")) == 0
        await run_migration(session, "0141_zero_value_output_cost.py", "downgrade")
        await run_migration(session, "0141_zero_value_output_cost.py", "upgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.guard_output_cost_revision()')"))


async def test_specific_zero_receipt_gets_typed_output_cost_destination(pg_factory, pg_book):
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await run_migration(session, "0141_zero_value_output_cost.py", "upgrade")
        await session.commit()
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book, normative_verified=True)
    async with pg_factory() as session:
        draft = command(policy_id, output_id, line_id)
        basis = await preview_standalone_zero_value_issue_basis(session, pg_book[0], draft)
        await register_standalone_zero_value_issue(session, pg_book[0], "tester", draft.model_copy(update={"basis_digest": basis}))
        await service.post(session, pg_book[0], PostingInput(
            source="zero-output-late-wip", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Late WIP", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="100"),
            ]), "tester")
        receipt = await session.get(ProductionOutputTransferReceipt, output_id)
        preview = await preview_output_cost_correction(session, pg_book[0], "2026-10", ProductionOutputCostPreviewInput(
            original_entry_id=receipt.entry_id, posting_date="2026-10-31", request_evidence="Late WIP after zero issue"))
        zero = next(row for row in preview["destinations"] if row["destination"] and row["destination"]["kind"] == "zero")
        remaining = next(row for row in preview["destinations"] if row["kind"] == "remaining")
        assert zero["amount_byn"] == "25.00" and remaining["amount_byn"] == "75.00"
        confirmation = ProductionOutputCostConfirmInput(
            original_entry_id=output_id, posting_date="2026-10-31", request_evidence="Late WIP after zero issue",
            request_key=uuid4(), basis_digest=preview["basis_digest"])
        revision = await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")
        await session.commit()
        revision_id = revision.id
        revision_entry_id = revision.entry_id
        revision_token = revision.registration_token
        original_evidence = preview["ledger_evidence"]
    async with pg_factory() as session:
        assert (await confirm_output_cost_correction(session, pg_book[0], "2026-10", confirmation, "tester")).id == revision_id
        await service.post(session, pg_book[0], PostingInput(
            source="zero-output-next-wip", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Next late WIP", lines=[
                LineInput(account="20", side="debit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="credit", amount="100"),
            ]), "tester")
        request = ProductionOutputCostPreviewInput(
            original_entry_id=output_id, posting_date="2026-10-31", request_evidence="Second late cost")
        second = await preview_output_cost_correction(session, pg_book[0], "2026-10", request)
        allocations = second["ledger_evidence"]["allocation"]
        remaining = next(row for row in allocations if row["key"] == "remaining")
        disposed = next(row for row in allocations if row["key"].startswith("zero:"))
        assert Decimal(str(remaining["desired"])) == 150
        assert Decimal(str(disposed["desired"])) == 50
        assert Decimal(str(remaining["delta"])) == 75
        assert Decimal(str(disposed["delta"])) == 25
        await confirm_output_cost_correction(session, pg_book[0], "2026-10",
            ProductionOutputCostConfirmInput(**request.model_dump(), request_key=uuid4(),
                                             basis_digest=second["basis_digest"]), "tester")
        await session.commit()
    async with pg_factory() as session:
        unchanged = await preview_output_cost_correction(session, pg_book[0], "2026-10", request)
        assert unchanged["ledger_evidence"]["matrix"] == []
        historical = await session.scalar(text(
            "SELECT accounting.output_cost_revision_evidence(:org,:output,CAST(:day AS date),:entry,:token)::text"
        ), {"org": pg_book[0], "output": output_id, "day": "2026-10-31",
            "entry": revision_entry_id, "token": revision_token})
        assert json.loads(historical, parse_float=str) == original_evidence
        with pytest.raises(DBAPIError, match="preview differs from authenticated"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO accounting.production_output_cost_revision
                    (organization_id,original_entry_id,sequence,previous_id,entry_id,month,
                     request_key,command,preview,posting,actor)
                    SELECT organization_id,original_entry_id,sequence+1,id,NULL,month,
                           :request,command,'{}'::json,NULL,actor
                    FROM accounting.production_output_cost_revision
                    WHERE original_entry_id=:output ORDER BY sequence DESC LIMIT 1
                """), {"request": str(uuid4()), "output": output_id})
        with pytest.raises(DBAPIError, match="Cannot downgrade 0141"):
            async with session.begin_nested():
                await run_migration(session, "0141_zero_value_output_cost.py", "downgrade")
        await session.execute(text(
            "UPDATE accounting.period SET closed=true,closed_generation=generation,evidence=CAST(:evidence AS json) "
            "WHERE organization_id=:org AND month='2026-10'"
        ), {"org": pg_book[0], "evidence": json.dumps({key: "Synthetic checked" for key in service.CLOSE_STEPS})})
        with pytest.raises(service.AccountingError, match="Closed-period"):
            await preview_output_cost_correction(session, pg_book[0], "2026-10", request)
        with pytest.raises(DBAPIError, match="original policy and an open period"):
            async with session.begin_nested():
                await session.execute(text("""
                    INSERT INTO accounting.production_output_cost_revision
                    (organization_id,original_entry_id,sequence,previous_id,entry_id,month,
                     request_key,command,preview,posting,actor)
                    SELECT organization_id,original_entry_id,sequence+1,id,NULL,month,
                           :request,command,'{}'::json,NULL,actor
                    FROM accounting.production_output_cost_revision
                    WHERE original_entry_id=:output ORDER BY sequence DESC LIMIT 1
                """), {"request": str(uuid4()), "output": output_id})
