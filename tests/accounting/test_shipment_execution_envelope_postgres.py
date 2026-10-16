"""Full-head isolated ASGI/PG reproduction; never a Fresh/OIDC release receipt."""
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import get_settings
from core.domain.reference import Currency, Unit
from core.runtime.app import create_app
from core.runtime.deps import get_session
from modules.accounting import models, shipment_commands
from modules.wms.models import StockMovement, WarehouseDirectory

pytestmark = pytest.mark.integration
BASELINE = "3f1344a1f587aa4a6f1660bc0002505d55d8ae63"
DRIVER_SHA = "54c6ac4fe6e660540565b55fa780fdc7dd145326a277ee05fcc5f6f92d5cf867"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def persist_test(path, value, *, new=True):
    wrapped = {"execution": "ISOLATED_TEST_ONLY", "releaseAcceptance": False,
               "ordinaryOIDC": False, "linuxRuntimeAcceptance": False, "observation": value}
    with path.open("x" if new else "w", encoding="utf-8") as out:
        json.dump(wrapped, out, ensure_ascii=False, indent=2)


def pg_error(error):
    pending, seen = [error], set()
    while pending and len(seen) < 24:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        diagnostic = getattr(item, "diag", None)
        if diagnostic is not None:
            return {"errorType": type(item).__name__, "sqlstate": getattr(diagnostic, "sqlstate", None),
                    "expectedGuard": getattr(diagnostic, "message_primary", None)
                    == "Shipment receipt requires its exact physical act"}
        pending.extend([getattr(item, "__cause__", None), getattr(item, "__context__", None),
                        getattr(item, "orig", None), *getattr(item, "exceptions", ())])
    return {"errorType": type(error).__name__, "sqlstate": None, "expectedGuard": False}


@pytest_asyncio.fixture
async def full_pg_case(monkeypatch):
    instance_path = os.getenv("SHIPMENT_ENVELOPE_INSTANCE")
    if not instance_path:
        pytest.skip("Requires the reviewed owned PostgreSQL controller")
    instance = json.loads(Path(instance_path).read_bytes())
    control = load("owned_envelope_test_control", Path(os.environ["SHIPMENT_ENVELOPE_CONTROL"]))
    proof = await asyncio.to_thread(control.rpc, instance, "verify")
    assert proof["owner"] == instance["owner"] and proof["status"] == "OWNED_PG_READY"
    master = os.environ["SHIPMENT_ENVELOPE_MASTER_URL"]
    parsed = make_url(master)
    assert parsed.host == "127.0.0.1" and parsed.port == 55436 and parsed.database == "accounting_test"
    database = "acc_test_" + uuid4().hex
    marker = "crm-acc-fixture:" + instance["owner"] + ":" + database
    target = parsed.set(database=database).render_as_string(hide_password=False)
    folder = Path(instance["folder"]) / database
    folder.mkdir()
    admin = create_async_engine(master, isolation_level="AUTOCOMMIT")
    engine, app, created = None, None, False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
            await connection.execute(text(f'COMMENT ON DATABASE "{database}" IS \'{marker}\''))
        with (folder / "migration.private.log").open("xb") as log:
            result = await asyncio.to_thread(
                subprocess.run, [sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
                env=dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_AUTH_MODE="dev", AIOS_DATABASE_URL=target),
                stdout=log, stderr=subprocess.STDOUT, timeout=150,
            )
        assert result.returncode == 0, "Full-head migration failed; private fixture log retained"
        monkeypatch.setenv("AIOS_DATABASE_URL", target)
        monkeypatch.setenv("AIOS_ENVIRONMENT", "dev")
        monkeypatch.setenv("AIOS_AUTH_MODE", "dev")
        get_settings.cache_clear()
        assert get_settings().database_url == target and get_settings().auth_mode == "dev"
        engine = create_async_engine(target)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == database
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0194"
        source = control.SOURCE
        raw = (source / "native_business.py").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == DRIVER_SHA
        driver = load("isolated_unchanged_native_business", source / "native_business.py")
        profile = deepcopy(json.loads((source / "initialization-candidate-r204.private.json").read_bytes())["candidate"])
        driver.approved_profile(profile["accounts"])
        app = create_app()  # No lifespan/background workers or external integration startup.
        assert app.state.core.services.db.url == target
        app.state.core.services.db.session_factory = factory

        async def sessions():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = sessions
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://isolated-test",
                               headers={"X-User": "fixture-director", "X-User-Roles": "director"}) as api:
            response = await api.post("/accounting/organizations", json={"name": "Isolated envelope fixture", "unp": "999999961"})
            assert response.status_code == 201
            org = response.json()["id"]
            async with factory() as session:
                for row in profile["accounts"]:
                    session.add(models.Account(organization_id=org, **dict(row, valid_from=date(2026, 7, 1))))
                for row in profile["warehouses"]:
                    session.add(WarehouseDirectory(organization_id=org, created_by="fixture-director", **row))
                for model, rows in ((Unit, profile["units"]), (Currency, profile["currencies"])):
                    for row in rows:
                        if await session.scalar(select(model.id).where(model.code == row["code"])) is None:
                            session.add(model(**row))
                await session.commit()
            persist_test(folder / "fixture.json", {"database": database, "marker": marker, "head": "0194",
                         "ownedPG": proof["containerId"], "testAuthentication": "LOCAL_ASGI_DEV_HEADERS",
                         "backgroundWritersStarted": False})
            yield SimpleNamespace(factory=factory, api=api, org=org, profile=profile, driver=driver,
                                  database=database, target=target, folder=folder, marker=marker)
    finally:
        if app is not None and app.state.core.services.db.engine is not None:
            await app.state.core.services.db.engine.dispose()
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.connect() as connection:
                current = await connection.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=:name"), {"name": database})
                assert current == marker
                await connection.execute(text(f'DROP DATABASE "{database}"'))
            persist_test(folder / "database-cleanup.json", {"database": database, "markerMatched": True, "dropped": True})
        await admin.dispose()
        get_settings.cache_clear()


