"""Real local PostgreSQL, synthetic adapters only; no native crypto/portal proof.

Requires the purpose-created eschf_g04_test database on loopback. Every test runs
the reserved migration body directly, without pretending the predecessor graph
is integrated. Only the eschf schema and synthetic public.outbox_event are reset.
"""

import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import CheckConstraint, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Until module registration is integrated, do not add its schema to the normal
# SQLite suite's global Base metadata merely by collecting this opt-in module.
if os.environ.get("ESCHF_TEST_DATABASE_URL"):
    from core.db.base import Base
    from core.domain.models import OutboxEvent
    from core.runtime.contract import Role
    from core.services.auth import CurrentUser
    from core.services.eventbus import OutboxEventBus
    from modules.eschf.lifecycle import PortalEvidence
    from modules.eschf.models import (
        TABLES,
        Attempt,
        Decision,
        DeliveryRecord,
        NumberReservation,
        Observation,
        SignedArtifact,
        Snapshot,
    )
    from modules.eschf.preparation import canonical, sha256
    from modules.eschf.repository import PERMISSIONS, Repository, SignedVerification, SnapshotInput
else:
    pytest.skip(
        "ESCHF_TEST_DATABASE_URL required for real PostgreSQL evidence", allow_module_level=True
    )

pytestmark = pytest.mark.integration
MIGRATION = Path(__file__).resolve().parents[2] / "migrations/versions/0121_eschf_durable_state.py"


def migrate(connection, direction):
    spec = importlib.util.spec_from_file_location("eschf_migration_0121", MIGRATION.resolve())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0121" and module.down_revision == "0119"
    with Operations.context(
        MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
    ):
        getattr(module, direction)()


@pytest_asyncio.fixture
async def pg():
    dsn = os.environ.get("ESCHF_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("ESCHF_TEST_DATABASE_URL required for real PostgreSQL evidence")
    url = make_url(dsn)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "eschf_g04_test"
        or url.port != 15439
        or url.username != "eschf_test"
        or bool(url.query)
    ):
        pytest.fail("requires the dedicated loopback eschf_g04_test database")
    engine = create_async_engine(url)
    async with engine.connect() as guard:
        assert await guard.scalar(text("SELECT current_database()")) == "eschf_g04_test"
        assert await guard.scalar(text("SELECT current_user")) == "eschf_test"
        if not await guard.scalar(text("SELECT pg_try_advisory_lock(904121)")):
            pytest.fail("another ESCHF test runner owns the dedicated database")
        await guard.commit()
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP SCHEMA IF EXISTS eschf CASCADE"))
                await connection.run_sync(lambda c: OutboxEvent.__table__.drop(c, checkfirst=True))
                await connection.run_sync(lambda c: OutboxEvent.__table__.create(c))
                await connection.run_sync(migrate, "upgrade")
            yield async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as connection:
                await connection.run_sync(migrate, "downgrade")
                await connection.run_sync(lambda c: OutboxEvent.__table__.drop(c))
        finally:
            await guard.execute(text("SELECT pg_advisory_unlock(904121)"))
            await guard.commit()
    await engine.dispose()


