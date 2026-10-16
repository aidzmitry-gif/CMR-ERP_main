"""Approve/queue freshness on guarded PG/real ACL with synthetic native callbacks.

No native runtime or portal proof. The fixtures reuse the actual module/router,
Sales source resolver and authenticated mapping verifier from bridge checks.
"""

import asyncio
import base64
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

if not os.environ.get("ESCHF_TEST_DATABASE_URL"):
    pytest.skip("ESCHF_TEST_DATABASE_URL required for freshness checks", allow_module_level=True)

from core.domain.models import Counterparty, CounterpartyBranch, OutboxEvent, User
from core.services.auth import CurrentUser
from integrations.onec_eschf.adapter import canonical
from modules.eschf.models import Attempt, Decision, DeliveryRecord, SignedArtifact, Snapshot
from modules.eschf.repository import Repository, SnapshotInput
from modules.sales.models import DealDocument
from tests.eschf.test_repository_postgres import SyntheticAdapter
from tests.eschf.test_source_postgres import bridge_http as bridge_http
from tests.eschf.test_source_postgres import pg as pg
from tests.eschf.test_source_postgres import prepare
from tests.eschf.test_source_postgres import source_pg as source_pg


async def saved_value(h, snapshot_id):
    async with h.pg() as session:
        row = await session.get(Snapshot, UUID(snapshot_id))
        return SnapshotInput(
            row.number,
            row.taxpayer_unp,
            row.binding_snapshot,
            row.unsigned_xml,
            row.adapter_id,
            row.environment,
        )


async def send_action(h, data, action, *, headers=None):
    body = (
        {key: data[key] for key in ("binding_sha256", "unsigned_sha256")}
        if action == "approval"
        else {}
    )
    return await h.client.post(f"/eschf/{data['id']}/{action}", json=body, headers=headers)


async def candidate(h, action):
    response = await prepare(h)
    assert response.status_code == 201, response.text
    data = response.json()
    if action == "queue":
        response = await send_action(h, data, "approval")
        assert response.status_code == 200, response.text
        adapter = SyntheticAdapter()
        h.app.state.eschf_evidence_adapter = adapter
        raw = adapter.signed(await saved_value(h, data["id"]))
        response = await h.client.post(
            f"/eschf/{data['id']}/signed-artifact",
            content=raw,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
    return data


async def durable_state(h, snapshot_id):
    async with h.pg() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (Snapshot, Decision, SignedArtifact, Attempt, OutboxEvent)
        ]
        row = await session.get(DeliveryRecord, UUID(snapshot_id))
        return (
            counts,
            row.state,
            row.approved_by,
            row.approved_binding_sha256,
            row.approved_unsigned_sha256,
            await saved_value(h, snapshot_id),
        )


async def assert_stale_unchanged(h, data, action, before):
    response = await send_action(h, data, action)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "preview_stale"}
    assert await durable_state(h, data["id"]) == before


