"""Synthetic held-document trust boundary, transaction and replay regressions."""

import json
import runpy
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from core.db.base import Base
from core.domain.document_source import DocumentSourceRevision as Revision
from core.domain.models import (
    CatalogSourceIdentity,
    CatalogSourceRevision,
    Counterparty,
    CounterpartyAlias,
    Sku,
)
from core.domain.reference import NomenclatureCategory
from core.services import native_document_stage as staging
from core.services.native_catalog_import import digest
from core.services.native_document_stage import (
    BOUND,
    REQUIRED_HOLDS,
    SHARED,
    DocumentStageConflict,
    stage_documents,
)

ENTITY = "Document_SyntheticReceipt"
SHARED_ENTITY = "Document_SyntheticShared"
ORG = "11111111-1111-1111-1111-111111111111"
START, END = datetime(2026, 7, 1), datetime(2026, 9, 1)
SCOPES = {ENTITY: BOUND, SHARED_ENTITY: SHARED}


def row(number=1, *, version="v1", entity=ENTITY, holds=None, raw=None, **changes):
    values = dict(
        Ref_Key=f"00000000-0000-0000-0000-{number:012x}",
        DataVersion=version,
        Date="2026-07-15T12:00:00",
        Posted=True,
        DeletionMark=False,
    )
    if entity == ENTITY:
        values["Организация_Key"] = ORG
    values.update(changes)
    raw = json.dumps(values, ensure_ascii=False) if raw is None else raw
    scope = SCOPES[entity]
    holds = list(sorted(REQUIRED_HOLDS)) if holds is None else list(holds)
    if scope == SHARED and "ORG_UNEXPOSED_NOT_POSTABLE" not in holds:
        holds.append("ORG_UNEXPOSED_NOT_POSTABLE")
    return dict(
        entity=entity,
        source_guid=values["Ref_Key"],
        data_version=version,
        source_text=raw,
        source_sha256=digest(raw),
        source_scope=scope,
        status="HELD_SOURCE_ONLY",
        holds=holds,
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    # SQLite needs explicit BEGIN so savepoint release cannot commit caller work.
    @event.listens_for(engine, "connect")
    def connect(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    tables = [
        Counterparty.__table__,
        CounterpartyAlias.__table__,
        NomenclatureCategory.__table__,
        Sku.__table__,
        CatalogSourceIdentity.__table__,
        CatalogSourceRevision.__table__,
        Revision.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session
    engine.dispose()


def load(db, records, **kwargs):
    namespace = kwargs.pop("namespace", "synthetic:documents")
    options = dict(
        actor="synthetic-test",
        entity_scopes=SCOPES,
        organization_sha256=digest(ORG),
        period_start=START,
        period_end=END,
    )
    options.update(kwargs)
    return stage_documents(db, namespace, records, **options)


def count(db):
    return db.scalar(select(func.count()).select_from(Revision))


def test_exact_text_replay_and_versioned_correction(db):
    original = row()
    exact = original["source_text"][:-1] + ', "Строки": [{"Quantity": 0.100000000000000000001}]}'
    original.update(source_text=exact, source_sha256=digest(exact))
    assert load(db, [original])["created"] == 1
    db.commit()
    assert load(db, [original])["replayed"] == 1
    db.commit()
    corrected = row(version="v2", Date="2026-08-31T23:59:59")
    key = (ENTITY, original["source_guid"])
    assert (
        load(db, [corrected], expected_previous={key: original["source_sha256"]})["corrected"] == 1
    )
    revisions = list(db.scalars(select(Revision).order_by(Revision.revision_no)))
    assert len(revisions) == 2 and revisions[0].source_text == exact
    assert revisions[1].previous_sha == digest(exact)
    assert load(db, [corrected])["replayed"] == 1 and count(db) == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"Date": "2026-09-01T00:00:00"}, "SOURCE_PERIOD"),
        ({"Date": "2026-06-30T23:59:59"}, "SOURCE_PERIOD"),
        ({"Date": "2026-07-01T00:00:00+03:00"}, "SOURCE_PERIOD"),
        ({"Date": "2026-02-30T00:00:00"}, "SOURCE_PERIOD"),
        ({"Posted": "true"}, "SOURCE_STATE"),
        ({"DeletionMark": 0}, "SOURCE_STATE"),
        ({"Организация_Key": "22222222-2222-2222-2222-222222222222"}, "SOURCE_ORGANIZATION"),
        ({"Ref_Key": "00000000-0000-0000-0000-000000000000"}, "GUID_ZERO"),
        ({"DataVersion": ""}, "SOURCE_DATA_VERSION"),
    ],
)
def test_invalid_source_has_no_writes(db, change, code):
    with pytest.raises(DocumentStageConflict, match=code):
        load(db, [row(**change)])
    assert count(db) == 0


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("source_sha256", "0" * 64, "SOURCE_SEAL"),
        ("source_guid", "bad", "SOURCE_IDENTITY"),
        ("data_version", "other", "SOURCE_DATA_VERSION"),
        ("status", "POSTED", "SOURCE_SCOPE_STATUS"),
        ("source_scope", SHARED, "SOURCE_SCOPE_STATUS"),
        ("holds", [], "SOURCE_HOLDS"),
    ],
)
def test_envelope_mismatch_is_rejected(db, field, value, code):
    incoming = row()
    incoming[field] = value
    with pytest.raises(DocumentStageConflict, match=code):
        load(db, [incoming])
    assert count(db) == 0


