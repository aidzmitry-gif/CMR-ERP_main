"""Real ModuleContract/ASGI/auth/PG boundary, using explicit synthetic providers.

No main-app activation, real OIDC server, native binding, crypto or portal proof.
The shared middleware and get_current_user dependencies are not replaced.
"""

import json
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

if not os.environ.get("ESCHF_TEST_DATABASE_URL"):
    pytest.skip(
        "ESCHF_TEST_DATABASE_URL required for real ASGI/PostgreSQL evidence",
        allow_module_level=True,
    )

from core.domain.models import OutboxEvent
from core.runtime.access import AccessControlMiddleware, build_prefix_map
from core.runtime.core import Core
from core.runtime.loader import load_modules
from core.services.auth import CurrentUser
from core.services.eventbus import OutboxEventBus
from modules.eschf.bridge import PreparedSource
from modules.eschf.models import (
    Attempt,
    Decision,
    Observation,
    Original,
    SignedArtifact,
    Snapshot,
)
from modules.eschf.preparation import canonical, sha256
from modules.eschf.repository import Repository
from modules.eschf.routes import MAX_ARTIFACT_BYTES
from tests.eschf import test_repository_postgres as repository_fixtures
from tests.eschf.test_repository_postgres import SyntheticAdapter
from tests.eschf.test_repository_postgres import pg as pg

pytestmark = pytest.mark.integration
repository_value = repository_fixtures.value
ACCOUNTANT = {"X-User": "synthetic-accountant", "X-User-Roles": "eschf_accountant"}
BINARY = {"Content-Type": "application/octet-stream"}
SOURCE = {"source_document_id": 101, "source_document_version": 3}


@pytest.fixture
def value(repository_value):
    data = json.loads(repository_value.binding_snapshot)
    data["binding_evidence"].update(material_schema=1, source_material_sha256="c" * 64)
    return replace(repository_value, binding_snapshot=canonical(data))


class SyntheticSourceProvider:
    """Authenticated application wiring fixture; no native system is contacted."""

    def __init__(self, value):
        self.values = {3: value}
        self.calls = []
        self.failure = None

    async def prepare_source(self, request, user, source_document_id, source_document_version):
        self.calls.append((user, source_document_id, source_document_version))
        if self.failure:
            raise self.failure
        if source_document_id != 101:
            raise PermissionError("synthetic source ACL denial")
        if source_document_version not in self.values:
            raise ValueError("synthetic stale source")

        async def synthetic_recheck(session, current_user):
            assert session.in_transaction() and current_user == user

        return PreparedSource(self.values[source_document_version], synthetic_recheck)

    async def revalidate_source(self, request, user, persisted):
        # Isolated API fixture only; real source/provenance checks are exercised
        # by test_source_postgres/test_freshness_postgres with SalesNativeSourceProvider.
        if persisted not in self.values.values():
            raise ValueError("synthetic preview changed")

        async def synthetic_recheck(session, current_user):
            assert session.in_transaction() and current_user == user

        return PreparedSource(persisted, synthetic_recheck)


@pytest_asyncio.fixture
async def http(pg, value, monkeypatch):
    settings = SimpleNamespace(auth_mode="dev")
    monkeypatch.setattr("core.services.auth.get_settings", lambda: settings)
    monkeypatch.setattr("core.runtime.access.get_settings", lambda: settings)
    core = Core(
        SimpleNamespace(
            config=settings, event_bus=OutboxEventBus(), db=SimpleNamespace(session_factory=pg)
        )
    )
    load_modules(core, ["eschf"])
    app = FastAPI()
    app.state.core = core
    app.state.eschf_source_provider = SyntheticSourceProvider(value)
    app.state.eschf_evidence_adapter = SyntheticAdapter()
    for registered in core.routers:
        app.include_router(registered.router, prefix=registered.prefix)
    app.add_middleware(AccessControlMiddleware, prefixes=build_prefix_map(core))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://synthetic-local", headers=ACCOUNTANT
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            core=core,
            provider=app.state.eschf_source_provider,
            adapter=app.state.eschf_evidence_adapter,
            settings=settings,
        )