async def test_another_authorized_approver_preserves_exact_preview_and_receipt(bridge_http):
    h = bridge_http
    data = await candidate(h, "approval")
    original = await saved_value(h, data["id"])
    async with h.pg.begin() as session:
        session.add(
            User(
                id=2,
                username="second-accountant",
                full_name="Second synthetic accountant",
                employee_id=702,
                role="eschf_accountant",
                status="active",
                deal_visibility="all",
            )
        )
    second = CurrentUser("second-accountant", h.actor.roles)
    async with h.pg.begin() as session:
        pin_a = await h.provider.source_resolver.load(session, h.request, h.actor, 301, 1)
        pin_b = await h.provider.source_resolver.load(session, h.request, second, 301, 1)
    assert pin_a.digest != pin_b.digest and pin_a.material_digest == pin_b.material_digest
    headers = {"X-User": second.username, "X-User-Roles": ",".join(second.roles)}
    response = await send_action(h, data, "approval", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["approved_by"] == second.username
    assert await saved_value(h, data["id"]) == original
    adapter = SyntheticAdapter()
    h.app.state.eschf_evidence_adapter = adapter
    signed = adapter.signed(original)
    assert (
        await h.client.post(
            f"/eschf/{data['id']}/signed-artifact",
            content=signed,
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
    ).status_code == 200
    response = await send_action(h, data, "queue", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "queued"
    assert await saved_value(h, data["id"]) == original
    async with h.pg() as session:
        artifact = await session.get(SignedArtifact, UUID(data["id"]))
        assert artifact.signed_bytes == signed
        assert await session.scalar(select(func.count()).select_from(Attempt)) == 0
    # A new receipt was used for verification but did not overwrite the saved one.
    assert (
        json.loads(original.binding_snapshot)["binding_evidence"]["raw_base64"]
        != base64.b64encode(h.pipeline.raw).decode()
    )


@pytest.mark.parametrize("action", ["approval", "queue"])
@pytest.mark.parametrize(
    "change",
    ["source", "party", "branch", "mapping", "xml", "scope", "current_receipt", "signature"],
)
async def test_changed_preview_requires_refresh_without_decision_or_outbox(
    bridge_http, monkeypatch, action, change
):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])
    if change in {"source", "party", "branch"}:
        model, values = {
            "source": (DealDocument, {"version": 2}),
            "party": (Counterparty, {"revision": 2}),
            "branch": (CounterpartyBranch, {"portal_branch_code": "0009"}),
        }[change]
        async with h.pg.begin() as session:
            await session.execute(update(model).values(**values))
    elif change == "mapping":
        h.pipeline.native = h.pipeline.native.model_copy(
            update={"captured_dependencies": {"new_dependency": True}}
        )
    elif change == "xml":
        capture = h.pipeline.capture_verified

        async def changed_bytes(pin, receipt):
            result = await capture(pin, receipt)
            raw = result.xml_bytes + b"\n"
            return replace(
                result,
                xml_bytes=raw,
                result=result.result.model_copy(update={"xml_text": raw.decode("utf-8")}),
            )

        monkeypatch.setattr(h.pipeline, "capture_verified", changed_bytes)
    elif change == "scope":
        h.pipeline.scope = "local_envelope_only"
    elif change == "current_receipt":
        h.pipeline.claim_changes["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=5)
        ).isoformat()
    else:
        h.pipeline.tamper = True
    await assert_stale_unchanged(h, data, action, before)


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_original_receipt_expiry_cannot_be_extended_silently(
    bridge_http, monkeypatch, action
):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])
    calls = len(h.pipeline.calls)
    future = datetime.now(UTC) + timedelta(minutes=3)
    monkeypatch.setattr(
        "modules.eschf.bridge.datetime",
        SimpleNamespace(now=lambda tz: future, fromisoformat=datetime.fromisoformat),
    )
    await assert_stale_unchanged(h, data, action, before)
    assert h.pipeline.calls[calls:] == ["verify"]


@pytest.mark.parametrize("action", ["approval", "queue"])
@pytest.mark.parametrize("component", ["mapping_resolver", "mapping_verifier", "capture_provider"])
async def test_unavailable_runtime_returns_503_without_mutation(bridge_http, action, component):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])
    setattr(h.provider, component, None)
    response = await send_action(h, data, action)
    assert response.status_code == 503
    assert await durable_state(h, data["id"]) == before


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_old_snapshot_without_material_fingerprint_requires_explicit_refresh(
    bridge_http, action
):
    h = bridge_http
    prepared = await h.provider.prepare_source(h.request, h.actor, 301, 1)
    binding = json.loads(prepared.value.binding_snapshot)
    del binding["binding_evidence"]["material_schema"]
    del binding["binding_evidence"]["source_material_sha256"]
    legacy = replace(prepared.value, binding_snapshot=canonical(binding))
    adapter = SyntheticAdapter()
    async with h.pg.begin() as session:
        repo = Repository(session, core=h.core, event_bus=h.core.event_bus, adapter=adapter)
        snapshot_id = await repo.prepare(h.actor, legacy)
        if action == "queue":
            row, _ = await repo.get(h.actor, snapshot_id)
            await repo.approve(
                h.actor,
                snapshot_id,
                binding_sha256=row.binding_sha256,
                unsigned_sha256=row.unsigned_sha256,
            )
            await repo.attach_signed(h.actor, snapshot_id, adapter.signed(legacy))
    data = (await h.client.get(f"/eschf/{snapshot_id}")).json()
    before = await durable_state(h, data["id"])
    await assert_stale_unchanged(h, data, action, before)
    response = await h.client.post(
        f"/eschf/{snapshot_id}/refresh", json={"source_document_version": 1}
    )
    assert response.status_code == 201, response.text
    fresh = response.json()
    assert fresh["approved_by"] is None and fresh["signed_sha256"] is None
    assert (await send_action(h, fresh, "approval")).status_code == 200
    assert await saved_value(h, str(snapshot_id)) == legacy