class LocalNativeContext:
    def __init__(self, case, owner, abort):
        self.case, self.abort = case, abort
        self.root = case.folder
        self.inputs = {"initialization": case.profile}
        self.m = {"owner": owner, "scope": "isolated_test", "auth": {"subject": "fixture-director"}}
        self.state = {"owner": owner, "resources": {"app": "LOCAL_ASGI_PROCESS:" + str(os.getpid())},
                      "identity": {"database": case.database, "fixtureMarker": case.marker},
                      "initialization": {"organizationId": case.org}}

    def save(self, **values):
        self.state.update(values)

    def effect(self, _name, operation):
        return operation()

    def native(self, program, payload=None):
        assert not self.abort.is_set(), "ISOLATED_TEST_ABORTED"
        driver = self.case.driver
        assert program in {driver.REFERENCE, driver.PHYSICAL, driver.RELAY,
                           driver.RESERVATION_SOURCE, driver.DOCUMENT_MODE_READBACK}
        prefix = "import asyncio,sys\nif sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())\n"
        result = subprocess.run([sys.executable, "-B", "-c", prefix + program],
                                input=json.dumps(payload).encode(), capture_output=True, timeout=40,
                                env=dict(os.environ, AIOS_ENVIRONMENT="dev", AIOS_AUTH_MODE="dev",
                                         AIOS_DATABASE_URL=self.case.target))
        assert len(result.stdout) <= 262144
        if result.returncode:
            (self.root / ("native-" + hashlib.sha256(program.encode()).hexdigest()[:12] + ".private.log")).write_bytes(result.stderr)
        assert result.returncode == 0, "Isolated native helper failed; private log retained"
        return json.loads(result.stdout)


