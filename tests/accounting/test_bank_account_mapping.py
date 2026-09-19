from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from modules.accounting import bank_account_mapping
from modules.accounting.models import Account, Audit, Organization, Period
from modules.accounting.schemas import BankAccountMappingInput
from tests.accounting.test_postgres import pg_book as pg_book
from tests.accounting.test_postgres import pg_factory as pg_factory


def payload(account_id, **changes):
    value = {
        "provider": "synthetic-bank",
        "external_account": "BY00SYNTHETIC0001",
        "currency": "BYN",
        "valid_from": "2026-09-01",
        "ledger_account_id": account_id,
        "dimensions": {},
        "evidence": "Synthetic documented mapping evidence",
    }
    value.update(changes)
    return value


async def account(db, org_id, code="51"):
    return await db.scalar(select(Account).where(Account.organization_id == org_id, Account.code == code))


async def test_mapping_registry_creates_lists_and_closes_with_audit(client, db, book):
    ledger = await account(db, book[0])
    created = await client.post(f"/accounting/organizations/{book[0]}/bank-account-mappings",
                                json=payload(ledger.id))
    assert created.status_code == 201, created.text
    mapping = created.json()
    assert mapping["version"] == 1
    assert mapping["valid_to"] is None
    assert len(mapping["digest"]) == 64

    listed = await client.get(f"/accounting/organizations/{book[0]}/bank-account-mappings")
    assert listed.status_code == 200
    assert [item["mapping_id"] for item in listed.json()] == [mapping["mapping_id"]]

    closed = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings/{mapping['mapping_id']}/close",
        json={"valid_to": "2026-10-01", "evidence": "Synthetic close decision evidence"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["valid_to"] == "2026-10-01"
    assert closed.json()["evidence"] == "Synthetic documented mapping evidence"
    audit = (await db.scalars(select(Audit).where(Audit.action == "bank_account_mapping_closed"))).one()
    assert audit.detail["after"]["close_evidence"] == "Synthetic close decision evidence"
    repeated = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings/{mapping['mapping_id']}/close",
        json={"valid_to": "2026-10-02", "evidence": "Synthetic duplicate close evidence"},
    )
    assert repeated.status_code == 409


async def test_mapping_rejects_cross_organization_overlap_and_invalid_foreign_account(client, db, book):
    ledger = await account(db, book[0])
    first = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings",
        json=payload(ledger.id, valid_from="2026-10-01"),
    )
    assert first.status_code == 201

    other = Organization(name="Synthetic other company", unp="888888888")
    db.add(other)
    await db.flush()
    other_account = Account(organization_id=other.id, code="51", title="Other cash", category="asset",
                            valid_from=date(2026, 1, 1), required_dimensions=[], currency_tracking=True,
                            quantity_tracking=False, cash=True, normative_ref="synthetic")
    db.add(other_account)
    await db.flush()
    with pytest.raises(HTTPException, match="already has an effective mapping"):
        await bank_account_mapping.create(
            db, other.id, BankAccountMappingInput.model_validate(payload(other_account.id)), "tester",
        )

    foreign_ledger = Account(organization_id=book[0], code="52", title="Foreign cash without tracking",
                             category="asset", valid_from=date(2026, 1, 1), required_dimensions=[],
                             currency_tracking=False, quantity_tracking=False, cash=True,
                             normative_ref="synthetic")
    db.add(foreign_ledger)
    await db.commit()
    foreign = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings",
        json=payload(foreign_ledger.id, external_account="USD-ACCOUNT", currency="USD"),
    )
    assert foreign.status_code == 422
    assert "currency tracking" in foreign.json()["detail"]


async def test_mapping_resolve_rejects_stale_account_version(client, db, book):
    ledger = await account(db, book[0])
    created = await client.post(f"/accounting/organizations/{book[0]}/bank-account-mappings", json=payload(ledger.id))
    assert created.status_code == 201
    db.add(Account(organization_id=book[0], code="51", title="New cash version", category="asset",
                   valid_from=date(2026, 10, 1), required_dimensions=[], currency_tracking=True,
                   quantity_tracking=False, cash=True, normative_ref="synthetic successor"))
    await db.commit()
    with pytest.raises(HTTPException, match="stale"):
        await bank_account_mapping.resolve(
            db, book[0], provider="synthetic-bank", external_account="BY00SYNTHETIC0001",
            currency="BYN", on=date(2026, 10, 2),
        )