@pytest.mark.parametrize("action", ["approval", "queue"])
@pytest.mark.parametrize("race", ["party", "access", "expiry"])
async def test_final_transaction_recheck_rejects_race_without_outbox(
    bridge_http, monkeypatch, action, race
):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])
    if race == "expiry":
        recheck = h.provider.source_resolver.recheck

        async def expire_during_recheck(*args):
            await recheck(*args)
            future = datetime.now(UTC) + timedelta(minutes=3)
            monkeypatch.setattr(
                "modules.eschf.bridge.datetime",
                SimpleNamespace(now=lambda tz: future, fromisoformat=datetime.fromisoformat),
            )

        monkeypatch.setattr(h.provider.source_resolver, "recheck", expire_during_recheck)
    else:

        async def mutate_during_native_io():
            async with h.pg.begin() as session:
                model, values = (
                    (Counterparty, {"revision": 2})
                    if race == "party"
                    else (User, {"status": "suspended"})
                )
                await session.execute(update(model).values(**values))

        h.pipeline.hook = mutate_during_native_io
    response = await send_action(h, data, action)
    assert response.status_code == (403 if race == "access" else 409), response.text
    if race != "access":
        assert response.json() == {"detail": "preview_stale"}
    assert await durable_state(h, data["id"]) == before


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_revalidation_native_io_holds_no_snapshot_or_source_locks(bridge_http, action):
    h = bridge_http
    data = await candidate(h, action)

    async def writer_probe():
        async def update_same_values():
            async with h.pg.begin() as session:
                await session.execute(update(DeliveryRecord).values(state=DeliveryRecord.state))
                await session.execute(update(Counterparty).values(revision=Counterparty.revision))

        await asyncio.wait_for(update_same_values(), 3)

    h.pipeline.hook = writer_probe
    response = await send_action(h, data, action)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_expiry_while_waiting_for_snapshot_lock_requires_refresh(
    bridge_http, monkeypatch, action
):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])
    final_read = asyncio.Event()
    reads = 0
    original_get = Repository.get

    async def observe_get(repository, *args):
        nonlocal reads
        reads += 1
        if reads == 2:
            final_read.set()
        return await original_get(repository, *args)

    monkeypatch.setattr(Repository, "get", observe_get)
    async with h.pg() as blocker:
        async with blocker.begin():

            async def hold_snapshot_during_native_io():
                await blocker.execute(
                    select(DeliveryRecord)
                    .where(DeliveryRecord.snapshot_id == UUID(data["id"]))
                    .with_for_update()
                )

            h.pipeline.hook = hold_snapshot_during_native_io
            task = asyncio.create_task(send_action(h, data, action))
            await asyncio.wait_for(final_read.wait(), 5)
            assert not task.done()
            future = datetime.now(UTC) + timedelta(minutes=3)
            monkeypatch.setattr(
                "modules.eschf.bridge.datetime",
                SimpleNamespace(now=lambda tz: future, fromisoformat=datetime.fromisoformat),
            )
        response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "preview_stale"}
    assert await durable_state(h, data["id"]) == before


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_superseded_during_native_recheck_cannot_receive_old_consent(bridge_http, action):
    h = bridge_http
    data = await candidate(h, action)
    value = await saved_value(h, data["id"])

    async def supersede_concurrently():
        async with h.pg.begin() as session:
            repo = Repository(session, core=h.core, event_bus=h.core.event_bus)
            await repo.supersede(h.actor, UUID(data["id"]), value)

    h.pipeline.hook = supersede_concurrently
    response = await send_action(h, data, action)
    assert response.status_code == 409 and response.json() == {"detail": "preview_stale"}
    assert await saved_value(h, data["id"]) == value
    async with h.pg() as session:
        facts = (await session.scalars(select(Decision))).all()
        assert [f.kind for f in facts] == ([] if action == "approval" else ["approved"])
        assert (await session.get(DeliveryRecord, UUID(data["id"]))).state == "superseded"


@pytest.mark.parametrize("action", ["approval", "queue"])
async def test_outbox_failure_rolls_back_after_successful_real_source_recheck(
    bridge_http, monkeypatch, action
):
    h = bridge_http
    data = await candidate(h, action)
    before = await durable_state(h, data["id"])

    def fail(*args, **kwargs):
        raise SQLAlchemyError("synthetic outbox failure")

    monkeypatch.setattr(h.core.event_bus, "emit", fail)
    response = await send_action(h, data, action)
    assert response.status_code == 503
    assert await durable_state(h, data["id"]) == before
