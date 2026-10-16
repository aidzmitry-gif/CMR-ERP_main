"""One isolated reproduction of the accepted native transfer-confirm boundary."""
# ruff: noqa: F811 -- imported PostgreSQL fixtures are registered by pytest.
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.domain.models import Sku
from core.services.auth import CurrentUser
from modules.accounting import order_snapshot, service
from modules.accounting.gateway import AccountingService
from modules.accounting.models import (
    Account,
    Entry,
    Line,
    Organization,
    ProductionOutputTransferReceipt,
    SourceControl,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    confirm_output_transfer,
    prepare_output_transfer,
)
from modules.accounting.schemas import LineInput, PostingInput
from modules.production.accounting_ownership import ProductionOrderOwnership
from modules.production.models import ProductionOrder
from modules.production.output_documents import OutputCommand, confirm_output, prepare_output
from modules.wms.models import Location
from modules.wms.reservation_gateway import WmsReservationService
from tests.accounting.test_postgres import pg_book  # noqa: F401 -- pytest registration.
from tests.accounting.test_production_output_transfer_postgres import (
    SyntheticProduction,
    _seed_production_book,
    transfer_input,
)


@pytest_asyncio.fixture
async def pg_factory():
    """Reuse disposable-DB ownership and full-migration integration patterns."""
    raw = os.environ["ACCOUNTING_TEST_POSTGRES_URL"]
    parsed = make_url(raw)
    assert parsed.host == "127.0.0.1" and parsed.port == 55436 and parsed.database == "accounting_test"
    inspected = subprocess.run(["docker", "inspect", "--format",
        '{{.Id}} {{index .Config.Labels "codex.task"}} {{.State.Running}}', "crm-rel001-r362-pg"],
        capture_output=True, check=True, timeout=10).stdout.decode().split()
    assert len(inspected) == 3 and inspected[1:] == ["CRM-REL-001-R362", "true"]
    database = "acc_test_" + uuid4().hex
    admin = create_async_engine(raw, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
            await connection.execute(text(f'COMMENT ON DATABASE "{database}" IS \'crm-acc-fixture:{database}\''))
        target = parsed.set(database=database).render_as_string(hide_password=False)
        directory = Path(os.environ["R362_REPRO_EVIDENCE"]).parent
        with (directory / f"per-test-full-migration-{database}.private.log").open("xb") as log:
            subprocess.run([sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
                env=dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_DATABASE_URL=target),
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=150)
        engine = create_async_engine(parsed.set(database=database))
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "0193"
        marker = {"alembicVersion": version, "ownedContainerId": inspected[0], "containerLabel": inspected[1],
                  "database": database, "freshDatabase": True, "productionWrites": 0}
        with Path(os.environ["R362_SCHEMA_EVIDENCE"]).open("x", encoding="utf-8") as handle:
            json.dump(marker, handle, indent=2)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.connect() as connection:
                marker = await connection.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"), {"name": database})
                assert marker == "crm-acc-fixture:" + database
                await connection.execute(text(f'DROP DATABASE "{database}"'))
        await admin.dispose()


def safe_failure(error):
    result = []
    seen = set()
    while error is not None and id(error) not in seen and len(result) < 3:
        seen.add(id(error))
        frames = []
        trace = error.__traceback__
        while trace is not None and len(frames) < 16:
            frames.append({"fileLeaf": Path(trace.tb_frame.f_code.co_filename).name,
                           "operation": trace.tb_frame.f_code.co_name, "line": trace.tb_lineno})
            trace = trace.tb_next
        item = {"errorType": type(error).__name__, "safeFrames": frames}
        diagnostic = getattr(error, "diag", None)
        if diagnostic is not None:
            # Extract only static function identities/line numbers, never SQL or error text.
            context = getattr(diagnostic, "context", None)
            if type(context) is str:
                item["postgresFrames"] = [{"function": name, "line": int(line)} for name, line in
                    re.findall(r"PL/pgSQL function ([A-Za-z_][A-Za-z0-9_.]*)\([^\n]*?\) line ([0-9]+)", context)[:8]]
            code = getattr(diagnostic, "sqlstate", None)
            if type(code) is str and re.fullmatch(r"[A-Z0-9]{5}", code):
                item["sqlstate"] = code
        result.append(item)
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return result


async def test_owned_output_confirm_exact_snapshot_postgres(pg_factory, pg_book):
    """Real ledger, ownership, immutable receipt and source controls; synthetic physical facts."""
    evidence = Path(os.environ["R362_REPRO_EVIDENCE"])
    proof = {"baseline": "ae71eb115816f670086c095bddefd29501a85d08", "testsPlanned": 1,
             "productionWrites": 0, "humanLogin": False, "imageRebuilt": False,
             "fixture": "fresh marked full-head DB + pg_book + real output services + synthetic reconciliation",
             "previewPassed": False, "confirmAttempted": False, "confirmPassed": False}
    policy_id = await _seed_production_book(pg_factory, pg_book)
    documents = []
    async with pg_factory() as session:
        order = ProductionOrder(id=42, number="ORDER-42", product="Synthetic widget", qty=10,
                                stage="planned", created_at=datetime(2026, 10, 1))
        session.add(order)
        await session.flush()
        snapshot = {"order_id": 42, "number": order.number, "product": order.product,
                    "quantity": order.qty, "stage": order.stage,
                    "created_at": order.created_at.isoformat()}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        owner = ProductionOrderOwnership(order_id=42, organization_id=pg_book[0], snapshot=snapshot,
                                         digest=digest, evidence="Synthetic isolated reproduction", actor="tester")
        session.add(owner)
        await session.flush()
        dimensions = dict(order_snapshot.dimensions_from_ownership(owner), department="SHOP")
        session.add(Sku(code="SYN-WIDGET", title="Synthetic widget", unit="шт", is_active=True))
        place = Location(warehouse="Main", code="SYN-CELL", zone="SYN", title="Synthetic receiving place", is_active=True)
        session.add(place)
        await session.flush()
        for index, quantity in enumerate(("4.00", "6.00"), start=101):
            request = str(UUID(int=index))
            raw = OutputCommand(request_id=request, order_id=42, expected_order_digest=digest,
                                operation_date="2026-10-10", quantity=quantity, sku_code="SYN-WIDGET",
                                lot="LOT-1", warehouse="Main", location_id=place.id,
                                evidence="Synthetic isolated physical output")
            gateway, warehouse = AccountingService(), WmsReservationService()
            user = CurrentUser("tester", ["director"])
            document = await prepare_output(session, gateway, pg_book[0], user, raw, warehouse_gateway=warehouse)
            await confirm_output(session, gateway, pg_book[0], user, document.id, document.digest, warehouse_gateway=warehouse)
            documents.append({"document_id": document.id, "request_id": request,
                              "operation_date": "2026-10-10", "sku_code": "SYN-WIDGET",
                              "lot": "LOT-1", "quantity": quantity, "state": "accepted",
                              "accepted_quantity": quantity, "rejected_quantity": "0.00"})
        await session.commit()
    async with pg_factory() as session:
        posting = PostingInput(source="production:wip:42", source_version=1, operation="manual",
            document_date="2026-10-10", operation_date="2026-10-10", posting_date="2026-10-10",
            policy_id=policy_id, rule_version="synthetic-wip-v1", explanation="Synthetic owned WIP",
            lines=[LineInput(account="20", side="debit", amount="177.00", dimensions=dimensions),
                   LineInput(account="60", side="credit", amount="177.00", dimensions={})])
        await service.post(session, pg_book[0], posting, "tester")
        await session.commit()

    class PhysicalFacts(SyntheticProduction):
        async def cost_orders(self, _session, _organization_id, order_ids):
            return [{"order_id": order_ids[0], "product": "Synthetic widget", "quantity": "10.00"}]

        async def output_reconciliation(self, _session, _organization_id, _order_id, _warehouse):
            return {"planned_quantity": "10.00", "confirmed_quantity": "10.00",
                    "accepted_quantity": "10.00", "rejected_quantity": "0.00", "pending_quantity": "0.00",
                    "sku_code": "SYN-WIDGET", "unit": "шт", "lot": "LOT-1", "documents": documents}

    production = PhysicalFacts()
    command = transfer_input(policy_id).model_copy(update={"output_document_ids": [row["document_id"] for row in documents]})
    try:
        async with pg_factory() as session:
            preview = await prepare_output_transfer(session, pg_book[0], "2026-10", command, production, object())
            assert preview["candidate_transfer_byn"] == "177.00" and preview["final_cost_certified"] is False
            proof["previewPassed"] = True
            confirmed = ProductionOutputTransferConfirmInput.model_validate({**command.model_dump(mode="json"),
                         "basis_digest": preview["basis_digest"], "digest": preview["digest"]})
        async with pg_factory() as session:
            proof["confirmAttempted"] = True
            entry = await confirm_output_transfer(session, pg_book[0], "2026-10", confirmed, "tester",
                                                  production=production, warehouse_gateway=object())
            await session.commit()
            proof["confirmPassed"] = True
            receipt = await session.get(ProductionOutputTransferReceipt, entry.id)
            assert receipt.command == confirmed.model_dump(mode="json")
            controls = (await session.scalars(select(SourceControl).where(
                SourceControl.organization_id == pg_book[0]))).all()
            assert len(controls) == 2 and all(control.entry_id == entry.id for control in controls)
            assert await session.scalar(select(Entry.id).where(Entry.id == entry.id)) == entry.id
            # SQL must independently reject bad ownership evidence, even when a
            # caller bypasses the Python posting API. Keep each injected journal
            # balanced and roll it back with its failed validator savepoint.
            foreign = Organization(id=pg_book[0] + 1000, name="Synthetic other company", unp="999999998")
            session.add(foreign)
            await session.flush()
            other_order = ProductionOrder(id=84, number="ORDER-42", product="Synthetic widget", qty=10,
                                          stage="planned", created_at=datetime(2026, 10, 1))
            session.add(other_order)
            await session.flush()
            other_snapshot = dict(snapshot, order_id=84)
            other_digest = hashlib.sha256(json.dumps(other_snapshot, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode()).hexdigest()
            other_owner = ProductionOrderOwnership(order_id=84, organization_id=foreign.id,
                snapshot=other_snapshot, digest=other_digest, evidence="Synthetic foreign ownership", actor="tester")
            session.add(other_owner)
            await session.flush()
            variants = {
                "partial": {k: v for k, v in dimensions.items() if k != "order_digest"},
                "extra": dict(dimensions, unapproved="synthetic"),
                "tampered": dict(dimensions, order_digest="f" * 64),
                "foreign": dict(order_snapshot.dimensions_from_ownership(other_owner), department="SHOP"),
                "unregistered": dict(dimensions, order_id="999999"),
                "legacy_changed_trace": {"department": "SHOP", "order": "ORDER-42"},
            }
            accounts = {a.code: a for a in (await session.scalars(select(Account).where(
                Account.organization_id == pg_book[0], Account.code.in_(["20", "60"]))))}
            proof["sqlRegressionCases"] = []
            for name, variant in variants.items():
                expected = ("Shipment output WIP source basis is stale" if name == "legacy_changed_trace"
                            else "Malformed output revision WIP evidence")
                with pytest.raises(DBAPIError, match=expected):
                    async with session.begin_nested():
                        injected = posting.model_copy(update={"source": "synthetic:r362:" + name,
                            "lines": [LineInput(account="20", side="debit", amount="1.00", dimensions=variant),
                                      LineInput(account="60", side="credit", amount="1.00", dimensions={})]})
                        bad = Entry(**injected.model_dump(exclude={"lines"}), organization_id=pg_book[0],
                                    digest=service.digest(injected), actor="tester")
                        session.add(bad)
                        await session.flush()
                        for item in injected.lines:
                            account = accounts[item.account]
                            session.add(Line(**item.model_dump(exclude={"account"}), entry_id=bad.id,
                                account_id=account.id, account_code=account.code, account_title=account.title,
                                category=account.category, cash=account.cash))
                        await session.flush()
                        await session.execute(text("SELECT accounting.validate_shipment_output_layer(:org,:entry,:line,'43',:day,:anchor)"),
                            {"org": pg_book[0], "entry": entry.id,
                             "line": await session.scalar(select(Line.id).where(Line.entry_id == entry.id, Line.side == "debit")),
                             "day": command.posting_date, "anchor": bad.id + 1})
                proof["sqlRegressionCases"].append({"case": name, "status": "PASS"})
            migration = __import__("runpy").run_path("migrations/versions/0193_verified_owned_output_wip.py")
            from alembic.migration import MigrationContext
            from alembic.operations import Operations

            def refuse_downgrade(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migration["downgrade"]()

            with pytest.raises(DBAPIError, match="Cannot downgrade accepted owned-order output history"):
                async with session.begin_nested():
                    connection = await session.connection()
                    await connection.run_sync(refuse_downgrade)
            proof["downgradeWithOwnedHistoryRefused"] = True
    except BaseException as error:
        proof["status"] = "REPRODUCED_EXCEPTION"
        proof["exceptionChain"] = safe_failure(error)
        raise
    else:
        proof["status"] = "CONFIRM_SUCCEEDED"
    finally:
        evidence.write_text(json.dumps(proof, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
