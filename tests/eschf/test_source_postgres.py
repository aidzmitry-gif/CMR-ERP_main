"""Real source ORM/ACL/PG locks plus a synthetic authenticated bridge.

Only the guarded disposable ESCHF DB is used. Source tables are the real owner
models in a unique translated fixture schema, removed at teardown. create_all
does not prove the Sales migration's immutability triggers (tested by its owner).
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.requests import Request

if not os.environ.get("ESCHF_TEST_DATABASE_URL"):
    pytest.skip(
        "ESCHF_TEST_DATABASE_URL required for source/bridge PG checks", allow_module_level=True
    )

from core.db.base import Base
from core.domain.models import (
    AuditLog,
    Counterparty,
    CounterpartyBranch,
    IdentityInvitationRequest,
    OutboxEvent,
    User,
)
from core.runtime.access import AccessControlMiddleware, build_prefix_map
from core.runtime.contract import Role
from core.runtime.core import Core
from core.runtime.loader import load_modules
from core.services.auth import CurrentUser
from core.services.eventbus import OutboxEventBus
from integrations.onec_eschf.adapter import canonical, sha256
from modules.eschf.bridge import MappingReceipt, SalesNativeSourceProvider, VerifiedCapture
from modules.eschf.models import Original, Snapshot
from modules.sales.models import Deal, DealDocument
from tests.eschf.test_repository_postgres import pg as pg
from tests.onec_eschf.test_adapter import (
    binding_for,
    identity,
    result_for,
    setup_case,
    synthetic_xml,
)


@pytest_asyncio.fixture
async def source_pg(pg):
    schema = "eschf_source_fixture_" + uuid4().hex
    engine = pg.kw["bind"].execution_options(schema_translate_map={None: schema, "sales": schema})
    tables = [
        User.__table__,
        Counterparty.__table__,
        CounterpartyBranch.__table__,
        Deal.__table__,
        DealDocument.__table__,
        OutboxEvent.__table__,
        AuditLog.__table__,
        IdentityInvitationRequest.__table__,
    ]
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            # Generated locally above, never a DSN/schema supplied by the caller.
            assert schema.startswith("eschf_source_fixture_") and len(schema) == 53
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


class SyntheticPipeline:
    environment = "synthetic"
    adapter_id = "synthetic-native-capture-fixture-v1"
    verifier_id = "synthetic-mapping-hmac-fixture-v1"
    key = b"synthetic-mapping-fixture-only"

    def __init__(self, native):
        self.native = native
        self.calls = []
        self.raw = None
        self.hook = None
        self.tamper = False
        self.scope = "synthetic_fixture"
        self.claim_changes = {}

    async def resolve(self, pin):
        self.calls.append("resolve")
        now = datetime.now(UTC)
        receipt = MappingReceipt(
            receipt_id="synthetic-receipt",
            issuer="synthetic-fixture-issuer",
            environment=self.environment,
            source_pin_sha256=pin.digest,
            source_material_sha256=pin.material_digest,
            binding=binding_for(pin.source, self.native, pin.selection),
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=2),
        )
        payload = receipt.model_dump(mode="json")
        payload.update(self.claim_changes)
        mac = hmac.new(self.key, canonical(payload), hashlib.sha256).hexdigest()
        self.raw = canonical({"payload": payload, "mac": "0" * 64 if self.tamper else mac})
        return self.raw

    def verify(self, raw):
        self.calls.append("verify")
        envelope = json.loads(raw)
        expected = hmac.new(self.key, canonical(envelope["payload"]), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(envelope["mac"], expected):
            raise ValueError("synthetic receipt signature mismatch")
        receipt = MappingReceipt.model_validate_json(canonical(envelope["payload"]))
        if receipt.issuer != "synthetic-fixture-issuer":
            raise ValueError("synthetic issuer not trusted")
        return receipt

    async def capture_verified(self, pin, receipt):
        self.calls.append("capture")
        if self.hook:
            await self.hook()
        payload = synthetic_xml(self.native)
        return VerifiedCapture(
            native=self.native,
            result=result_for(self.native, payload),
            xml_bytes=payload,
            codec="utf-8",
            byte_evidence_ref="synthetic-byte-fixture",
            proof=canonical(
                {
                    "source_pin_sha256": pin.digest,
                    "native_capture_sha256": receipt.binding.native_capture_sha256,
                    "fixture_only": True,
                }
            ),
            expires_at=receipt.expires_at,
            scope=self.scope,
        )


@pytest_asyncio.fixture
async def bridge_http(source_pg, monkeypatch):
    settings = SimpleNamespace(auth_mode="dev")
    for name in (
        "core.services.auth.get_settings",
        "core.runtime.access.get_settings",
        "modules.sales.access.get_settings",
    ):
        monkeypatch.setattr(name, lambda: settings)
    core = Core(
        SimpleNamespace(
            config=settings,
            event_bus=OutboxEventBus(),
            db=SimpleNamespace(session_factory=source_pg),
        )
    )
    load_modules(core, ["eschf"])
    core.declare_role(Role("source_reader", ("sales.deal.read",)))
    app = FastAPI()
    app.state.core = core
    source, _, native = setup_case(shared=True)
    snapshot = deepcopy(source.snapshot)
    snapshot["party"].update(
        legal_entity_revision=1,
        branch_revision=1,
        branch_name="Synthetic branch",
        branch_address="Synthetic address",
    )
    snapshot.update(kind="invoice", deal_id=401, number="ERP-source-number")
    async with source_pg.begin() as session:
        session.add(
            User(
                id=1,
                username="synthetic-accountant",
                full_name="Synthetic accountant",
                employee_id=701,
                role="eschf_accountant",
                status="active",
                deal_visibility="own",
            )
        )
        session.add(
            Counterparty(
                id=101,
                name="Unrelated display name",
                legal_name=snapshot["party"]["legal_name"],
                unp="111111111",
                requisites={"address": "Synthetic"},
            )
        )
        session.add(
            Deal(
                id=401,
                number="synthetic-deal",
                title="Synthetic deal",
                counterparty="Untrusted display label",
                counterparty_id=101,
                branch_id=201,
                owner_id=701,
                amount=Decimal("120"),
            )
        )
        await session.flush()
        session.add(
            CounterpartyBranch(
                id=201,
                legal_entity_id=101,
                name="Synthetic branch",
                address="Synthetic address",
                tax_mode="shared",
                portal_branch_code="0007",
            )
        )
        session.add(
            DealDocument(
                id=301,
                deal_id=401,
                kind="invoice",
                number="ERP-source-number",
                status="posted",
                version=1,
                amount=Decimal("120"),
                original_html=source.original_html,
                snapshot_json=snapshot,
                content_sha256=source.content_sha256,
                issued_at=datetime.now(UTC).replace(tzinfo=None),
                issued_by="synthetic-accountant",
                onec_ref="mock:untrusted-reference",
            )
        )
    pipeline = SyntheticPipeline(native)
    provider = SalesNativeSourceProvider(
        mapping_resolver=pipeline, mapping_verifier=pipeline, capture_provider=pipeline
    )
    app.state.eschf_source_provider = provider
    for registered in core.routers:
        app.include_router(registered.router, prefix=registered.prefix)
    app.add_middleware(AccessControlMiddleware, prefixes=build_prefix_map(core))
    actor = CurrentUser("synthetic-accountant", ["eschf_accountant", "source_reader"])
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/eschf/preparations",
            "headers": [],
            "app": app,
            "scheme": "http",
            "server": ("synthetic-local", 80),
            "query_string": b"",
        }
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://synthetic-local",
        headers={"X-User": actor.username, "X-User-Roles": ",".join(actor.roles)},
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            core=core,
            actor=actor,
            request=request,
            provider=provider,
            pipeline=pipeline,
            pg=source_pg,
        )


async def prepare(http):
    return await http.client.post(
        "/eschf/preparations", json={"source_document_id": 301, "source_document_version": 1}
    )


async def counts(pg):
    async with pg() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (Original, Snapshot, OutboxEvent)
            ]
        )


async def test_real_source_to_authenticated_mapping_to_durable_snapshot(bridge_http):
    h = bridge_http
    response = await prepare(h)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["environment"] == "synthetic" and data["state"] == "prepared"
    assert h.pipeline.calls == ["resolve", "verify", "capture"]
    async with h.pg() as session:
        snapshot = await session.get(Snapshot, UUID(data["id"]))
        binding = json.loads(snapshot.binding_snapshot)
        assert snapshot.unsigned_xml == synthetic_xml(h.pipeline.native)
        assert binding["binding_evidence"]["raw_sha256"] == sha256(h.pipeline.raw)
        assert base64.b64decode(binding["binding_evidence"]["raw_base64"]) == h.pipeline.raw
        assert binding["full_projection"]["scope"] == "local_envelope_only"
        assert binding["native_version_evidence"]["scope"] == "synthetic_fixture"
        assert binding["basis_reference"] == h.pipeline.native.basis.reference
        assert binding["native_invoice_uuid"] == h.pipeline.native.invoice.reference
        assert "mock:untrusted-reference" not in snapshot.binding_snapshot.decode()
    assert await counts(h.pg) == (1, 1, 1)


@pytest.mark.parametrize(
    "table,values,status",
    [
        (User, {"status": "suspended"}, 403),
        (User, {"employee_id": 999}, 404),
        (Deal, {"owner_id": 999}, 404),
        (DealDocument, {"issued_at": None}, 409),
        (DealDocument, {"superseded_by_id": 301}, 409),
        (DealDocument, {"status": "cancelled"}, 409),
        (DealDocument, {"version": 2}, 409),
        (DealDocument, {"kind": "contract"}, 409),
        (DealDocument, {"original_html": "tampered"}, 409),
        (DealDocument, {"content_sha256": "0" * 64}, 409),
        (Counterparty, {"revision": 2}, 409),
        (Counterparty, {"is_active": False}, 409),
        (Counterparty, {"merged_into_id": 101}, 409),
        (Counterparty, {"legal_name": None}, 409),
        (CounterpartyBranch, {"revision": 2}, 409),
        (CounterpartyBranch, {"is_active": False}, 409),
        (CounterpartyBranch, {"portal_branch_code": "0008"}, 409),
        (CounterpartyBranch, {"tax_mode": "unknown"}, 409),
    ],
)
async def test_source_denial_precedes_any_mapping_callback(bridge_http, table, values, status):
    h = bridge_http
    async with h.pg.begin() as session:
        await session.execute(update(table).values(**values))
    response = await prepare(h)
    assert response.status_code == status, response.text
    assert not h.pipeline.calls and await counts(h.pg) == (0, 0, 0)


@pytest.mark.parametrize(
    "change", ["legacy_party", "snapshot_version", "foreign_branch", "wrong_unp", "snapshot_number"]
)
async def test_source_snapshot_and_branch_identity_are_required(bridge_http, change):
    h = bridge_http
    async with h.pg.begin() as session:
        doc = await session.get(DealDocument, 301)
        data = deepcopy(doc.snapshot_json)
        if change == "legacy_party":
            del data["party"]
        elif change == "snapshot_version":
            data["version"] = 9
        elif change == "wrong_unp":
            data["party"]["legal_entity_unp"] = "999999999"
        elif change == "snapshot_number":
            data["number"] = "another-source-number"
        else:
            session.add(Counterparty(id=102, name="Another", legal_name="Another", unp="999999999"))
            await session.flush()
            await session.execute(update(CounterpartyBranch).values(legal_entity_id=102))
        await session.execute(update(DealDocument).values(snapshot_json=data))
    response = await prepare(h)
    assert response.status_code == 409, response.text
    assert not h.pipeline.calls


async def test_eschf_permission_does_not_grant_source_access(bridge_http):
    h = bridge_http
    response = await h.client.post(
        "/eschf/preparations",
        json={"source_document_id": 301, "source_document_version": 1},
        headers={"X-User-Roles": "eschf_accountant"},
    )
    assert response.status_code == 403 and not h.pipeline.calls


@pytest.mark.parametrize("component", ["mapping_resolver", "mapping_verifier", "capture_provider"])
async def test_each_unwired_bridge_component_fails_503(bridge_http, component):
    setattr(bridge_http.provider, component, None)
    response = await prepare(bridge_http)
    assert response.status_code == 503
    assert response.json()["detail"] == "eschf_native_bridge_unavailable"
    assert await counts(bridge_http.pg) == (0, 0, 0)


@pytest.mark.parametrize(
    "change", ["signature", "issuer", "source_pin", "expired", "scope", "basis", "dependency"]
)
async def test_untrusted_stale_or_mismatched_native_material_is_rejected(bridge_http, change):
    h = bridge_http
    if change == "signature":
        h.pipeline.tamper = True
    elif change == "issuer":
        h.pipeline.claim_changes["issuer"] = "untrusted-issuer"
    elif change == "source_pin":
        h.pipeline.claim_changes["source_pin_sha256"] = "0" * 64
    elif change == "expired":
        h.pipeline.claim_changes["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=10)
        ).isoformat()
    elif change == "scope":
        h.pipeline.environment = "native"
        h.pipeline.scope = "local_envelope_only"
    else:

        async def change_capture():
            updates = (
                {"basis": identity("Document.РеализацияТоваровУслуг", 999)}
                if change == "basis"
                else {"captured_dependencies": {"changed": True}}
            )
            h.pipeline.native = h.pipeline.native.model_copy(update=updates)

        h.pipeline.hook = change_capture
    response = await prepare(h)
    assert response.status_code == 409, response.text
    assert await counts(h.pg) == (0, 0, 0)


@pytest.mark.parametrize(
    "table,values,status",
    [
        (User, {"status": "suspended"}, 403),
        (User, {"deal_visibility": "all"}, 409),
        (Deal, {"owner_id": 999}, 404),
        (DealDocument, {"superseded_by_id": 301}, 409),
        (Counterparty, {"revision": 2}, 409),
        (Counterparty, {"requisites": {"changed_by_sql_without_revision": True}}, 409),
        (CounterpartyBranch, {"portal_branch_code": "0009"}, 409),
    ],
)
async def test_final_transaction_rechecks_access_source_and_parties(
    bridge_http, table, values, status
):
    h = bridge_http

    async def mutate_after_source_read():
        async with h.pg.begin() as session:
            await session.execute(update(table).values(**values))

    h.pipeline.hook = mutate_after_source_read
    response = await prepare(h)
    assert response.status_code == status, response.text
    assert h.pipeline.calls == ["resolve", "verify", "capture"]
    assert await counts(h.pg) == (0, 0, 0)


async def test_native_callback_has_no_source_row_locks(bridge_http):
    h = bridge_http

    async def writer_probe():
        async def update_same_values():
            async with h.pg.begin() as session:
                await session.execute(update(Deal).values(owner_id=701))
                await session.execute(update(Counterparty).values(revision=1))

        await asyncio.wait_for(update_same_values(), 3)

    h.pipeline.hook = writer_probe
    assert (await prepare(h)).status_code == 201


async def test_final_pg_share_lock_lasts_until_caller_commit(bridge_http):
    h = bridge_http
    prepared = await h.provider.prepare_source(h.request, h.actor, 301, 1)
    writer = None
    try:
        async with h.pg() as holder:
            async with holder.begin():
                await prepared.recheck(holder, h.actor)
                holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))

                async def update_party():
                    async with h.pg.begin() as session:
                        await session.execute(update(Counterparty).values(revision=2))

                writer = asyncio.create_task(update_party())
                blocked = 0
                async with h.pg() as observer:
                    for _ in range(100):
                        blocked = await observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))"
                            ),
                            {"pid": holder_pid},
                        )
                        if blocked:
                            break
                        await asyncio.sleep(0.02)
                assert blocked and not writer.done(), "No real PostgreSQL source lock wait observed"
            await asyncio.wait_for(writer, 3)
    finally:
        if writer and not writer.done():
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)


async def test_recheck_refuses_another_actor_and_expired_evidence(bridge_http, monkeypatch):
    h = bridge_http
    prepared = await h.provider.prepare_source(h.request, h.actor, 301, 1)
    async with h.pg.begin() as session:
        with pytest.raises((PermissionError, HTTPException, ValueError)):
            await prepared.recheck(session, CurrentUser("other-user", h.actor.roles))
    future = datetime.now(UTC) + timedelta(days=1)
    monkeypatch.setattr("modules.eschf.bridge.datetime", SimpleNamespace(now=lambda tz: future))
    async with h.pg.begin() as session:
        with pytest.raises(ValueError, match="expired"):
            await prepared.recheck(session, h.actor)


async def test_refresh_rechecks_source_and_keeps_previous_snapshot_on_failure(bridge_http):
    h = bridge_http
    first = (await prepare(h)).json()
    h.pipeline.native = h.pipeline.native.model_copy(update={"number": "123456789-2026-0000000002"})
    response = await h.client.post(
        f"/eschf/{first['id']}/refresh", json={"source_document_version": 1}
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["number"] != first["number"] and second["original_id"] == first["original_id"]
    before = await counts(h.pg)

    async def cancel_source():
        async with h.pg.begin() as session:
            await session.execute(update(DealDocument).values(status="cancelled"))

    h.pipeline.hook = cancel_source
    response = await h.client.post(
        f"/eschf/{second['id']}/refresh", json={"source_document_version": 1}
    )
    assert response.status_code == 409 and await counts(h.pg) == before
    assert (await h.client.get(f"/eschf/{second['id']}")).json()["state"] == "prepared"


async def test_oidc_source_uses_stable_subject_without_username_fallback(bridge_http):
    h = bridge_http
    h.core.declare_role(Role("eschf_accountant", ("sales.deal.read",)))
    async with h.pg.begin() as session:
        await session.execute(update(User).values(keycloak_user_id="synthetic-stable-subject"))
    actor = CurrentUser(
        "renamed-accountant",
        ["eschf_accountant"],
        "synthetic-stable-subject",
        issued_at=int(datetime.now(UTC).timestamp()),
    )
    prepared = await h.provider.prepare_source(h.request, actor, 301, 1)
    async with h.pg.begin() as session:
        await prepared.recheck(session, actor)
    unknown_subject = CurrentUser("synthetic-accountant", ["eschf_accountant"], "unknown-subject")
    with pytest.raises(HTTPException) as error:
        await h.provider.prepare_source(h.request, unknown_subject, 301, 1)
    assert error.value.status_code == 403


async def test_oidc_revocation_fact_is_rechecked_after_native_io(bridge_http):
    h = bridge_http
    h.core.declare_role(Role("eschf_accountant", ("sales.deal.read",)))
    async with h.pg.begin() as session:
        await session.execute(update(User).values(keycloak_user_id="synthetic-stable-subject"))
    actor = CurrentUser(
        "synthetic-accountant",
        ["eschf_accountant"],
        "synthetic-stable-subject",
        issued_at=int((datetime.now(UTC) - timedelta(seconds=10)).timestamp()),
    )
    prepared = await h.provider.prepare_source(h.request, actor, 301, 1)
    async with h.pg.begin() as session:
        session.add(
            AuditLog(
                actor="synthetic-operator",
                action="identity.user.crm_access_requested",
                entity_ref="employee:701",
                detail={},
            )
        )
    async with h.pg.begin() as session:
        with pytest.raises(PermissionError, match="current source permission"):
            await prepared.recheck(session, actor)
