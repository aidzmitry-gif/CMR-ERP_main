"""Database-authenticated replay evidence for zero-value disposal receipts."""
# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
import pytest
from sqlalchemy import select

from modules.accounting import inventory_cost, service
from modules.accounting.models import Entry, Line, Organization, Period, Policy
from modules.accounting.schemas import InventoryIssuePreviewInput, LineInput, PostingInput
from modules.accounting.service import AccountingError
from modules.accounting.zero_value_disposals import (
    load_authenticated_zero_value_disposals,
    parse_zero_value_command,
    preview_standalone_zero_value_issue_basis,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_disposals_postgres import command, upgrade_0140, zeroed_output

pytestmark = pytest.mark.integration


def issue_request(policy_id, quantity="1.5"):
    return InventoryIssuePreviewInput(policy_id=policy_id, posting_date="2026-10-31", account="43",
                                      warehouse="Main", sku="SYN-WIDGET", lot="LOT-1", quantity=quantity)


async def receipt_with_database_basis(session, org_id, draft):
    basis = await preview_standalone_zero_value_issue_basis(session, org_id, draft)
    return await register_standalone_zero_value_issue(
        session, org_id, "tester", draft.model_copy(update={"basis_digest": basis}))


async def test_loader_replays_authenticated_history_and_respects_registration_cutoff(pg_factory, pg_book):
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await upgrade_0140(session)
        await receipt_with_database_basis(session, pg_book[0], command(policy_id, output_id, line_id))
        await session.commit()

    async with pg_factory() as session:
        policy = await session.get(Policy, policy_id)
        rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
            Entry.organization_id == pg_book[0], Line.account_code == "43").order_by(
                Entry.posting_date, Entry.id, Line.id))).all()
        from modules.accounting.late_cost_receipts import verified_value_lines

        verified = await verified_value_lines(session, pg_book[0], rows, None)
        result = await inventory_cost.replay_issue_result(
            session, policy, rows, pg_book[0], issue_request(policy_id), verified_value_lines=verified)
        assert result["book_quantity"] == "1.500000" and result["book_value_byn"] == "0.00"
        assert sum(item["zero_value_disposal"] for item in result["evidence"] if "zero_value_disposal" in item) == 1

        later_entry = await service.post(session, pg_book[0], PostingInput(
            source="zero-loader-cutoff", source_version=1, operation="manual", document_date="2026-10-31",
            operation_date="2026-10-31", posting_date="2026-10-31", policy_id=policy_id,
            rule_version="synthetic", explanation="Registration-cutoff marker", lines=[
                LineInput(account="60", side="debit", amount="1"),
                LineInput(account="20", side="credit", amount="1", dimensions={"department": "SHOP", "order": "ORDER-42"}),
            ]), "tester")
        await session.commit()
        cutoff = later_entry.id

    async with pg_factory() as session:
        late = command(policy_id, output_id, line_id, source="inventory:zero:late", source_version=2)
        await receipt_with_database_basis(session, pg_book[0], late)
        await session.commit()

    async with pg_factory() as session:
        policy = await session.get(Policy, policy_id)
        rows = (await session.execute(select(Entry, Line).join(Line, Line.entry_id == Entry.id).where(
            Entry.organization_id == pg_book[0], Line.account_code == "43").order_by(
                Entry.posting_date, Entry.id, Line.id))).all()
        from modules.accounting.late_cost_receipts import verified_value_lines

        verified = await verified_value_lines(session, pg_book[0], rows, None)
        historical = await inventory_cost.replay_issue_result(
            session, policy, rows, pg_book[0], issue_request(policy_id), verified_value_lines=verified,
            before_registration_token=cutoff)
        assert historical["book_quantity"] == "1.500000" and historical["book_value_byn"] == "0.00"
        with pytest.raises(AccountingError, match="Insufficient book quantity"):
            await inventory_cost.replay_issue_result(
                session, policy, rows, pg_book[0], issue_request(policy_id), verified_value_lines=verified)
        current = await inventory_cost.replay_issue_result(
            session, policy, rows, pg_book[0], issue_request(policy_id, "1"), verified_value_lines=verified)
        assert current["book_quantity"] == "1.000000" and current["book_value_byn"] == "0.00"
        session.add(Period(organization_id=pg_book[0], month="2026-11", closed=False))
        await session.flush()
        future = command(policy_id, output_id, line_id, source="inventory:zero:future", source_version=3,
                         posting_date="2026-11-01")
        await receipt_with_database_basis(session, pg_book[0], future)
        await session.commit()
        with pytest.raises(AccountingError, match="later movements"):
            await inventory_cost.replay_issue_result(
                session, policy, rows, pg_book[0], issue_request(policy_id, "1"), verified_value_lines=verified)
        assert len(await load_authenticated_zero_value_disposals(session, pg_book[0])) == 3
        session.add(Organization(id=2000, name="Other organization", unp="555000001"))
        await session.flush()
        assert await load_authenticated_zero_value_disposals(session, 2000) == ()
        with pytest.raises(AccountingError, match="Organization not found"):
            await load_authenticated_zero_value_disposals(session, pg_book[0] + 999)


async def test_loader_requires_0140_schema(pg_factory, pg_book):
    async with pg_factory() as session:
        with pytest.raises(AccountingError, match="migration 0140"):
            await load_authenticated_zero_value_disposals(session, pg_book[0])


async def test_loader_preserves_dated_command_after_commit(pg_factory, pg_book):
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await upgrade_0140(session)
        draft = parse_zero_value_command({
            **command(policy_id, output_id, line_id).model_dump(mode="json"),
            "command_version": 2, "document_date": "2026-10-29", "operation_date": "2026-10-30",
        })
        saved = await receipt_with_database_basis(session, pg_book[0], draft)
        snapshot = saved.command
        await session.commit()
    async with pg_factory() as session:
        loaded, = await load_authenticated_zero_value_disposals(session, pg_book[0])
        assert loaded.command.model_dump(mode="json") == snapshot
        assert loaded.command.document_date.isoformat() == "2026-10-29"
        assert loaded.command.operation_date.isoformat() == "2026-10-30"
        assert loaded.posting_date.isoformat() == "2026-10-31"