@pytest.mark.parametrize(
    "addition,code",
    [
        (', "Posted": true', "DUPLICATE_JSON_KEY"),
        (', "Nested": {"x":1,"x":2}', "DUPLICATE_JSON_KEY"),
        (', "Amount": NaN', "JSON_NONFINITE"),
    ],
)
def test_ambiguous_or_nonfinite_json_rejected(db, addition, code):
    incoming = row()
    raw = incoming["source_text"][:-1] + addition + "}"
    incoming.update(source_text=raw, source_sha256=digest(raw))
    with pytest.raises(DocumentStageConflict, match=code):
        load(db, [incoming])
    assert count(db) == 0


def test_duplicate_guid_and_reused_version_or_stale_rewind(db):
    original = row()
    key = (ENTITY, original["source_guid"])
    with pytest.raises(DocumentStageConflict, match="DUPLICATE_SOURCE_GUID"):
        load(db, [original, original])
    load(db, [original])
    db.commit()
    with pytest.raises(DocumentStageConflict, match="DATA_VERSION_REUSED"):
        load(
            db,
            [row(Date="2026-07-16T12:00:00")],
            expected_previous={key: digest(original["source_text"])},
        )
    corrected = row(version="v2")
    with pytest.raises(DocumentStageConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [corrected])
    load(db, [corrected], expected_previous={key: original["source_sha256"]})
    db.commit()
    with pytest.raises(DocumentStageConflict, match="DATA_VERSION_REUSED"):
        load(db, [original], expected_previous={key: corrected["source_sha256"]})
    assert count(db) == 2


def test_batch_failure_and_caller_rollback(db):
    original = row(2)
    load(db, [original])
    db.commit()
    with pytest.raises(DocumentStageConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [row(1), row(2, version="v2")])
    assert count(db) == 1
    load(db, [row(3)])
    db.rollback()
    assert count(db) == 1


def test_replay_cannot_change_holds_and_correction_cannot_drop_hold(db):
    original = row(holds=sorted(REQUIRED_HOLDS) + ["EXTRA_REVIEW_REQUIRED"])
    load(db, [original])
    db.commit()
    with pytest.raises(DocumentStageConflict, match="REPLAY_POLICY_CHANGED"):
        load(db, [row()])
    with pytest.raises(DocumentStageConflict, match="SOURCE_HOLDS_WEAKENED"):
        load(
            db,
            [row(version="v2")],
            expected_previous={(ENTITY, original["source_guid"]): original["source_sha256"]},
        )
    assert count(db) == 1


@pytest.mark.parametrize(
    "context",
    [
        {"period_end": datetime(2026, 10, 1)},
        {"entity_scopes": {**SCOPES, "Document_Another": BOUND}},
        {"organization_sha256": "0" * 64},
    ],
)
def test_namespace_context_immutable_including_shared_replay(db, context):
    incoming = row(entity=SHARED_ENTITY)
    load(db, [incoming])
    db.commit()
    with pytest.raises(DocumentStageConflict, match="NAMESPACE_CONTEXT_CHANGED"):
        load(db, [incoming], **context)
    assert count(db) == 1