class SyntheticAdapter:
    """HMAC test fixture: NEVER evidence that the real portal ECP was verified."""

    adapter_id = "synthetic-hmac-fixture-v1"
    environment = "synthetic"
    _key = b"synthetic-unit-test-only"

    def wrap(self, payload):
        return canonical(
            {
                "payload": payload,
                "mac": hmac.new(self._key, canonical(payload), hashlib.sha256).hexdigest(),
            }
        )

    def unwrap(self, raw):
        obj = json.loads(raw)
        if not isinstance(obj, dict) or set(obj) != {"payload", "mac"}:
            raise ValueError("synthetic authenticated envelope required")
        expected = hmac.new(self._key, canonical(obj["payload"]), hashlib.sha256).hexdigest()
        if not isinstance(obj["mac"], str) or not hmac.compare_digest(obj["mac"], expected):
            raise ValueError("synthetic signature invalid")
        return obj["payload"]

    def signed(self, value):
        return self.wrap(
            {
                "number": value.number,
                "taxpayer_unp": value.taxpayer_unp,
                "xml": base64.b64encode(value.unsigned_xml).decode("ascii"),
            }
        )

    async def verify_signed(self, raw_signed, target):
        payload = self.unwrap(raw_signed)
        return SignedVerification(
            payload["number"],
            payload["taxpayer_unp"],
            sha256(base64.b64decode(payload["xml"], validate=True)),
            sha256(raw_signed),
            raw_signed,
        )

    def portal(self, value, *, code="COMPLETED", kind="status", hours=0, **changes):
        return self.wrap(
            {
                "number": value.number,
                "taxpayer_unp": value.taxpayer_unp,
                "signed_sha256": sha256(self.signed(value)),
                "kind": kind,
                "code": code,
                "since": (datetime(2026, 9, 9, tzinfo=UTC) + timedelta(hours=hours)).isoformat(),
                **changes,
            }
        )

    async def verify_portal(self, raw_evidence, target):
        payload = self.unwrap(raw_evidence)
        return PortalEvidence(
            payload["number"],
            payload["taxpayer_unp"],
            payload["signed_sha256"],
            payload["kind"],
            payload["code"],
            datetime.fromisoformat(payload["since"]),
            sha256(raw_evidence),
            True,
        )


@pytest.fixture
def adapter():
    return SyntheticAdapter()


@pytest.fixture
def core():
    return SimpleNamespace(
        roles=[
            Role("eschf-operator", tuple(p.code for p in PERMISSIONS)),
            Role("eschf-reader", ("eschf.read",)),
            Role("eschf-worker", ("eschf.worker",)),
        ]
    )


@pytest.fixture
def user():
    return CurrentUser("synthetic-accountant", ["eschf-operator"])


@pytest.fixture
def value():
    xml = b"<SyntheticFinalXML>not a native invoice</SyntheticFinalXML>"
    binding = {
        "source_document_id": 101,
        "source_document_version": 3,
        "source_content_sha256": "a" * 64,
        "source_snapshot_sha256": "b" * 64,
        "provider_identity": {"information_base_id": "synthetic", "native_uuid": str(uuid4())},
        "recipient_selection": {"legal_entity_id": 201, "legal_entity_revision": 7},
        "native_information_base_id": "synthetic",
        "native_metadata_object": "Synthetic.Invoice",
        "native_invoice_uuid": str(uuid4()),
        "native_version_evidence": {"synthetic": True},
        "basis_reference": "synthetic-source:101",
        "binding_evidence": {"synthetic": True},
        "prepared_xml_sha256": sha256(xml),
        "full_projection": {"synthetic": True},
    }
    return SnapshotInput(
        "100000000-2026-0000000001",
        "100000000",
        canonical(binding),
        xml,
        "synthetic-preparation-fixture-v1",
        "synthetic",
    )


def repo(session, core, adapter=None):
    return Repository(session, core=core, event_bus=OutboxEventBus(), adapter=adapter)


async def ready(pg, core, user, adapter, value):
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        snapshot_id = await repository.prepare(user, value)
        await repository.approve(
            user,
            snapshot_id,
            binding_sha256=sha256(value.binding_snapshot),
            unsigned_sha256=sha256(value.unsigned_xml),
        )
        await repository.attach_signed(user, snapshot_id, adapter.signed(value))
        await repository.enqueue(user, snapshot_id)
    return snapshot_id


async def attempted(pg, core, user, adapter, value):
    snapshot_id = await ready(pg, core, user, adapter, value)
    async with pg.begin() as session:
        assert await repo(session, core, adapter).claim_next(user) is not None
    return snapshot_id


async def count(pg, model):
    async with pg() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_migration_upgrade_downgrade_and_columns(pg):
    async with pg.kw["bind"].begin() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names(schema="eschf"))
        assert set(tables) == {table.name for table in TABLES}
        for table in TABLES:
            columns = await connection.run_sync(
                lambda c: inspect(c).get_columns(table.name, schema="eschf"),
            )
            assert {c["name"] for c in columns} == set(table.columns.keys())
            checks = await connection.run_sync(
                lambda c: inspect(c).get_check_constraints(table.name, schema="eschf"),
            )
            assert {c["name"] for c in checks} == {
                c.name for c in table.constraints if isinstance(c, CheckConstraint)
            }
        await connection.run_sync(migrate, "downgrade")
        assert not await connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='eschf')",
            )
        )
        await connection.run_sync(migrate, "upgrade")


