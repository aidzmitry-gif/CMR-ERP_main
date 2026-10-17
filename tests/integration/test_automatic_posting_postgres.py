"""Synthetic automatic-account owners on migrated, test-owned PostgreSQL.

The existing frozen proposal remains unchanged; the shared fixture applies the
G26 policy migration. This wrapper adds bank mapping before seeding; it does not prove full CRM head,
real document admission, statutory approval, month closing or OIDC.
"""

import asyncio
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from core.domain.models import Counterparty
from core.runtime.app import create_app
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import (
    automatic_bank_import,
    automatic_shipments,
    bank_import,
    models,
)
from modules.accounting.gateway import AccountingService
from modules.finance.models import BankTransaction
from modules.procurement.models import Supplier
from modules.sales.reservation_source import SalesReservationSource
from modules.wms.invoice_reservations import ReserveInput, reserve
from modules.wms.models import StockMovement, WarehouseDirectory
from modules.wms.reservation_events import apply
from tests.accounting.conftest import book, db, posting  # noqa: F401
from tests.accounting.test_automatic_bank_import import confirmation, policy
from tests.accounting.test_automatic_shipments import setup as shipment_setup
from tests.accounting.test_bank_import import map_source
from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.reservation_source import invoice

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def automatic_pg(pg_factory, db, book):  # noqa: F811
    factory = pg_factory

    def policy_migration(connection):
        assert re.fullmatch(r"acc_test_[a-f0-9]{32}", connection.scalar(text("SELECT current_database()")))
        assert connection.scalar(text("SELECT count(*) FROM finance.bank_transaction")) == 0
        assert connection.scalar(text("SELECT count(*) FROM pg_constraint WHERE conrelid='finance.bank_transaction'::regclass "
                                      "AND conname IN ('bank_statement_direction','bank_statement_provenance')")) == 0
        assert connection.scalar(text("SELECT to_regclass('finance.bank_statement_source_identity')")) is None
        # The shared fixture uses current ORM columns with a pre-0135 guard.
        # Reproduce only the empty legacy column prestate; real0135 adds all guards.
        connection.execute(text("ALTER TABLE finance.bank_transaction DROP COLUMN direction, DROP COLUMN source_provider, "
                                "DROP COLUMN source_external_id, DROP COLUMN source_kind, DROP COLUMN source_reference"))
        with Operations.context(MigrationContext.configure(connection)):
            for name in ("0135_full_bank_statement_sources", "0137_bank_account_mapping"):
                path = Path(__file__).resolve().parents[2] / f"migrations/versions/{name}.py"
                spec = spec_from_file_location(name, path)
                migration = module_from_spec(spec)
                spec.loader.exec_module(migration)
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
        for table in ("accounting.account", "accounting.policy", "wms.warehouse_directory"):
            await session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))"
            ))
        await session.commit()

    app = create_app()
    app.state.core.services.db.session_factory = factory

    async def request_session():
        async with factory() as session:
            yield session

    async def identity(request: Request):
        return CurrentUser(request.headers.get("X-User", "tester"), ["director"])

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"X-User-Roles": "director"}) as api:
        api.test_app = app
        yield api, factory, book


async def ledger_state(factory):
    async with factory() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model)) for model in
                      (models.Entry, models.Line, models.BankImportReceipt, models.ShipmentAccountingReceipt)])


async def forbid_resolver(*_args, **_kwargs):
    raise AssertionError("Durable replay must not use current policy, source, mapping or cost")