def test_deleted_and_unposted_remain_held_without_native_writes(db):
    load(db, [row(1, Posted=False), row(2, DeletionMark=True), row(3, entity=SHARED_ENTITY)])
    assert count(db) == 3
    for model in (
        Counterparty,
        CounterpartyAlias,
        Sku,
        NomenclatureCategory,
        CatalogSourceIdentity,
        CatalogSourceRevision,
    ):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    saved = list(db.scalars(select(Revision)))
    assert all(REQUIRED_HOLDS <= set(v.holds) for v in saved)
    assert "ORG_UNEXPOSED_NOT_POSTABLE" in saved[-1].holds


def test_dirty_session_and_invalid_context_refused(db):
    load(db, [row()])
    db.commit()
    db.scalar(select(Revision)).actor = "pending-change"
    with pytest.raises(DocumentStageConflict, match="CLEAN_SESSION_REQUIRED"):
        load(db, [row(2)])
    db.rollback()
    with pytest.raises(DocumentStageConflict, match="IMPORT_CONTEXT"):
        load(db, [row(2)], period_start=START.replace(tzinfo=timezone.utc))
    with pytest.raises(DocumentStageConflict, match="IMPORT_SCOPE"):
        load(db, [row(2)], actor="\ud800")


def test_database_error_is_safe_and_batch_rolled_back(db):
    db.execute(
        text(
            "CREATE TRIGGER refused BEFORE INSERT ON document_source_revision BEGIN SELECT RAISE(FAIL,'private-source-name'); END"
        )
    )
    with pytest.raises(DocumentStageConflict) as caught:
        load(db, [row()])
    assert str(caught.value) == "DATABASE_STAGE_REJECTED" and count(db) == 0


def test_same_guid_separated_by_entity_and_namespace(db):
    original = row()
    load(db, [original, row(entity=SHARED_ENTITY)])
    db.commit()
    load(db, [original], namespace="synthetic:second-context", period_end=datetime(2026, 8, 1))
    db.commit()
    assert count(db) == 3
    assert load(db, [original, row(entity=SHARED_ENTITY)])["replayed"] == 2
    assert (
        load(db, [original], namespace="synthetic:second-context", period_end=datetime(2026, 8, 1))[
            "replayed"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "kind", ["row_bytes", "batch_bytes", "row_count", "scope_count", "scope_bytes"]
)
def test_resource_limits_reject_before_database_queries(db, monkeypatch, kind):
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2]))
    records, options = [row()], {}
    code = "BATCH_SIZE"
    if kind == "row_bytes":
        monkeypatch.setattr(staging, "MAX_ROW_BYTES", 256)
        records = [row(Padding="x" * 300)]
        code = "SOURCE_ROW_SIZE"
    elif kind == "batch_bytes":
        monkeypatch.setattr(staging, "MAX_BATCH_BYTES", 256)
        records = [row(1), row(2)]
        code = "BATCH_BYTES"
    elif kind == "row_count":
        records *= 4001
    elif kind == "scope_count":
        options["entity_scopes"] = {"Document_" + str(i): BOUND for i in range(129)}
        code = "IMPORT_CONTEXT"
    else:
        options["entity_scopes"] = {"Document_" + str(i) + "я" * 112: BOUND for i in range(128)}
        code = "IMPORT_CONTEXT_SIZE"
    with pytest.raises(DocumentStageConflict, match=code):
        load(db, records, **options)
    assert statements == []
    assert count(db) == 0


def test_alembic_discovery_and_one_linear_head():
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0200"]
    assert "crm_rel_001_native_docs_01" in {revision.revision for revision in script.walk_revisions()}
    with (
        EnvironmentContext(config, script),
        patch(
            "config.settings.get_settings",
            return_value=SimpleNamespace(
                database_url="postgresql+psycopg://synthetic@127.0.0.1:1/synthetic"
            ),
        ),
        patch("alembic.context.is_offline_mode", return_value=True),
        patch("alembic.context.configure") as configure,
        patch("alembic.context.begin_transaction", return_value=nullcontext()),
        patch("alembic.context.run_migrations"),
    ):
        loaded = runpy.run_path(str(Path("migrations/env.py")))
    assert loaded["target_metadata"].tables["document_source_revision"] is Revision.__table__
    assert (
        configure.call_args.kwargs["target_metadata"].tables["document_source_revision"]
        is Revision.__table__
    )