async def test_mapping_successor_closes_predecessor_and_respects_closed_periods(client, db, book):
    original = await account(db, book[0])
    first = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings",
        json=payload(original.id),
    )
    assert first.status_code == 201, first.text
    replacement = Account(organization_id=book[0], code="51", title="Bank cash successor",
                          category="asset", valid_from=date(2026, 10, 1),
                          required_dimensions=["department"], currency_tracking=True,
                          quantity_tracking=False, cash=True, normative_ref="synthetic successor")
    db.add(replacement)
    await db.commit()
    successor = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings",
        json=payload(replacement.id, valid_from="2026-10-01", dimensions={"department": "bank"},
                     evidence="Synthetic successor mapping evidence"),
    )
    assert successor.status_code == 201, successor.text
    assert successor.json()["version"] == 2
    before_boundary = await client.get(
        f"/accounting/organizations/{book[0]}/bank-account-mappings", params={"at": "2026-09-30"},
    )
    at_boundary = await client.get(
        f"/accounting/organizations/{book[0]}/bank-account-mappings", params={"at": "2026-10-01"},
    )
    assert [row["mapping_id"] for row in before_boundary.json()] == [first.json()["mapping_id"]]
    assert [row["mapping_id"] for row in at_boundary.json()] == [successor.json()["mapping_id"]]
    history = await client.get(
        f"/accounting/organizations/{book[0]}/bank-account-mappings", params={"include_closed": "true"},
    )
    old = next(row for row in history.json() if row["mapping_id"] == first.json()["mapping_id"])
    assert old["valid_to"] == "2026-10-01"
    assert old["ledger_account_id"] == original.id
    assert old["dimensions"] == {}

    db.add(Period(organization_id=book[0], month="2026-11", generation=0, closed=True))
    await db.commit()
    blocked_create = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings",
        json=payload(replacement.id, external_account="CLOSED-PERIOD", valid_from="2026-11-01",
                     dimensions={"department": "bank"}),
    )
    blocked_close = await client.post(
        f"/accounting/organizations/{book[0]}/bank-account-mappings/{successor.json()['mapping_id']}/close",
        json={"valid_to": "2026-11-01", "evidence": "Synthetic closed-period close evidence"},
    )
    assert blocked_create.status_code == 409
    assert blocked_close.status_code == 409


def test_migration_has_postgres_overlap_and_immutability_guards():
    migration = Path("migrations/versions/0137_bank_account_mapping.py").read_text(encoding="utf-8")
    assert 'down_revision = "0136"' in migration
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in migration
    assert "EXCLUDE USING gist" in migration
    assert "guard_bank_account_mapping_update" in migration
    assert "NEW.id IS DISTINCT FROM OLD.id" in migration
    assert "guard_bank_account_mapping_delete" in migration


@pytest.mark.integration
async def test_postgres_mapping_history_and_global_overlap_guards(pg_factory, pg_book):
    """Exercise migration guards directly on an isolated PostgreSQL database."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with pg_factory() as session:
        async with session.begin():
            def upgrade(connection):
                migration = Path("migrations/versions/0137_bank_account_mapping.py")
                namespace = {}
                exec(migration.read_text(encoding="utf-8"), namespace)
                with Operations.context(MigrationContext.configure(connection)):
                    namespace["upgrade"]()

            connection = await session.connection()
            await connection.run_sync(upgrade)
            account_id = await session.scalar(text(
                "SELECT id FROM accounting.account WHERE organization_id=:org AND code='51'"
            ), {"org": pg_book[0]})
            mapping_id = await session.scalar(text("""
                INSERT INTO accounting.bank_account_mapping
                  (organization_id, provider, external_account, currency, valid_from, version,
                   ledger_account_id, dimensions, evidence, actor)
                VALUES (:org, 'synthetic-bank', 'PG-MUTATION', 'BYN', '2026-09-01', 1,
                        :account, '{}'::jsonb, 'Synthetic PostgreSQL guard evidence', 'tester')
                RETURNING id
            """), {"org": pg_book[0], "account": account_id})

    async with pg_factory() as session:
        other_org = await session.scalar(text("""
            INSERT INTO accounting.organization (id, name, unp, generation)
            VALUES (999999, 'Synthetic overlap organization', '777777777', 0)
            RETURNING id
        """))
        with pytest.raises(DBAPIError):
            await session.execute(text("""
                INSERT INTO accounting.bank_account_mapping
                  (organization_id, provider, external_account, currency, valid_from, version,
                   ledger_account_id, dimensions, evidence, actor)
                VALUES (:org, 'synthetic-bank', 'PG-MUTATION', 'BYN', '2026-09-15', 1,
                        :account, '{}'::jsonb, 'Synthetic overlap guard evidence', 'tester')
            """), {"org": other_org, "account": account_id})
        await session.rollback()

    for statement in (
        "UPDATE accounting.bank_account_mapping SET id=id + 1000 WHERE id=:id",
        "DELETE FROM accounting.bank_account_mapping WHERE id=:id",
    ):
        async with pg_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(text(statement), {"id": mapping_id})
            await session.rollback()