async def counts(pg):
    async with pg() as session:
        return {
            model.__name__: await session.scalar(select(func.count()).select_from(model))
            for model in (
                Original,
                Snapshot,
                Decision,
                SignedArtifact,
                Attempt,
                Observation,
                OutboxEvent,
            )
        }


async def prepared(http):
    response = await http.client.post("/eschf/preparations", json=SOURCE)
    assert response.status_code == 201, response.text
    return response.json()


async def approved(http):
    snapshot = await prepared(http)
    response = await http.client.post(
        f"/eschf/{snapshot['id']}/approval",
        json={key: snapshot[key] for key in ("binding_sha256", "unsigned_sha256")},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def queued(http, value):
    snapshot = await approved(http)
    response = await http.client.post(
        f"/eschf/{snapshot['id']}/signed-artifact",
        content=http.adapter.signed(value),
        headers=BINARY,
    )
    assert response.status_code == 200, response.text
    response = await http.client.post(f"/eschf/{snapshot['id']}/queue", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_module_contract_is_declared_without_dispatch(http):
    assert http.core.loaded_modules == ["eschf"]
    assert {(r.module, r.prefix) for r in http.core.routers} == {("eschf", "/eschf")}
    assert {p.code for p in http.core.permissions} == {
        f"eschf.{p}" for p in ("read", "prepare", "approve", "queue", "worker", "reconcile")
    }
    assert {r.name for r in http.core.roles} == {
        "eschf_accountant",
        "eschf_auditor",
        "eschf_worker",
    }
    assert (
        not http.core.events
        and not http.core.tick_hooks
        and not http.core.startup_hooks
        and not http.core.workflows
    )


async def test_guest_unrelated_role_and_auditor_permissions_cover_every_route(http, pg):
    snapshot = await prepared(http)
    root = f"/eschf/{snapshot['id']}"
    writes = [
        ("/eschf/preparations", SOURCE),
        (root + "/refresh", {"source_document_version": 3}),
        (
            root + "/approval",
            {
                "binding_sha256": snapshot["binding_sha256"],
                "unsigned_sha256": snapshot["unsigned_sha256"],
            },
        ),
        (root + "/queue", {}),
        (root + "/recovery", {}),
        (root + "/signed-artifact", {}),
        (root + "/observations", {}),
    ]
    before = await counts(pg)
    for role in ("", "sales", "eschf_auditor"):
        headers = {"X-User-Roles": role}
        for path, body in writes:
            response = await http.client.post(path, json=body, headers=headers)
            assert response.status_code == 403, (role, path, response.text)
        for suffix in ("", "/xml", "/history"):
            response = await http.client.get(root + suffix, headers=headers)
            assert response.status_code == (200 if role == "eschf_auditor" else 403)
    # The worker can reconcile, but cannot prepare/approve/sign/queue.
    for path, body in writes[:4] + [writes[5]]:
        response = await http.client.post(path, json=body, headers={"X-User-Roles": "eschf_worker"})
        assert response.status_code == 403, (path, response.text)
    assert await counts(pg) == before
    assert len(http.provider.calls) == 1


async def test_no_credentials_and_invalid_oidc_keep_shared_403(http, pg, monkeypatch):
    # Clear dev fixture identity entirely: shared auth fails closed.
    http.client.headers.clear()
    assert (await http.client.post("/eschf/preparations", json=SOURCE)).status_code == 403
    http.settings.auth_mode = "oidc"
    tokens = []

    def validate(token):
        tokens.append(token)
        return None

    monkeypatch.setattr(
        "core.services.auth._get_authenticator", lambda settings: SimpleNamespace(validate=validate)
    )
    response = await http.client.post(
        "/eschf/preparations",
        json=SOURCE,
        headers={"Authorization": "Bearer invalid-synthetic-token", **ACCOUNTANT},
    )
    assert response.status_code == 403
    assert tokens == ["invalid-synthetic-token"]
    assert not http.provider.calls
    assert not any((await counts(pg)).values())


async def test_unwired_source_503_and_client_native_fields_are_rejected(http, pg):
    for addition in (
        {"native_invoice_uuid": str(uuid4())},
        {"signature_verified": True},
        {"environment": "native"},
        {"binding_snapshot": {}},
        {"source_document_id": True},
    ):
        response = await http.client.post("/eschf/preparations", json={**SOURCE, **addition})
        assert response.status_code == 422
    del http.app.state.eschf_source_provider
    response = await http.client.post("/eschf/preparations", json=SOURCE)
    assert response.status_code == 503
    assert response.json()["detail"] == "eschf_source_provider_unavailable"
    assert not http.provider.calls
    assert not any((await counts(pg)).values())


@pytest.mark.parametrize(
    "failure,status",
    [
        (PermissionError("private source"), 403),
        (ValueError("private native version"), 409),
        (RuntimeError("private provider connection"), 503),
    ],
)
async def test_source_provider_failures_are_sanitized_and_leave_no_writes(
    http, pg, failure, status
):
    http.provider.failure = failure
    response = await http.client.post("/eschf/preparations", json=SOURCE)
    assert response.status_code == status
    assert "private" not in response.text
    assert not any((await counts(pg)).values())


@pytest.mark.parametrize("field", ["source_document_id", "source_document_version"])
async def test_provider_cannot_return_another_source_or_version(http, pg, value, field):
    binding = json.loads(value.binding_snapshot)
    binding[field] += 1
    http.provider.values[3] = replace(value, binding_snapshot=canonical(binding))
    response = await http.client.post("/eschf/preparations", json=SOURCE)
    assert response.status_code == 503
    assert response.json()["detail"] == "eschf_source_provider_contract_mismatch"
    assert not any((await counts(pg)).values())


async def test_prepare_read_exact_xml_and_hash_approval_are_durable(http, pg, value):
    snapshot = await prepared(http)
    assert snapshot["environment"] == "synthetic" and snapshot["state"] == "prepared"
    assert snapshot["created_by"] == "synthetic-accountant"
    assert snapshot["binding_sha256"] == sha256(value.binding_snapshot)
    assert snapshot["unsigned_sha256"] == sha256(value.unsigned_xml)
    assert snapshot["signed_sha256"] is None and snapshot["observation_id"] is None
    user, source_id, version = http.provider.calls[0]
    assert isinstance(user, CurrentUser) and user.username == "synthetic-accountant"
    assert (source_id, version) == (101, 3)
    root = f"/eschf/{snapshot['id']}"
    xml = await http.client.get(root + "/xml")
    assert xml.content == value.unsigned_xml
    assert xml.headers["etag"] == f'"{sha256(value.unsigned_xml)}"'
    assert xml.headers["content-disposition"].startswith("attachment;")
    assert xml.headers["cache-control"] == "no-store"
    assert xml.headers["x-content-type-options"] == "nosniff"
    before = await counts(pg)
    assert (
        await http.client.post(
            root + "/approval",
            json={"binding_sha256": "0" * 64, "unsigned_sha256": snapshot["unsigned_sha256"]},
        )
    ).status_code == 409
    assert await counts(pg) == before
    response = await http.client.post(
        root + "/approval",
        json={key: snapshot[key] for key in ("binding_sha256", "unsigned_sha256")},
    )
    assert response.status_code == 200
    assert response.json()["approved_binding_sha256"] == snapshot["binding_sha256"]
    # Independent sessions/HTTP requests observe the committed facts and outbox.
    assert (await http.client.get(root)).json()["state"] == "approved"
    result = await counts(pg)
    assert result["Decision"] == 1 and result["OutboxEvent"] == 2
    history = (await http.client.get(root + "/history")).json()
    assert history["decisions"][0]["actor"] == "synthetic-accountant"
    assert history["attempt"] is None and history["observations"] == []


async def test_signed_relation_queue_outbox_and_no_send_attempt(http, pg, value):
    snapshot = await queued(http, value)
    assert snapshot["state"] == "queued"
    assert snapshot["signed_sha256"] == sha256(http.adapter.signed(value))
    assert snapshot["signed_sha256"] != snapshot["unsigned_sha256"]
    assert snapshot["signed_adapter_id"] == http.adapter.adapter_id
    async with pg() as session:
        artifact = await session.get(SignedArtifact, UUID(snapshot["id"]))
        assert artifact.signed_bytes == http.adapter.signed(value)
        assert artifact.unsigned_sha256 == snapshot["unsigned_sha256"]
        events = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
        assert [event.event_type for event in events] == [
            "eschf.prepared",
            "eschf.approved",
            "eschf.signed_artifact_attached",
            "eschf.queued",
        ]
        assert all(event.payload["by"] == "synthetic-accountant" for event in events)
        assert await session.scalar(select(func.count()).select_from(Attempt)) == 0


async def test_unwired_verifier_and_untrusted_signed_payload_never_advance_state(http, pg, value):
    snapshot = await approved(http)
    path = f"/eschf/{snapshot['id']}/signed-artifact"
    before = await counts(pg)
    del http.app.state.eschf_evidence_adapter
    assert (await http.client.post(path, content=b"anything", headers=BINARY)).status_code == 503
    http.app.state.eschf_evidence_adapter = http.adapter
    assert (await http.client.post(path, json={"signature_verified": True})).status_code == 415
    assert (
        await http.client.post(
            path, content=canonical({"signature_verified": True}), headers=BINARY
        )
    ).status_code == 409
    wrong = replace(value, unsigned_xml=b"<DifferentFinalXML/>")
    assert (
        await http.client.post(path, content=http.adapter.signed(wrong), headers=BINARY)
    ).status_code == 409
    assert await counts(pg) == before
    assert (await http.client.get(f"/eschf/{snapshot['id']}")).json()["state"] == "approved"


async def test_raw_artifact_stream_is_bounded_even_without_content_length(http, pg):
    snapshot = await approved(http)
    before = await counts(pg)

    async def chunks():
        for _ in range(MAX_ARTIFACT_BYTES // 65536 + 1):
            yield b"x" * 65536

    response = await http.client.post(
        f"/eschf/{snapshot['id']}/signed-artifact", content=chunks(), headers=BINARY
    )
    assert response.status_code == 413
    assert await counts(pg) == before


async def test_preparation_outbox_failure_rolls_back_all_rows(http, pg, monkeypatch):
    original = http.core.event_bus.emit

    def fail_after_add(*args, **kwargs):
        original(*args, **kwargs)
        raise SQLAlchemyError("synthetic private DB failure")

    monkeypatch.setattr(http.core.event_bus, "emit", fail_after_add)
    response = await http.client.post("/eschf/preparations", json=SOURCE)
    assert response.status_code == 503
    assert "private" not in response.text
    assert not any((await counts(pg)).values())


async def test_approval_outbox_failure_rolls_back_fact_and_projection(http, pg, monkeypatch):
    snapshot = await prepared(http)
    before = await counts(pg)

    def fail(*args, **kwargs):
        raise SQLAlchemyError("synthetic write failure")

    monkeypatch.setattr(http.core.event_bus, "emit", fail)
    response = await http.client.post(
        f"/eschf/{snapshot['id']}/approval",
        json={key: snapshot[key] for key in ("binding_sha256", "unsigned_sha256")},
    )
    assert response.status_code == 503
    assert await counts(pg) == before
    assert (await http.client.get(f"/eschf/{snapshot['id']}")).json()["state"] == "prepared"


async def test_pre_attempt_refresh_changes_native_number_and_requires_new_approval(http, pg, value):
    old = await approved(http)
    binding = json.loads(value.binding_snapshot)
    xml = b"<SyntheticChangedFinalXML/>"
    binding.update(source_document_version=4, prepared_xml_sha256=sha256(xml))
    http.provider.values[4] = replace(
        value,
        number="100000000-2026-0000000002",
        unsigned_xml=xml,
        binding_snapshot=canonical(binding),
    )
    response = await http.client.post(
        f"/eschf/{old['id']}/refresh", json={"source_document_version": 4}
    )
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["original_id"] == old["original_id"] and new["supersedes_id"] == old["id"]
    assert new["number"] != old["number"] and new["source_document_version"] == 4
    assert new["state"] == "prepared" and new["approved_by"] is None
    assert (await http.client.get(f"/eschf/{old['id']}")).json()["state"] == "superseded"
    before = await counts(pg)
    response = await http.client.post(
        f"/eschf/{new['id']}/approval",
        json={key: old[key] for key in ("binding_sha256", "unsigned_sha256")},
    )
    assert response.status_code == 409 and await counts(pg) == before


async def test_attempt_unknown_recovery_and_authenticated_synthetic_observation(http, pg, value):
    snapshot = await queued(http, value)
    snapshot_id = UUID(snapshot["id"])
    worker = CurrentUser("synthetic-worker", ["eschf_worker"])
    async with pg.begin() as session:
        repository = Repository(
            session, core=http.core, event_bus=http.core.event_bus, adapter=http.adapter
        )
        assert (await repository.claim_next(worker)).snapshot_id == snapshot_id
        await repository.mark_unknown(worker, snapshot_id, reason="timeout")
    root = f"/eschf/{snapshot_id}"
    assert (await http.client.post(root + "/queue", json={})).status_code == 409
    assert (
        await http.client.post(root + "/refresh", json={"source_document_version": 3})
    ).status_code == 409
    # Corrupt an unconstrained projection field; the API refuses a false view.
    async with pg.begin() as session:
        await session.execute(
            text("UPDATE eschf.delivery SET unknown_reason='lost_response' WHERE snapshot_id=:id"),
            {"id": snapshot_id},
        )
    assert (await http.client.get(root)).status_code == 409
    response = await http.client.post(
        root + "/recovery", json={}, headers={"X-User-Roles": "eschf_worker"}
    )
    assert response.status_code == 200
    assert (
        response.json()["state"] == "delivery_unknown"
        and response.json()["unknown_reason"] == "timeout"
    )
    before = await counts(pg)
    response = await http.client.post(
        root + "/observations",
        content=canonical({"signature_verified": True, "code": "COMPLETED"}),
        headers=BINARY,
    )
    assert response.status_code == 409 and await counts(pg) == before
    evidence = http.adapter.portal(value)
    response = await http.client.post(root + "/observations", content=evidence, headers=BINARY)
    assert response.status_code == 200, response.text
    observed = response.json()
    assert observed["state"] == "issued" and observed["environment"] == "synthetic"
    assert observed["evidence_sha256"] == sha256(evidence) and observed["observation_id"]
    history = (await http.client.get(root + "/history")).json()
    assert history["snapshot_id"] == str(snapshot_id) and history["environment"] == "synthetic"
    assert history["attempt"]["worker_id"] == "synthetic-worker"
    assert history["observations"][0]["adapter_id"] == http.adapter.adapter_id
    async with pg() as session:
        observation = await session.get(Observation, UUID(observed["observation_id"]))
        assert observation.raw_evidence == evidence
    assert (await counts(pg))["Attempt"] == 1


async def test_unknown_snapshot_returns_404_without_details(http):
    response = await http.client.get(f"/eschf/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "eschf_snapshot_not_found"}