async def test_prepare_rollback_has_no_snapshot_or_outbox(pg, core, user, value):
    async with pg() as session:
        await repo(session, core).prepare(user, value)
        await session.rollback()
    assert await count(pg, Snapshot) == await count(pg, OutboxEvent) == 0


async def test_two_workers_skip_locked_create_one_durable_attempt(pg, core, user, adapter, value):
    snapshot_id = await ready(pg, core, user, adapter, value)
    claimed, second_done = asyncio.Event(), asyncio.Event()

    async def first():
        async with pg.begin() as session:
            attempt = await repo(session, core).claim_next(
                CurrentUser("worker-1", ["eschf-worker"])
            )
            claimed.set()
            await asyncio.wait_for(second_done.wait(), 5)
            return attempt.claim_id

    async def second():
        await asyncio.wait_for(claimed.wait(), 5)
        async with pg.begin() as session:
            result = await repo(session, core).claim_next(CurrentUser("worker-2", ["eschf-worker"]))
        second_done.set()
        return result

    first_id, second_result = await asyncio.gather(first(), second())
    assert first_id and second_result is None
    assert await count(pg, Attempt) == 1
    async with pg.begin() as session:
        assert (await session.get(Attempt, snapshot_id)).worker_id == "worker-1"
        assert await repo(session, core).claim_next(user) is None
        events = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.event_type == "eschf.attempt_recorded",
            )
        )
        assert events == 1


async def test_definite_claim_rollback_restores_queue_and_removes_intent(
    pg, core, user, adapter, value
):
    snapshot_id = await ready(pg, core, user, adapter, value)
    async with pg() as session:
        await repo(session, core).claim_next(user)
        await session.rollback()
    assert await count(pg, Attempt) == 0
    async with pg.begin() as session:
        assert (await session.get(DeliveryRecord, snapshot_id)).state == "queued"
        assert await repo(session, core).claim_next(user) is not None
    assert await count(pg, Attempt) == 1


@pytest.mark.parametrize(
    "reason", ["timeout", "process_restart", "lost_response", "commit_unknown"]
)
async def test_restart_and_uncertainty_never_requeue(pg, core, user, adapter, value, reason):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    # A fresh engine/factory has no identity map or state from the claimant.
    engine = create_async_engine(pg.kw["bind"].url)
    restarted = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with restarted.begin() as session:
            repository = repo(session, core, adapter)
            await repository.mark_unknown(user, snapshot_id, reason=reason)
        async with restarted.begin() as session:
            repository = repo(session, core, adapter)
            row = await session.get(DeliveryRecord, snapshot_id)
            assert (row.state, row.unknown_reason) == ("delivery_unknown", reason)
            assert await repository.claim_next(user) is None
            with pytest.raises(ValueError, match="never-attempted"):
                await repository.enqueue(user, snapshot_id)
            assert (
                await repository.observe(user, snapshot_id, adapter.portal(value, code="NOT_FOUND"))
                == "reconciliation_required"
            )
            with pytest.raises(ValueError, match="never-attempted"):
                await repository.enqueue(user, snapshot_id)
    finally:
        await engine.dispose()
    assert await count(pg, Attempt) == 1


async def test_unique_attempt_survives_corrupt_projection(pg, core, user, adapter, value):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    async with pg.begin() as session:
        await session.execute(
            text("UPDATE eschf.delivery SET state='queued' WHERE snapshot_id=:id"),
            {"id": snapshot_id},
        )
    with pytest.raises(ValueError, match="projection integrity"):
        async with pg.begin() as session:
            await repo(session, core).claim_next(user)
    assert await count(pg, Attempt) == 1


