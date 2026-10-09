"""Synthetic automatic-account owners on migrated, test-owned PostgreSQL.

The existing frozen proposal fixture remains unchanged. This wrapper applies
the actual G26 policy migration before seeding; it does not prove full CRM head,
real document admission, statutory approval, month closing or OIDC.
"""

import asyncio
from copy import deepcopy
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import (
    automatic_bank_import,
    automatic_shipments,
    bank_import,
    models,
    routes,
)
from modules.accounting.gateway import AccountingService
from modules.finance.models import BankTransaction
from modules.procurement.models import Supplier
from modules.wms.models import WarehouseDirectory
from tests.accounting.conftest import book, db, posting  # noqa: F401
from tests.accounting.test_automatic_bank_import import confirmation
from tests.accounting.test_automatic_bank_import import setup as bank_setup
from tests.accounting.test_automatic_shipments import setup as shipment_setup
from tests.accounting.test_postgres import pg_factory  # noqa: F401

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def automatic_pg(pg_factory, db, book):  # noqa: F811
    factory = pg_factory

    def policy_migration(connection):
        path = Path(__file__).resolve().parents[2] / "migrations/versions/crm_rel_001_auto_posting_01.py"
        spec = spec_from_file_location("automatic_policy_migration", path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    async with factory() as session:
        connection = await session.connection()
        await connection.run_sync(policy_migration)
        for model in (models.Organization, models.AccessGrant, models.Account, models.Policy,
                      Counterparty, Supplier, WarehouseDirectory):
            for row in (await db.scalars(select(model))).all():
                session.add(model(**{c.key: getattr(row, c.key) for c in model.__table__.columns}))
            await session.flush()
        # Explicit copied fixture IDs do not advance PostgreSQL sequences.
        for table in ("accounting.account", "accounting.policy"):
            await session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))"
            ))
        await session.commit()

    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.state.core = SimpleNamespace(services=SimpleNamespace(
        event_bus=None, accounting=AccountingService(),
    ))

    async def request_session():
        async with factory() as session:
            yield session

    async def identity(request: Request):
        return CurrentUser(request.headers.get("X-User", "tester"), ["director"])

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        api.test_app = app
        yield api, factory, book


async def ledger_state(factory):
    async with factory() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model)) for model in
                      (models.Entry, models.Line, models.BankImportReceipt, models.ShipmentAccountingReceipt)])


async def forbid_resolver(*_args, **_kwargs):
    raise AssertionError("Durable replay must not use current policy, source, mapping or cost")


@pytest.mark.parametrize("direction,pairs", [
    ("receipt", [("51", "debit"), ("62", "credit")]),
    ("payment", [("60", "debit"), ("51", "credit")]),
])
async def test_pg_automatic_bank_concurrent_durable_replay_and_holds(automatic_pg, monkeypatch, direction, pairs):
    api, factory, selected_book = automatic_pg
    async with factory() as session:
        source, command = await bank_setup(api, session, selected_book, direction)
        source_id = source.id
        source_before = bank_import.source_snapshot(source)
    path = f"/accounting/organizations/{selected_book[0]}/bank-import"
    baseline = await ledger_state(factory)
    for change in ({"source_digest": "0" * 64}, {"policy_id": 999}, {"rule_key": "missing"},
                   {"rule_key": "buyer_receipt" if direction == "payment" else "supplier_payment"}):
        held = await api.post(path + "/auto-preview", json={**command, **change})
        assert held.status_code == 422, held.text
        assert await ledger_state(factory) == baseline
    preview = await api.post(path + "/auto-preview", json=command)
    assert preview.status_code == 200, preview.text
    assert sorted((row["account"], row["side"]) for row in preview.json()["lines"]) == sorted(pairs)
    assert all(row["amount"] == "123.45" for row in preview.json()["lines"])
    body = confirmation(preview.json(), command["rule_key"])
    changed = deepcopy(body)
    changed["command"]["bank_dimensions"] = {"bank_account": "forged"}
    assert (await api.post(path + "/auto-confirm", json=changed)).status_code == 409
    assert await ledger_state(factory) == baseline
    first, second = await asyncio.gather(*[
        api.post(path + "/auto-confirm", json=body) for _ in range(2)
    ])
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    entry = first.json()["entry_id"]
    assert second.json()["entry_id"] == entry
    async with factory() as session:
        lines = (await session.scalars(select(models.Line).where(models.Line.entry_id == entry))).all()
        assert sorted((line.account_code, line.side) for line in lines) == sorted(pairs)
        assert all(line.amount == Decimal("123.45") and line.currency == "BYN" for line in lines)
        settlement = next(line for line in lines if line.account_code != "51")
        assert settlement.dimensions == {"counterparty": "reviewed-party", "contract": "reviewed-contract"}
        assert next(line for line in lines if line.account_code == "51").dimensions == {
            "bank_transaction_id": str(source_id), "bank_statement": "AUTO-BANK-1",
        }
        assert bank_import.source_snapshot(await session.get(BankTransaction, source_id)) == source_before
    assert await ledger_state(factory) == (1, 2, 1, 0)
    monkeypatch.setattr(automatic_bank_import, "resolve_command", forbid_resolver)
    replay = await api.post(path + "/auto-confirm", json=body)
    assert replay.status_code == 201 and replay.json()["entry_id"] == entry
    assert (await api.post(path + "/auto-confirm", json=body, headers={"X-User": "outsider"})).status_code == 403
    changed = deepcopy(body)
    changed["command"]["settlement_dimensions"] = {"counterparty": "other"}
    assert (await api.post(path + "/auto-confirm", json=changed)).status_code == 409
    async with factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE accounting.bank_import_receipt SET amount=999 WHERE entry_id=:id"), {"id": entry})
            await session.commit()
        await session.rollback()
    assert await ledger_state(factory) == (1, 2, 1, 0)


