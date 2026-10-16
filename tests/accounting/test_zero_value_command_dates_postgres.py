"""PostgreSQL evidence for migration 0142 command-date validation."""
# ruff: noqa: F811 -- imported fixtures are used by pytest parameter lookup.
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting.zero_value_disposals import (
    canonical_json,
    load_authenticated_zero_value_disposals,
    parse_zero_value_command,
    preview_standalone_zero_value_issue_basis,
    register_standalone_zero_value_issue,
)
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401
from tests.accounting.test_zero_value_disposals_postgres import command, zeroed_output

pytestmark = pytest.mark.integration


async def run_migration(session, revision, action):
    def run(connection):
        migration = runpy.run_path(f"migrations/versions/{revision}")
        with Operations.context(MigrationContext.configure(connection)):
            migration[action]()

    await (await session.connection()).run_sync(run)


async def save_with_basis(session, organization_id, draft):
    basis = await preview_standalone_zero_value_issue_basis(session, organization_id, draft)
    return await register_standalone_zero_value_issue(
        session, organization_id, "tester", draft.model_copy(update={"basis_digest": basis})
    )


async def insert_raw(session, organization_id, policy_id, raw):
    raw_basis = await session.scalar(
        text("SELECT accounting.zero_value_disposal_basis(:org, CAST(:command AS jsonb), 2147483647)"),
        {"org": organization_id, "command": canonical_json(raw)},
    )
    raw["basis_digest"] = raw_basis
    digest = await session.scalar(
        text("SELECT accounting.financial_sha(CAST(:snapshot AS jsonb))"),
        {"snapshot": canonical_json({"organization_id": organization_id, "actor": "tester", "command": raw})},
    )
    await session.execute(text("""
        INSERT INTO accounting.inventory_zero_value_disposal_receipt
            (organization_id, source, source_version, operation, entry_id, posting_date, policy_id,
             command, basis_digest, digest, actor)
        VALUES (:organization_id, :source, :source_version, :operation, NULL, :posting_date, :policy_id,
                CAST(:command AS json), :basis_digest, :digest, 'tester')
    """), {
        "organization_id": organization_id, "source": raw["source"],
        "source_version": raw["source_version"], "operation": raw["operation"],
        "posting_date": raw["posting_date"], "policy_id": policy_id,
        "command": canonical_json(raw), "basis_digest": raw_basis, "digest": digest,
    })


def dated_command(policy_id, output_id, line_id, **changes):
    body = command(policy_id, output_id, line_id).model_dump(mode="json")
    body.update({"command_version": 2, "document_date": "2026-10-29", "operation_date": "2026-10-30"})
    body.update(changes)
    return parse_zero_value_command(body)


async def test_0142_accepts_dated_v2_and_legacy_v1_and_rejects_raw_variants(pg_factory, pg_book):
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await run_migration(session, "0141_zero_value_output_cost.py", "upgrade")
        await run_migration(session, "0142_zero_value_command_dates.py", "upgrade")
        await session.commit()
    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        v2 = dated_command(policy_id, output_id, line_id)
        await save_with_basis(session, pg_book[0], v2)
        legacy = command(policy_id, output_id, line_id, source="inventory:zero:legacy", source_version=2)
        await save_with_basis(session, pg_book[0], legacy)
        await session.commit()

    async with pg_factory() as session:
        loaded = await load_authenticated_zero_value_disposals(session, pg_book[0])
        assert [getattr(item.command, "command_version", None) for item in loaded] == [2, None]
        assert loaded[0].command.document_date.isoformat() == "2026-10-29"
        assert loaded[0].command.operation_date.isoformat() == "2026-10-30"

        cases = [
            ("missing-date", {"document_date": None}, "date is invalid"),
            ("bad-date", {"operation_date": "2026-02-30"}, "date is invalid"),
            ("zero-year", {"document_date": "0000-01-01"}, "date is invalid"),
            ("infinity-date", {"operation_date": "infinity"}, "date is invalid"),
            ("unknown-version", {"command_version": 3}, "version must be integer 2"),
            ("decimal-version", {"command_version": 2.0}, "version must be integer 2"),
            ("null-version", {"command_version": None}, "version must be integer 2"),
            ("boolean-version", {"command_version": True}, "version must be integer 2"),
            ("string-version", {"command_version": "2"}, "version must be integer 2"),
            ("legacy-date", {"command_version": None, "document_date": "2026-10-29"},
             "Legacy zero-value command"),
        ]
        for index, (suffix, changes, message) in enumerate(cases, start=10):
            raw = dated_command(policy_id, output_id, line_id).model_dump(mode="json")
            raw.update(changes)
            if suffix == "legacy-date":
                raw.pop("command_version", None)
            if raw.get("document_date") is None:
                raw.pop("document_date", None)
            raw["source"] = f"inventory:zero:raw-{suffix}"
            raw["source_version"] = index
            with pytest.raises(DBAPIError, match=message):
                async with session.begin_nested():
                    await insert_raw(session, pg_book[0], policy_id, raw)

        with pytest.raises(DBAPIError, match="Cannot downgrade 0142"):
            async with session.begin_nested():
                await run_migration(session, "0142_zero_value_command_dates.py", "downgrade")


async def test_0142_rejects_invalid_existing_v2_and_empty_roundtrip(pg_factory, pg_book):
    async with pg_factory() as session:
        await run_migration(session, "0140_zero_value_disposals.py", "upgrade")
        await run_migration(session, "0141_zero_value_output_cost.py", "upgrade")
        await run_migration(session, "0142_zero_value_command_dates.py", "upgrade")
        await run_migration(session, "0142_zero_value_command_dates.py", "downgrade")
        await run_migration(session, "0142_zero_value_command_dates.py", "upgrade")
        assert await session.scalar(text("SELECT to_regprocedure('accounting.validate_zero_value_disposal_command(jsonb)')"))
        await session.commit()

    policy_id, output_id, line_id = await zeroed_output(pg_factory, pg_book)
    async with pg_factory() as session:
        await run_migration(session, "0142_zero_value_command_dates.py", "downgrade")
        raw = dated_command(policy_id, output_id, line_id, source="inventory:zero:historic-invalid", source_version=9)
        raw = raw.model_dump(mode="json")
        raw["operation_date"] = "2026-02-30"
        await insert_raw(session, pg_book[0], policy_id, raw)
        with pytest.raises(DBAPIError, match="date is invalid"):
            async with session.begin_nested():
                await run_migration(session, "0142_zero_value_command_dates.py", "upgrade")