@pytest.mark.parametrize("collision", ["number", "source"])
async def test_duplicate_original_identity_is_database_enforced(pg, core, user, value, collision):
    async with pg.begin() as session:
        await repo(session, core).prepare(user, value)
    binding = json.loads(value.binding_snapshot)
    if collision == "number":
        binding["source_document_id"] = 102
    else:
        binding["source_document_version"] += 1
        value = replace(value, number="100000000-2026-0000000002")
    changed = replace(value, binding_snapshot=canonical(binding))
    with pytest.raises(IntegrityError):
        async with pg.begin() as session:
            await repo(session, core).prepare(user, changed)
    assert await count(pg, Snapshot) == 1


@pytest.mark.parametrize(
    "table",
    [
        "original",
        "number_reservation",
        "snapshot",
        "decision",
        "signed_artifact",
        "attempt",
        "observation",
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_artifacts_immutable_even_through_direct_sql(
    pg, core, user, adapter, value, table, operation
):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    async with pg.begin() as session:
        await repo(session, core, adapter).observe(user, snapshot_id, adapter.portal(value))
    statements = {
        "UPDATE": f"UPDATE eschf.{table} SET "
        + {
            "original": "id=id",
            "number_reservation": "original_id=original_id",
            "snapshot": "number=number",
        }.get(table, "snapshot_id=snapshot_id"),
        "DELETE": f"DELETE FROM eschf.{table}",
        "TRUNCATE": f"TRUNCATE eschf.{table} CASCADE",
    }
    with pytest.raises(IntegrityError, match="immutable"):
        async with pg.begin() as session:
            await session.execute(text(statements[operation]))
    assert (
        await count(pg, Snapshot) == await count(pg, Attempt) == await count(pg, Observation) == 1
    )


async def test_stored_bytes_have_database_hash_constraint(pg, core, user, value):
    async with pg.begin() as session:
        snapshot_id = await repo(session, core).prepare(user, value)
    with pytest.raises(IntegrityError, match="artifact_hashes"):
        async with pg.begin() as session:
            snapshot = await session.get(Snapshot, snapshot_id)
            fields = {c.name: getattr(snapshot, c.name) for c in Snapshot.__table__.columns}
            fields.update(id=uuid4(), supersedes_id=snapshot_id, binding_snapshot=b"tampered bytes")
            await session.execute(Snapshot.__table__.insert().values(**fields))


async def test_approval_and_signed_relation_are_explicit(pg, core, user, adapter, value):
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        snapshot_id = await repository.prepare(user, value)
        with pytest.raises(ValueError, match="approved first"):
            await repository.attach_signed(user, snapshot_id, adapter.signed(value))
        with pytest.raises(ValueError, match="preview changed"):
            await repository.approve(
                user,
                snapshot_id,
                binding_sha256="c" * 64,
                unsigned_sha256=sha256(value.unsigned_xml),
            )
        await repository.approve(
            user,
            snapshot_id,
            binding_sha256=sha256(value.binding_snapshot),
            unsigned_sha256=sha256(value.unsigned_xml),
        )
        different = replace(value, unsigned_xml=b"different final XML")
        with pytest.raises(ValueError, match="approved final XML"):
            await repository.attach_signed(user, snapshot_id, adapter.signed(different))
        await repository.attach_signed(user, snapshot_id, adapter.signed(value))
        signed = await session.get(SignedArtifact, snapshot_id)
        assert signed.unsigned_sha256 == sha256(value.unsigned_xml)
        assert signed.signed_sha256 != signed.unsigned_sha256
        assert signed.signed_bytes == adapter.signed(value)


async def test_database_rejects_signed_or_attempt_hash_for_another_artifact(
    pg, core, user, adapter, value
):
    async with pg.begin() as session:
        repository = repo(session, core)
        snapshot_id = await repository.prepare(user, value)
        await repository.approve(
            user,
            snapshot_id,
            binding_sha256=sha256(value.binding_snapshot),
            unsigned_sha256=sha256(value.unsigned_xml),
        )
    raw_signed = adapter.signed(value)
    with pytest.raises(IntegrityError, match="unsigned_identity"):
        async with pg.begin() as session:
            session.add(
                SignedArtifact(
                    snapshot_id=snapshot_id,
                    signed_bytes=raw_signed,
                    signed_sha256=sha256(raw_signed),
                    unsigned_sha256="f" * 64,
                    verification_evidence=b"synthetic-proof",
                    verification_sha256=sha256(b"synthetic-proof"),
                    adapter_id=adapter.adapter_id,
                    created_by=user.username,
                )
            )
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        await repository.attach_signed(user, snapshot_id, raw_signed)
        await repository.enqueue(user, snapshot_id)
        original_id = (await session.get(Snapshot, snapshot_id)).original_id
    with pytest.raises(IntegrityError, match="signed_identity"):
        async with pg.begin() as session:
            session.add(
                Attempt(
                    snapshot_id=snapshot_id,
                    original_id=original_id,
                    signed_sha256="f" * 64,
                    worker_id="synthetic-invalid-worker",
                )
            )
    assert await count(pg, Attempt) == 0


async def test_authenticated_status_identity_history_replay_and_regression(
    pg, core, user, adapter, value
):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    receipt = adapter.portal(value, code="ACCEPTED", kind="receipt")
    completed = adapter.portal(value, hours=1)
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        assert await repository.observe(user, snapshot_id, receipt) == "portal_processing"
        assert await repository.observe(user, snapshot_id, completed) == "issued"
        assert await repository.observe(user, snapshot_id, receipt) == "issued"
        with pytest.raises(ValueError, match="stale"):
            await repository.observe(user, snapshot_id, adapter.portal(value, code="CANCELLED"))
        with pytest.raises(ValueError, match="regression"):
            await repository.observe(
                user, snapshot_id, adapter.portal(value, code="IN_PROGRESS", hours=2)
            )
        with pytest.raises(ValueError, match="unrelated"):
            await repository.observe(
                user, snapshot_id, adapter.portal(value, taxpayer_unp="200000000")
            )
    assert await count(pg, Observation) == 2
    async with pg() as session:
        rows = (
            (await session.execute(select(Observation).order_by(Observation.since))).scalars().all()
        )
        assert [r.raw_evidence for r in rows] == [receipt, completed]
        assert all(r.adapter_id == adapter.adapter_id for r in rows)


async def test_request_boolean_cannot_assert_portal_trust(pg, core, user, adapter, value):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        forged = canonical({"signature_verified": True, "code": "COMPLETED"})
        with pytest.raises(ValueError, match="envelope"):
            await repository.observe(user, snapshot_id, forged)
        forged = json.loads(adapter.portal(value))
        forged["payload"]["code"] = "COMPLETED_SIGNED"
        with pytest.raises(ValueError, match="signature"):
            await repository.observe(user, snapshot_id, canonical(forged))
        with pytest.raises(ValueError, match="adapter unavailable"):
            await repo(session, core).observe(user, snapshot_id, adapter.portal(value))
        adapter.environment = "native"
        with pytest.raises(ValueError, match="wrong environment"):
            await repository.observe(user, snapshot_id, adapter.portal(value))
        assert (await session.get(DeliveryRecord, snapshot_id)).state == "in_flight"
    assert await count(pg, Observation) == 0


@pytest.mark.parametrize(
    "actor",
    [
        CurrentUser("guest", ["Гость"]),
        CurrentUser("reader", ["eschf-reader"]),
        CurrentUser("restricted", ["director"], crm_restricted=True),
    ],
)
async def test_platform_rbac_enforced_before_mutation(pg, core, user, adapter, value, actor):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        operations = [
            lambda: repository.prepare(actor, value),
            lambda: repository.supersede(actor, snapshot_id, value),
            lambda: repository.approve(actor, snapshot_id, binding_sha256="", unsigned_sha256=""),
            lambda: repository.attach_signed(actor, snapshot_id, b"signed"),
            lambda: repository.enqueue(actor, snapshot_id),
            lambda: repository.claim_next(actor),
            lambda: repository.mark_unknown(actor, snapshot_id, reason="timeout"),
            lambda: repository.observe(actor, snapshot_id, adapter.portal(value)),
            lambda: repository.recover_projection(actor, snapshot_id),
        ]
        for operation in operations:
            with pytest.raises(PermissionError):
                await operation()
        if actor.roles == ["eschf-reader"]:
            assert (await repository.get(actor, snapshot_id))[0].unsigned_xml == value.unsigned_xml
        else:
            with pytest.raises(PermissionError):
                await repository.get(actor, snapshot_id)
        assert (await session.get(DeliveryRecord, snapshot_id)).state == "in_flight"


async def test_status_and_outbox_rollback_together(pg, core, user, adapter, value):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    old_events = await count(pg, OutboxEvent)
    async with pg() as session:
        await repo(session, core, adapter).observe(user, snapshot_id, adapter.portal(value))
        await session.rollback()
    async with pg() as session:
        assert (await session.get(DeliveryRecord, snapshot_id)).state == "in_flight"
    assert await count(pg, Observation) == 0
    assert await count(pg, OutboxEvent) == old_events


def refreshed(value, *, new_number=False):
    xml = b"<SyntheticFinalXML>refreshed native projection</SyntheticFinalXML>"
    binding = json.loads(value.binding_snapshot)
    binding.update(
        source_document_version=4,
        source_content_sha256="d" * 64,
        source_snapshot_sha256="e" * 64,
        prepared_xml_sha256=sha256(xml),
        native_version_evidence={"synthetic": True, "revision": 2},
    )
    return replace(
        value,
        binding_snapshot=canonical(binding),
        unsigned_xml=xml,
        number="100000000-2026-0000000002" if new_number else value.number,
    )


@pytest.mark.parametrize("stage", ["prepared", "approved", "signed", "queued"])
@pytest.mark.parametrize("new_number", [False, True])
async def test_pre_attempt_refresh_keeps_history_and_requires_fresh_approval(
    pg,
    core,
    user,
    adapter,
    value,
    stage,
    new_number,
):
    fresh = refreshed(value, new_number=new_number)
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        old_id = await repository.prepare(user, value)
        if stage != "prepared":
            await repository.approve(
                user,
                old_id,
                binding_sha256=sha256(value.binding_snapshot),
                unsigned_sha256=sha256(value.unsigned_xml),
            )
        if stage in {"signed", "queued"}:
            await repository.attach_signed(user, old_id, adapter.signed(value))
        if stage == "queued":
            await repository.enqueue(user, old_id)
        fresh_id = await repository.supersede(user, old_id, fresh)
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        old, old_row = await repository.get(user, old_id)
        current, current_row = await repository.get(user, fresh_id)
        assert old_row.state == "superseded" and old.unsigned_xml == value.unsigned_xml
        assert current.original_id == old.original_id and current.supersedes_id == old_id
        assert current.number == fresh.number and current.unsigned_xml == fresh.unsigned_xml
        assert current_row.state == "prepared" and current_row.approved_by is None
        assert await session.get(SignedArtifact, fresh_id) is None
        with pytest.raises(ValueError, match="never-attempted"):
            await repository.enqueue(user, fresh_id)
        with pytest.raises(ValueError, match="never-attempted"):
            await repository.enqueue(user, old_id)
        with pytest.raises(ValueError, match="latest"):
            await repository.supersede(user, old_id, value)
        await repository.approve(
            user,
            fresh_id,
            binding_sha256=sha256(fresh.binding_snapshot),
            unsigned_sha256=sha256(fresh.unsigned_xml),
        )
        await repository.attach_signed(user, fresh_id, adapter.signed(fresh))
        await repository.enqueue(user, fresh_id)
        attempt = await repository.claim_next(user)
        assert attempt.snapshot_id == fresh_id and attempt.original_id == old.original_id
    assert await count(pg, Snapshot) == 2
    assert await count(pg, Attempt) == 1
    assert await count(pg, NumberReservation) == (2 if new_number else 1)


async def test_after_attempt_no_refresh_new_original_or_sql_revision_bypass(
    pg,
    core,
    user,
    adapter,
    value,
):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    fresh = refreshed(value, new_number=True)
    async with pg.begin() as session:
        with pytest.raises(ValueError, match="attempt exists"):
            await repo(session, core).supersede(user, snapshot_id, fresh)
    with pytest.raises(IntegrityError):
        async with pg.begin() as session:
            await repo(session, core).prepare(user, fresh)
    with pytest.raises(IntegrityError, match="attempted original cannot be refreshed"):
        async with pg.begin() as session:
            old = await session.get(Snapshot, snapshot_id)
            fields = {c.name: getattr(old, c.name) for c in Snapshot.__table__.columns}
            fields.update(id=uuid4(), supersedes_id=snapshot_id)
            await session.execute(Snapshot.__table__.insert().values(**fields))
    assert await count(pg, Snapshot) == await count(pg, Attempt) == 1


async def test_superseded_number_cannot_be_reused_by_another_original(
    pg,
    core,
    user,
    value,
):
    async with pg.begin() as session:
        repository = repo(session, core)
        old_id = await repository.prepare(user, value)
        await repository.supersede(user, old_id, refreshed(value, new_number=True))
    binding = json.loads(value.binding_snapshot)
    binding["source_document_id"] = 202
    with pytest.raises(IntegrityError):
        async with pg.begin() as session:
            await repo(session, core).prepare(
                user, replace(value, binding_snapshot=canonical(binding))
            )
    assert await count(pg, NumberReservation) == 2


async def test_refresh_rolls_back_with_history_and_outbox(pg, core, user, value):
    async with pg.begin() as session:
        old_id = await repo(session, core).prepare(user, value)
    old_events = await count(pg, OutboxEvent)
    async with pg() as session:
        await repo(session, core).supersede(user, old_id, refreshed(value, new_number=True))
        await session.rollback()
    async with pg.begin() as session:
        assert (await repo(session, core).get(user, old_id))[1].state == "prepared"
    assert await count(pg, Snapshot) == await count(pg, NumberReservation) == 1
    assert await count(pg, OutboxEvent) == old_events


async def test_refresh_holds_queue_lock_against_concurrent_worker(pg, core, user, adapter, value):
    old_id = await ready(pg, core, user, adapter, value)
    async with pg.begin() as refresher:
        fresh_id = await repo(refresher, core).supersede(user, old_id, refreshed(value))
        async with pg.begin() as worker:
            assert await repo(worker, core).claim_next(user) is None
    async with pg.begin() as session:
        assert (await repo(session, core).get(user, fresh_id))[1].state == "prepared"
        assert await repo(session, core).claim_next(user) is None
    assert await count(pg, Attempt) == 0


async def test_committing_attempt_wins_over_concurrent_refresh(pg, core, user, adapter, value):
    old_id = await ready(pg, core, user, adapter, value)
    waiting = asyncio.Event()

    async def refresh():
        async with pg.begin() as session:
            waiting.set()
            with pytest.raises(ValueError, match="attempt exists"):
                await repo(session, core).supersede(user, old_id, refreshed(value, new_number=True))

    async with pg.begin() as session:
        assert await repo(session, core).claim_next(user) is not None
        task = asyncio.create_task(refresh())
        await asyncio.wait_for(waiting.wait(), 5)
    await asyncio.wait_for(task, 5)
    assert await count(pg, Snapshot) == await count(pg, Attempt) == 1


async def test_sql_cannot_create_issued_without_document_evidence(pg, core, user, value):
    async with pg.begin() as session:
        snapshot_id = await repo(session, core).prepare(user, value)
    with pytest.raises(IntegrityError, match="portal_evidence"):
        async with pg.begin() as session:
            await session.execute(
                text("UPDATE eschf.delivery SET state='issued' WHERE snapshot_id=:id"),
                {"id": snapshot_id},
            )
    async with pg.begin() as session:
        assert (await repo(session, core).get(user, snapshot_id))[1].state == "prepared"
    assert await count(pg, Attempt) == await count(pg, Observation) == 0


async def test_sql_forged_approval_is_not_authority_and_recovers_to_prepared(
    pg,
    core,
    user,
    adapter,
    value,
):
    async with pg.begin() as session:
        snapshot_id = await repo(session, core).prepare(user, value)
    async with pg.begin() as session:
        await session.execute(
            text("""
            UPDATE eschf.delivery SET state='approved', approved_by='forged', approved_at=now(),
            approved_binding_sha256=:binding, approved_unsigned_sha256=:unsigned
            WHERE snapshot_id=:id
        """),
            {
                "id": snapshot_id,
                "binding": sha256(value.binding_snapshot),
                "unsigned": sha256(value.unsigned_xml),
            },
        )
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        with pytest.raises(ValueError, match="projection integrity"):
            await repository.get(user, snapshot_id)
        with pytest.raises(ValueError, match="projection integrity"):
            await repository.attach_signed(user, snapshot_id, adapter.signed(value))
        assert await repository.recover_projection(user, snapshot_id) == "prepared"
        assert (await repository.get(user, snapshot_id))[1].approved_by is None
    with pytest.raises(IntegrityError, match="invalid approval"):
        async with pg.begin() as session:
            session.add(
                Decision(
                    snapshot_id=snapshot_id,
                    kind="approved",
                    actor="forged",
                    binding_sha256="f" * 64,
                    unsigned_sha256="f" * 64,
                )
            )
    assert await count(pg, Decision) == await count(pg, SignedArtifact) == 0


@pytest.mark.parametrize("tamper", ["state", "evidence_sha256", "approved_by"])
async def test_projection_recovers_portal_truth_from_immutable_observation(
    pg,
    core,
    user,
    adapter,
    value,
    tamper,
):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    raw = adapter.portal(value)
    async with pg.begin() as session:
        await repo(session, core, adapter).observe(user, snapshot_id, raw)
    async with pg.begin() as session:
        row = await session.get(DeliveryRecord, snapshot_id)
        setattr(
            row,
            tamper,
            {"state": "portal_error", "evidence_sha256": "f" * 64, "approved_by": "forged"}[tamper],
        )
    async with pg.begin() as session:
        repository = repo(session, core, adapter)
        with pytest.raises(ValueError, match="projection integrity"):
            await repository.get(user, snapshot_id)
        assert await repository.recover_projection(user, snapshot_id) == "issued"
        _, row = await repository.get(user, snapshot_id)
        assert row.evidence_sha256 == sha256(raw) and row.approved_by == user.username
        assert (await session.get(Observation, row.observation_id)).raw_evidence == raw
    assert await count(pg, Observation) == await count(pg, Attempt) == 1


async def test_recovery_never_turns_unknown_attempt_into_queue(pg, core, user, adapter, value):
    snapshot_id = await attempted(pg, core, user, adapter, value)
    async with pg.begin() as session:
        await repo(session, core).mark_unknown(user, snapshot_id, reason="lost_response")
    async with pg.begin() as session:
        await session.execute(
            text(
                "UPDATE eschf.delivery SET state='queued', unknown_reason=NULL WHERE snapshot_id=:id"
            ),
            {"id": snapshot_id},
        )
    async with pg.begin() as session:
        repository = repo(session, core)
        with pytest.raises(ValueError, match="projection integrity"):
            await repository.claim_next(user)
        assert await repository.recover_projection(user, snapshot_id) == "delivery_unknown"
        assert (await repository.get(user, snapshot_id))[1].unknown_reason == "lost_response"
        assert await repository.claim_next(user) is None
        with pytest.raises(ValueError):
            await repository.enqueue(user, snapshot_id)
    assert await count(pg, Attempt) == 1


async def test_foreign_observation_cannot_be_bound_to_another_invoice(
    pg, core, user, adapter, value
):
    first = await attempted(pg, core, user, adapter, value)
    other_binding = json.loads(value.binding_snapshot)
    other_binding["source_document_id"] = 202
    other_value = replace(
        value, number="100000000-2026-0000000002", binding_snapshot=canonical(other_binding)
    )
    second = await attempted(pg, core, user, adapter, other_value)
    async with pg.begin() as session:
        await repo(session, core, adapter).observe(user, first, adapter.portal(value))
        observation_id = (await session.get(DeliveryRecord, first)).observation_id
    with pytest.raises(IntegrityError, match="observation_identity"):
        async with pg.begin() as session:
            await session.execute(
                text(
                    "UPDATE eschf.delivery SET state='issued', observation_id=:obs WHERE snapshot_id=:id"
                ),
                {"id": second, "obs": observation_id},
            )
    async with pg.begin() as session:
        assert (await repo(session, core).get(user, second))[1].state == "in_flight"