@pytest.mark.parametrize("case_name", ["baseline", "full_flow", "unknown_top", "nested_tamper"])
async def test_full_head_shipment_execution_envelope(full_pg_case, monkeypatch, case_name):
    case = full_pg_case
    original = shipment_commands.confirm
    if case_name == "baseline":
        raw = subprocess.check_output(["git", "show", BASELINE + ":modules/accounting/shipment_commands.py"])
        namespace = {"__name__": "isolated_baseline_shipment", "__file__": shipment_commands.__file__}
        exec(compile(raw, "isolated-baseline-shipment", "exec"), namespace)
        selected = namespace["confirm"]
    else:
        selected = original
    before = {}

    async def observed_confirm(session, org_id, receipt, *args, **kwargs):
        before.update(entries=await session.scalar(select(func.count()).select_from(models.Entry)),
                      receipts=await session.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt)),
                      stock=await session.scalar(select(func.count()).select_from(StockMovement)),
                      source=f"wms:physical-shipment:{org_id}:{receipt['source_key']}")
        receipt = deepcopy(receipt)
        if case_name == "unknown_top":
            receipt["future_evidence"] = "must remain under SQL validation"
        elif case_name == "nested_tamper":
            receipt["snapshot"]["evidence"] = "changed after authenticated gateway"
        return await selected(session, org_id, receipt, *args, **kwargs)

    monkeypatch.setattr(shipment_commands, "confirm", observed_confirm)
    loop, abort, active = asyncio.get_running_loop(), threading.Event(), set()
    driver = case.driver

    class Api:
        observations = []

        def request(self, method, path, body=None, *, statuses=(200,), principal=False):
            assert not abort.is_set()

            async def dispatch():
                task = asyncio.current_task()
                active.add(task)
                try:
                    headers = {"X-Expected-Principal": "fixture-director"} if principal else None
                    response = await case.api.request(method, path, json=body, headers=headers)
                    if response.status_code not in statuses:
                        persist_test(case.folder / "unexpected-http.private.json", {
                            "method": method, "path": path, "status": response.status_code,
                            "response": response.json(),
                        }, new=False)
                    return response
                finally:
                    active.discard(task)

            future = asyncio.run_coroutine_threadsafe(dispatch(), loop)
            try:
                response = future.result(timeout=12)
            except BaseException:
                future.cancel()
                raise
            assert response.status_code in statuses, (method, path, response.status_code)
            result = response.json()
            self.observations.append({"method": method, "path": path, "httpStatus": response.status_code,
                                      "requestSHA256": driver.digest(body), "resultSHA256": driver.digest(result)})
            return result

    owner = uuid4().hex
    fresh = LocalNativeContext(case, owner, abort)
    sink = SimpleNamespace(TARGET="ISOLATED_LOCAL_ASGI_WITH_OWNED_REMOTE_PG", persist=persist_test)
    reference = driver.finite_reference(case.profile, owner)
    task = asyncio.create_task(asyncio.to_thread(driver.execute, fresh, sink, Api(), case.org,
                               [row["name"] for row in case.profile["warehouses"]], reference))
    try:
        try:
            observed = await asyncio.wait_for(asyncio.shield(task), 150)
        except BaseException as error:
            if case_name == "full_flow":
                persist_test(case.folder / "failure.json", pg_error(error))
                raise
            failure = pg_error(error)
            persist_test(case.folder / "expected-failure.json", failure)
            assert failure["expectedGuard"] is True and failure["sqlstate"] == "P0001"
            assert before, "Failure must reach actual shipment confirmation"
            async with case.factory() as session:
                assert await session.scalar(select(func.count()).select_from(models.Entry)) == before["entries"]
                assert await session.scalar(select(func.count()).select_from(models.ShipmentAccountingReceipt)) == before["receipts"]
                assert await session.scalar(select(func.count()).select_from(StockMovement)) == before["stock"]
                control = await session.scalar(select(models.SourceControl).where(models.SourceControl.source == before["source"]))
                assert control is not None and control.entry_id is None
        else:
            assert case_name == "full_flow", "Expected strict PostgreSQL rejection"
            assert (observed["netRevenueBYN"], observed["costBYN"], observed["grossProfitBYN"]) == ("300.00", "177.00", "123.00")
            assert observed["secondWarehouseUnchanged"] and observed["duplicateOperationRejected"]
            assert observed["stockRemaining"] == "0"
            persist_test(case.folder / "full-flow-result.json", {"financial": ["300.00", "177.00", "123.00"],
                         "replay": True, "twoWarehouses": True, "stockRemaining": "0", "driverSHA256": DRIVER_SHA})
    finally:
        abort.set()
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), 50)
            except BaseException:
                pass
            assert task.done(), "Isolated native thread must close"
        pending = list(active)
        for request in pending:
            request.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