async def test_pg_automatic_shipment_concurrent_exact_cost_and_authorized_saved_replay(automatic_pg, posting, monkeypatch):  # noqa: F811
    api, factory, selected_book = automatic_pg
    async with factory() as session:
        receipt, _, options, gateway = await shipment_setup(api, session, selected_book, posting)
    original_receipt = deepcopy(receipt)
    path = f"/accounting/organizations/{selected_book[0]}/shipments/{receipt['source_key']}"
    baseline = await ledger_state(factory)
    assert baseline == (1, 2, 0, 0)
    held = await api.post(path + "/auto-preview", json={**options, "policy_id": 999})
    assert held.status_code == 409, held.text
    preview = await api.post(path + "/auto-preview", json=options)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert (plan["net_byn"], plan["vat_byn"], plan["gross_byn"]) == ("40.00", "8.00", "48.00")
    assert [row["cost_byn"] for row in plan["mapping"]] == ["3.33", "6.67"]
    body = {**plan["resolved_command"], "expected_basis_digest": plan["basis_digest"]}
    changed = deepcopy(body)
    changed["commercial_lines"][0]["net_amount"] = "999.00"
    assert (await api.post(path + "/auto-confirm", json=changed)).status_code == 409
    assert await ledger_state(factory) == baseline
    first, second = await asyncio.gather(*[
        api.post(path + "/auto-confirm", json=body) for _ in range(2)
    ])
    assert first.status_code == second.status_code == 201, (first.text, second.text)
    assert first.json() == second.json()
    entry = first.json()["anchor_entry_id"]
    expected = {("62", "debit"): "48", ("90.1", "credit"): "48", ("90.2", "debit"): "8",
                ("68.2", "credit"): "8", ("90.4", "debit"): "10", ("41.2", "credit"): "10"}
    async with factory() as session:
        lines = (await session.scalars(select(models.Line).where(models.Line.entry_id == entry))).all()
        assert {(line.account_code, line.side) for line in lines} == set(expected)
        for key, amount in expected.items():
            assert sum((line.amount for line in lines if (line.account_code, line.side) == key), Decimal(0)) == Decimal(amount)
        assert sum((line.quantity for line in lines if line.account_code == "41.2"), Decimal(0)) == 3
        assert sum((line.amount * (1 if line.side == "debit" else -1) for line in lines), Decimal(0)) == 0
        credits = [line for line in lines if line.account_code == "41.2"]
        assert all(line.dimensions == {"warehouse": "W", "sku": "SKU", "lot": "lot1"} for line in credits)
        assert sorted(line.amount for line in credits) == [Decimal("3.33"), Decimal("6.67")]
        assert sorted(((line.dimensions, line.amount) for line in lines if line.account_code == "90.4"),
                      key=lambda row: row[0]["department"]) == [
            ({"department": "1"}, Decimal("3.33")), ({"department": "2"}, Decimal("6.67")),
        ]
        buyer = {"counterparty_id": "1", "counterparty": "supplier1", "counterparty_unp": "190000001",
                 "counterparty_revision": "1", "contract": "contract", "settlement_document": "sales:document:27"}
        assert all(line.dimensions == buyer for line in lines if line.account_code == "62")
        assert all(line.dimensions == {"vat_rate": "20", "vat_basis": "Synthetic accountant-approved basis"}
                   for line in lines if line.account_code in {"90.1", "90.2", "68.2"})
        control = await session.scalar(select(models.SourceControl).where(models.SourceControl.source == plan["source"]))
        assert control.entry_id == entry
    posted_state = await ledger_state(factory)
    assert posted_state == (2, 14, 0, 1)
    monkeypatch.setattr(automatic_shipments, "resolve_command", forbid_resolver)
    replay = await api.post(path + "/auto-confirm", json=body)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert (await api.post(path + "/auto-confirm", json=body, headers={"X-User": "outsider"})).status_code == 403
    assert (await api.post(path + "/auto-confirm", json=changed)).status_code == 409
    gateway.accounting_shipment_source.side_effect = ValueError("Original source is no longer authorized")
    assert (await api.post(path + "/auto-confirm", json=body)).status_code == 409
    assert receipt == original_receipt
    assert await ledger_state(factory) == posted_state
