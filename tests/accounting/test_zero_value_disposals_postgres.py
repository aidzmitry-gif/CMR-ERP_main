"""PostgreSQL persistence evidence for the bounded zero-value issue receipt."""
# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from modules.accounting.models import (
    ProductionOutputTransferReceipt,
    ZeroValueInventoryDisposalReceipt,
)
from modules.accounting.production_output_cost_workflow import confirm_output_cost_correction
from modules.accounting.schemas import LineInput, PostingInput
from modules.accounting.zero_value_disposals import (
    ZeroValueDisposalCommand,
    canonical_json,
    preview_standalone_zero_value_issue_basis,
    receipt_digest,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_finished_goods_inventory_postgres import (
    _confirm_output,
    _output_cost_command,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def upgrade_0140(session):
    def upgrade(connection):
        migration = runpy.run_path("migrations/versions/0140_zero_value_disposals.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
    await (await session.connection()).run_sync(upgrade)


async def downgrade_0140(session):
    def downgrade(connection):
        migration = runpy.run_path("migrations/versions/0140_zero_value_disposals.py")
        with Operations.context(MigrationContext.configure(connection)):
            migration["downgrade"]()
    await (await session.connection()).run_sync(downgrade)


async def test_migration_0140_up_down_up_isolated(pg_factory):
    async with pg_factory() as session:
        await upgrade_0140(session)
        assert await session.scalar(text("SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt')"))
        await downgrade_0140(session)
        assert await session.scalar(text("SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt')")) is None
        await upgrade_0140(session)
        assert await session.scalar(text("SELECT to_regclass('accounting.inventory_zero_value_disposal_receipt')"))


def command(policy_id, output_id, line_id, **changes):
    body = {"operation": "inventory_issue", "source": "inventory:zero:output-42", "source_version": 1,
            "posting_date": "2026-10-31", "policy_id": policy_id, "basis_digest": "a" * 64,
            "destination_account": "20", "destination_dimensions": {"department": "SHOP", "order": "ORDER-42"},
            "inventory_layers": [{"source_entry_id": output_id, "source_line_id": line_id,
                                  "inventory_account": "43", "inventory_dimensions": {"warehouse": "Main", "sku": "SYN-WIDGET", "lot": "LOT-1"}, "quantity": "0.5"}],
            "explanation": "Verified zero value issue"}
    body.update(changes)
    return ZeroValueDisposalCommand(**body)


async def zeroed_output(factory, book):
    policy_id = await _confirm_output(factory, book)
    async with factory() as session:
        output = await session.scalar(select(ProductionOutputTransferReceipt).where(ProductionOutputTransferReceipt.organization_id == book[0]))
        await service.post(session, book[0], PostingInput(source="production:reverse-wip:zero", source_version=1,
            operation="manual", document_date="2026-10-31", operation_date="2026-10-31", posting_date="2026-10-31",
            policy_id=policy_id, rule_version="synthetic", explanation="Reverse all WIP", lines=[
                LineInput(account="20", side="credit", amount="100", dimensions={"department": "SHOP", "order": "ORDER-42"}),
                LineInput(account="60", side="debit", amount="100"),
            ]), "tester")
        revision = await confirm_output_cost_correction(session, book[0], "2026-10", await _output_cost_command(session, book[0], output.entry_id), "tester")
        assert revision.entry_id is not None
        output_line = await session.scalar(text("SELECT id FROM accounting.line WHERE entry_id=:id AND side='debit'"), {"id": output.entry_id})
        await session.commit()
    return policy_id, output.entry_id, output_line


async def test_persists_immutable_entryless_zero_issue_and_rejects_forgery(pg_factory, pg_book):
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await upgrade_0140(session)
        draft = command(policy_id, output_id, line_id)
        basis = await preview_standalone_zero_value_issue_basis(session, pg_book[0], draft)
        verified = draft.model_copy(update={"basis_digest": basis})
        snapshot = {"organization_id": pg_book[0], "actor": "tester", "command": verified.model_dump(mode="json")}
        assert receipt_digest(pg_book[0], "tester", verified) == await session.scalar(
            text("SELECT accounting.financial_sha(CAST(:snapshot AS jsonb))"), {"snapshot": canonical_json(snapshot)})
        saved = await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified)
        assert saved.entry_id is None and saved.registration_token > 0
        assert await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified) is saved
        await session.commit()
    async with pg_factory() as session:
        saved = await session.scalar(select(ZeroValueInventoryDisposalReceipt))
        with pytest.raises(ValueError, match="different content"):
            await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified.model_copy(update={"explanation": "Changed"}))
        stale = verified.model_copy(update={"source": "inventory:zero:stale", "source_version": 3})
        stale = stale.model_copy(update={
            "basis_digest": await preview_standalone_zero_value_issue_basis(session, pg_book[0], stale)})
        second = verified.model_copy(update={"source": "inventory:zero:second", "source_version": 2})
        second = second.model_copy(update={
            "basis_digest": await preview_standalone_zero_value_issue_basis(session, pg_book[0], second)})
        await register_standalone_zero_value_issue(session, pg_book[0], "tester", second)
        with pytest.raises(ValueError, match="basis changed"):
            await register_standalone_zero_value_issue(session, pg_book[0], "tester", stale)
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(text("UPDATE accounting.inventory_zero_value_disposal_receipt SET actor='forged' WHERE id=:id"), {"id": saved.id})
        await session.rollback()
        with pytest.raises(DBAPIError, match="basis source|source output layer"):
            await register_standalone_zero_value_issue(session, pg_book[0], "tester", verified.model_copy(
                update={"source": "inventory:zero:forged", "source_version": 2,
                        "inventory_layers": [verified.inventory_layers[0].model_copy(update={"source_line_id": line_id + 999})]}))
        await session.rollback()
        raw_command = verified.model_dump(mode="json")
        raw_command["source"] = "inventory:zero:raw-missing-quantity"
        raw_command["source_version"] = 4
        del raw_command["inventory_layers"][0]["quantity"]
        raw_basis = await session.scalar(text(
            "SELECT accounting.zero_value_disposal_basis(:org, CAST(:command AS jsonb), 2147483647)"),
            {"org": pg_book[0], "command": canonical_json(raw_command)})
        raw_command["basis_digest"] = raw_basis
        raw_digest = await session.scalar(text("SELECT accounting.financial_sha(CAST(:snapshot AS jsonb))"), {
            "snapshot": canonical_json({"organization_id": pg_book[0], "actor": "tester", "command": raw_command})})
        with pytest.raises(DBAPIError, match="layer schema"):
            await session.execute(text("""INSERT INTO accounting.inventory_zero_value_disposal_receipt
                (organization_id,source,source_version,operation,entry_id,posting_date,policy_id,command,basis_digest,digest,actor)
                VALUES (:organization_id,:source,:source_version,:operation,NULL,:posting_date,:policy_id,
                        CAST(:command AS json),:basis_digest,:digest,:actor)"""), {
                "organization_id": pg_book[0], "source": raw_command["source"], "source_version": 4,
                "operation": "inventory_issue", "posting_date": raw_command["posting_date"], "policy_id": policy_id,
                "command": canonical_json(raw_command), "basis_digest": raw_basis, "digest": raw_digest, "actor": "tester"})
        await session.rollback()
        with pytest.raises(DBAPIError, match="reserved by a zero-value"):
            await session.execute(text("""INSERT INTO accounting.entry
                (organization_id,source,source_version,operation,document_date,operation_date,posting_date,
                 policy_id,rule_version,explanation,opening,correction_of,digest,actor)
                VALUES (:org,:source,1,'inventory_issue','2026-10-31','2026-10-31','2026-10-31',
                 :policy,'synthetic','must be rejected',false,NULL,:digest,'tester')"""),
                {"org": pg_book[0], "source": verified.source, "policy": policy_id, "digest": "0" * 64})
        await session.rollback()
        with pytest.raises(DBAPIError, match="Cannot downgrade zero-value disposals with history"):
            await downgrade_0140(session)