async def bank_setup(api, session, selected_book, direction):
    configured = await api.post(f"/accounting/organizations/{selected_book[0]}/policies", json=policy())
    assert configured.status_code == 201, configured.text
    source = BankTransaction(ext_id="AUTO-BANK-1", occurred_on=date(2026, 9, 3), amount="123.45", currency="BYN",
        account_code="main", source_provider="synthetic-bank", direction=direction,
        source_external_id="AUTO-BANK-1", source_kind="file", source_reference="Synthetic complete bank statement",
        purpose="No account inferred from purpose")
    session.add(source)
    await session.commit()
    session.add(models.SourceBinding(organization_id=selected_book[0], source_type="finance_bank_transaction",
        source_id=source.id, ownership="own", evidence="Synthetic reviewed source ownership", actor="tester"))
    await session.commit()
    await map_source(session, selected_book[0], source)
    return source, dict(request_key=str(uuid4()), source_transaction_id=source.id,
        source_digest=bank_import._digest(bank_import.source_snapshot(source)), policy_id=configured.json()["id"],
        posting_date="2026-09-04", rule_key="supplier_payment" if direction == "payment" else "buyer_receipt",
        settlement_dimensions={"counterparty": "reviewed-party", "contract": "reviewed-contract"}, explanation="Reviewed operation")


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
    results = await asyncio.gather(*[
        api.post(path + "/auto-confirm", json=body) for _ in range(2)
    ], return_exceptions=True)
    assert not any(isinstance(result, BaseException) for result in results), results
    first, second = results
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
    services = api.test_app.state.core.services
    gateway, sales_source = services.wms_reservations, services.sales_source
    async with factory() as session:
        fake_receipt, _, options, _ = await shipment_setup(api, session, selected_book, posting)
        services.wms_reservations, services.sales_source = gateway, sales_source
        org = selected_book[0]
        session.add(WarehouseDirectory(organization_id=org, name="W", title="Synthetic WMS warehouse",
                                       is_active=True, created_by="tester", wms_enabled=True,
                                       prohibit_negative_stock=True))
        await invoice(session, 27, [{"sku_code": "SKU", "qty": "1"}, {"sku_code": "SKU", "qty": "2"}], org)
        session.add(StockMovement(organization_id=org, sku_code="SKU", warehouse="W", kind="in", qty="3", reason="receipt"))
        await session.commit()
        actor = await AccountingService().source_member(session, org, CurrentUser("tester", ["director"]))
        facts = await SalesReservationSource().invoice_reservation(session, 27)
        physical_lines = [{"line_no": 1, "warehouse": "W", "qty": "1"},
                          {"line_no": 2, "warehouse": "W", "qty": "2"}]
        await reserve(session, org, facts, ReserveInput(allocations=physical_lines,
                      journal_complete=True, evidence="Synthetic complete journal"), actor)
        await apply(session, 27, [("SKU", "W", Decimal("1")), ("SKU", "W", Decimal("2"))],
                    organization_id=org, release=False)
        await session.commit()
    wms_path = f"/wms/organizations/{org}/invoices/27/physical-shipments"
    identity = {"expected_version": facts["version"], "expected_content_sha256": facts["content_sha256"]}
    physical_preview = await api.post(wms_path + "/preview", json=identity)
    assert physical_preview.status_code == 200, physical_preview.text
    basis = physical_preview.json()
    created = await api.post(wms_path, json={**identity, "source_key": fake_receipt["source_key"],
        "expected_reservation_digest": basis["reservation_digest"],
        "expected_remaining_digest": basis["remaining_digest"],
        "expected_physical_digest": basis["physical_digest"], "operation_date": "2026-09-02",
        "evidence": "Synthetic actual release by authorized operator", "lines": physical_lines})
    assert created.status_code == 201, created.text
    receipt = created.json()
    options["expected_act_digest"] = receipt["digest"]
    for allocation in options["allocations"]:
        original_line = next(line for line in fake_receipt["snapshot"]["lines"]
                             if line["source"] == allocation["line_source"])
        line = next(line for line in receipt["snapshot"]["lines"]
                    if line["line_no"] == original_line["line_no"] and line["warehouse"] == original_line["warehouse"])
        allocation["line_source"] = line["source"]
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
    results = await asyncio.gather(*[
        api.post(path + "/auto-confirm", json=body) for _ in range(2)
    ], return_exceptions=True)
    assert not any(isinstance(result, BaseException) for result in results), results
    first, second = results
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
    async def unauthorized_source(*_args, **_kwargs):
        raise ValueError("Original source is no longer authorized")
    monkeypatch.setattr(gateway, "accounting_shipment_source", unauthorized_source)
    assert (await api.post(path + "/auto-confirm", json=body)).status_code == 409
    assert receipt == original_receipt
    assert await ledger_state(factory) == posted_state
