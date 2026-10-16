"""Standalone synthetic PostgreSQL proof; explicit owned-cluster gate, no skips.

Run only with the existing dedicated G03 role/admin URL and G22 acceptance flag.
There are no protected packet reads, production defaults or business postings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crm_rel_001_migration_proof as migration
from psycopg import sql
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.domain.document_source import DocumentSourceRevision as Revision
from core.domain.models import CatalogSourceRevision
from core.services.native_catalog_import import NOMENCLATURE, SourceRow, digest, import_catalog
from core.services.native_document_stage import (
    BOUND,
    REQUIRED_HOLDS,
    SHARED,
    DocumentStageConflict,
    stage_documents,
)

HEAD = "crm_rel_001_native_docs_01"
PREVIOUS = "crm_rel_001_native_catalog_01"
ENTITY = "Document_СинтетическоеПоступление"
SHARED_ENTITY = "Document_СинтетическаяОбщаяЗапись"
SCOPES = {ENTITY: BOUND, SHARED_ENTITY: SHARED}
ORG = "11111111-1111-1111-1111-111111111111"
START, END = datetime(2026, 7, 1), datetime(2026, 9, 1)


def row(number, *, version="v1", shared=False, holds=None, **changes):
    entity = SHARED_ENTITY if shared else ENTITY
    raw = dict(
        Ref_Key=str(UUID(int=number)),
        DataVersion=version,
        Date="2026-07-15T12:00:00",
        Posted=True,
        DeletionMark=False,
    )
    if not shared:
        raw["Организация_Key"] = ORG
    raw.update(changes)
    source = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    kept = sorted(REQUIRED_HOLDS) if holds is None else list(holds)
    if shared:
        kept.append("ORG_UNEXPOSED_NOT_POSTABLE")
    return dict(
        entity=entity,
        source_guid=raw["Ref_Key"],
        data_version=version,
        source_text=source,
        source_sha256=digest(source),
        source_scope=SCOPES[entity],
        status="HELD_SOURCE_ONLY",
        holds=kept,
    )


def load(session, rows, namespace="synthetic:g22", **options):
    args = dict(
        actor="isolated-g22-proof",
        entity_scopes=SCOPES,
        organization_sha256=digest(ORG),
        period_start=START,
        period_end=END,
    )
    args.update(options)
    return stage_documents(session, namespace, rows, **args)


def values(incoming, namespace, *, revision=1, previous=None, period_end=END):
    """Build independent SQL input without the staging parser or its context helper."""
    scopes = json.dumps(SCOPES, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return dict(
        namespace=namespace,
        entity=incoming["entity"],
        source_guid=incoming["source_guid"],
        source_scope=incoming["source_scope"],
        revision_no=revision,
        source_sha=incoming["source_sha256"],
        data_version=incoming["data_version"],
        previous_sha=previous,
        source_text=incoming["source_text"],
        holds=json.dumps(incoming["holds"]),
        actor="isolated-direct-sql-proof",
        organization_sha256=digest(ORG),
        period_start=START,
        period_end=period_end,
        entity_scopes_sha256=digest(scopes),
        entity_scopes_text=scopes,
    )


def insert(connection, data):
    fields = list(data)
    columns = ",".join(fields)
    parameters = ",".join("CAST(:holds AS json)" if k == "holds" else ":" + k for k in fields)
    connection.execute(
        text(f"INSERT INTO document_source_revision ({columns}) VALUES ({parameters})"), data
    )


def refused(engine, action, expected):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            action(connection)
        except DBAPIError as error:
            transaction.rollback()
            assert getattr(error.orig, "sqlstate", None) == "P0001", "G22_UNEXPECTED_SQLSTATE"
            assert (
                getattr(getattr(error.orig, "diag", None), "message_primary", None) == expected
            ), "G22_UNEXPECTED_GUARD"
            return
        transaction.rollback()
        raise AssertionError("G22_GUARD_ACCEPTED_INVALID_SQL")


def count(session, namespace=None):
    query = select(func.count()).select_from(Revision)
    if namespace is not None:
        query = query.where(Revision.namespace == namespace)
    return session.scalar(query)


def snapshot(engine):
    """Only synthetic owned database rows, never a live or protected dump."""
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') AND tablename<>'document_source_revision' ORDER BY schemaname,tablename"
            )
        ).all()
        return {
            (schema, table): connection.exec_driver_sql(
                sql.SQL("SELECT count(*) FROM {}.{}")
                .format(sql.Identifier(schema), sql.Identifier(table))
                .as_string()
            ).scalar()
            for schema, table in tables
        }


def proof(engine):
    cases = []
    columns = {v["name"] for v in inspect(engine).get_columns("document_source_revision")}
    assert columns == set(Revision.__table__.columns.keys()), "G22_ORM_COLUMNS_DIFFER"
    checks = {v["name"] for v in inspect(engine).get_check_constraints("document_source_revision")}
    assert {
        v.name for v in Revision.__table__.constraints if v.__class__.__name__ == "CheckConstraint"
    } == checks
    cases.append("migrated_orm_columns_and_checks")
    before = snapshot(engine)
    original = row(1)
    exact = original["source_text"][:-1] + ',"Строки":[{"Amount":0.100000000000000000001}]}'
    original.update(source_text=exact, source_sha256=digest(exact))
    key = (ENTITY, original["source_guid"])
    with Session(engine) as session:
        assert load(session, [original])["created"] == 1
        session.commit()
        assert load(session, [original])["replayed"] == 1
        session.commit()
        corrected = row(1, version="v2", Date="2026-08-31T23:59:59")
        assert load(session, [corrected], expected_previous={key: digest(exact)})["corrected"] == 1
        session.commit()
        assert load(session, [corrected])["replayed"] == 1
        session.commit()
        revisions = list(
            session.scalars(
                select(Revision)
                .where(Revision.namespace == "synthetic:g22")
                .order_by(Revision.revision_no)
            )
        )
        assert len(revisions) == 2 and revisions[0].source_text == exact
        assert revisions[1].previous_sha == digest(exact)
        try:
            load(session, [original], expected_previous={key: corrected["source_sha256"]})
        except DocumentStageConflict as error:
            assert str(error) == "DATA_VERSION_REUSED"
        else:
            raise AssertionError("G22_STALE_REWIND_ACCEPTED")
        try:
            load(session, [row(2), row(1, version="v3")])
        except DocumentStageConflict as error:
            assert str(error) == "EXPECTED_PREVIOUS_SHA"
        else:
            raise AssertionError("G22_BATCH_FAILURE_ACCEPTED")
        assert count(session, "synthetic:g22") == 2
        load(session, [row(3)])
        session.rollback()
        assert count(session, "synthetic:g22") == 2
        load(session, [row(4, shared=True), row(5, Posted=False), row(6, DeletionMark=True)])
        session.commit()
        assert count(session, "synthetic:g22") == 5
        assert all(REQUIRED_HOLDS <= set(v.holds) for v in session.scalars(select(Revision)))
    cases.extend(
        [
            "exact_numeric_unicode_text_and_replay",
            "version_cas_and_stale_rewind",
            "atomic_failure_and_caller_rollback",
            "shared_unposted_deleted_are_held",
        ]
    )

    # Namespace lock must serialize not-yet-existing identities.
    barrier = Barrier(2)

    def concurrent_replay():
        with Session(engine) as session:
            barrier.wait(timeout=15)
            result = load(session, [row(70)], namespace="synthetic:concurrent-replay")
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            f.result(timeout=45)
            for f in [pool.submit(concurrent_replay), pool.submit(concurrent_replay)]
        ]
    assert sorted(v["created"] for v in results) == [0, 1]
    assert sorted(v["replayed"] for v in results) == [0, 1]
    cases.append("concurrent_first_identity_has_one_revision")

    # Direct SQL cannot mix contexts on two different first identities.
    barrier = Barrier(2)

    def different_first(number, end):
        with engine.begin() as connection:
            barrier.wait(timeout=15)
            try:
                insert(connection, values(row(number), "synthetic:context-race", period_end=end))
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "P0001"
                assert error.orig.diag.message_primary == "DOCUMENT_NAMESPACE_CONTEXT"
                return "REFUSED"
            return "INSERTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            f.result(timeout=45)
            for f in [
                pool.submit(different_first, 80, END),
                pool.submit(different_first, 81, datetime(2026, 10, 1)),
            ]
        ]
    assert sorted(results) == ["INSERTED", "REFUSED"]
    with Session(engine) as session:
        assert count(session, "synthetic:context-race") == 1
    cases.append("direct_sql_different_first_contexts_serialized")

    for isolation in ("REPEATABLE READ", "SERIALIZABLE"):

        def non_rc(connection):
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL " + isolation)
            insert(connection, values(row(90), "synthetic:non-rc"))

        refused(engine, non_rc, "DOCUMENT_ISOLATION_REQUIRED")
    cases.append("non_read_committed_inserts_refused")

    for statement in (
        "UPDATE document_source_revision SET actor='changed'",
        "DELETE FROM document_source_revision",
        "TRUNCATE document_source_revision",
    ):
        refused(
            engine,
            lambda c, statement=statement: c.exec_driver_sql(statement),
            "DOCUMENT_SOURCE_APPEND_ONLY",
        )
    cases.append("update_delete_truncate_refused")

    original_sql = row(30, holds=sorted(REQUIRED_HOLDS) + ["EXTRA_REVIEW_REQUIRED"])
    with engine.begin() as connection:
        insert(connection, values(original_sql, "synthetic:sql-guards"))
    next_row = row(30, version="v2", holds=original_sql["holds"])
    valid = values(
        next_row, "synthetic:sql-guards", revision=2, previous=original_sql["source_sha256"]
    )
    changes = [
        ({"source_sha": "0" * 64}, "DOCUMENT_SOURCE_SEAL"),
        ({"previous_sha": "0" * 64}, "DOCUMENT_REVISION_CHAIN"),
        ({"revision_no": 3}, "DOCUMENT_REVISION_CHAIN"),
        ({"holds": json.dumps(sorted(REQUIRED_HOLDS))}, "DOCUMENT_SOURCE_HOLDS"),
        ({"source_scope": SHARED}, "DOCUMENT_SOURCE_SCOPE"),
        ({"entity_scopes_sha256": "0" * 64}, "DOCUMENT_SOURCE_SEAL"),
        ({"period_end": datetime(2026, 10, 1)}, "DOCUMENT_NAMESPACE_CONTEXT"),
    ]
    for changed, guard in changes:
        refused(engine, lambda c, data={**valid, **changed}: insert(c, data), guard)
    for addition in (',"Nested":{"x":1,"x":2}', ',"Nested":[{"Outer":{"x":1,"x":2}}]'):
        incoming = dict(next_row)
        raw = incoming["source_text"][:-1] + addition + "}"
        incoming.update(source_text=raw, source_sha256=digest(raw))
        data = values(
            incoming, "synthetic:sql-guards", revision=2, previous=original_sql["source_sha256"]
        )
        refused(engine, lambda c, data=data: insert(c, data), "DOCUMENT_SOURCE_SEAL")
    for scopes in (
        json.dumps(SCOPES, ensure_ascii=False, sort_keys=True),
        json.dumps(
            dict(reversed(list(sorted(SCOPES.items())))), ensure_ascii=False, separators=(",", ":")
        ),
        json.dumps(SCOPES, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    ):
        data = {**valid, "entity_scopes_text": scopes, "entity_scopes_sha256": digest(scopes)}
        refused(engine, lambda c, data=data: insert(c, data), "DOCUMENT_SOURCE_SCOPE")
    for change, guard in [
        ({"Date": "2026-09-01T00:00:00"}, "DOCUMENT_SOURCE_PERIOD"),
        ({"Date": "2026-07-15T12:00:00+03:00"}, "DOCUMENT_SOURCE_PERIOD"),
        ({"Организация_Key": "22222222-2222-2222-2222-222222222222"}, "DOCUMENT_SOURCE_ORG"),
        ({"Posted": "true"}, "DOCUMENT_SOURCE_SEAL"),
    ]:
        incoming = row(30, version="v2", holds=original_sql["holds"], **change)
        data = values(
            incoming, "synthetic:sql-guards", revision=2, previous=original_sql["source_sha256"]
        )
        refused(engine, lambda c, data=data: insert(c, data), guard)
    reused = row(30, Date="2026-07-16T12:00:00", holds=original_sql["holds"])
    data = values(
        reused, "synthetic:sql-guards", revision=2, previous=original_sql["source_sha256"]
    )
    refused(engine, lambda c: insert(c, data), "DOCUMENT_VERSION_REUSED")
    cases.append("direct_sql_seal_chain_scope_org_period_hold_version_guards")
    with engine.begin() as connection:
        insert(connection, valid)
    with Session(engine) as session:
        assert count(session, "synthetic:sql-guards") == 2
        total = count(session)
    assert before == snapshot(engine), "G22_BUSINESS_TABLE_ROWS_CHANGED"
    cases.append("all_existing_table_counts_unchanged")
    return cases, total


def downgrade(url):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", PREVIOUS],
        cwd=migration.ROOT,
        env={
            **os.environ,
            "AIOS_ENVIRONMENT": "dev",
            "AIOS_DATABASE_URL": url.render_as_string(hide_password=False),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=300,
    )


def main():
    if sys.flags.optimize or os.environ.get("CRM_REL_001_G22_ACCEPTANCE") != "1":
        raise RuntimeError("G22_EXPLICIT_UNOPTIMIZED_PROOF_REQUIRED")
    admin = migration.selected_url()
    databases = []
    engine = None
    cases = []
    total = 0
    try:
        for mode in ("existing_catalog", "empty"):
            name = migration.PREFIX + "g22_" + uuid4().hex
            assert name.startswith(migration.PREFIX) and name != migration.ADMIN_DATABASE
            with migration.connect(admin) as connection:
                connection.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
                )
                connection.execute(
                    sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                        sql.Identifier(name), sql.Literal(name)
                    )
                )
            databases.append(name)
            url = admin.set(database=name)
            if mode == "existing_catalog":
                migration.upgrade(url, PREVIOUS)
                engine = create_engine(
                    url,
                    pool_size=6,
                    connect_args={
                        "connect_timeout": 10,
                        "options": "-c statement_timeout=15000 -c lock_timeout=10000",
                    },
                )
                source = json.dumps(
                    dict(
                        Ref_Key=str(UUID(int=100)),
                        DataVersion="catalog-v1",
                        Code="SYNTHETIC",
                        Description="Synthetic preserved catalog",
                        DeletionMark=False,
                        IsFolder=False,
                        Parent_Key=None,
                        ЕдиницаИзмерения_Key=None,
                    ),
                    ensure_ascii=False,
                )
                with Session(engine) as session:
                    import_catalog(
                        session,
                        "synthetic:preserved-catalog",
                        [SourceRow(NOMENCLATURE, source)],
                        actor="isolated-proof",
                    )
                    session.commit()
                before = snapshot(engine)
                engine.dispose()
                engine = None
            migration.upgrade(url, HEAD)
            migration.upgrade(url, HEAD)
            with migration.connect(url) as connection:
                assert migration.revision(connection) == [HEAD]
            engine = create_engine(
                url,
                pool_size=6,
                connect_args={
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=15000 -c lock_timeout=10000",
                },
            )
            if mode == "existing_catalog":
                assert before == snapshot(engine)
                with Session(engine) as session:
                    assert session.scalar(select(CatalogSourceRevision)).source_text == source
                cases.append("existing_catalog_preserved_upgrade_and_repeat")
                proved, total = proof(engine)
                cases.extend(proved)
                failed = downgrade(url)
                assert (
                    failed.returncode != 0
                    and "DOCUMENT_PRESERVED_HISTORY_NO_DOWNGRADE" in failed.stderr
                )
                with migration.connect(url) as connection:
                    assert migration.revision(connection) == [HEAD]
                with Session(engine) as session:
                    assert count(session) == total
                cases.append("populated_downgrade_refused_atomically")
            else:
                assert downgrade(url).returncode == 0
                migration.upgrade(url, HEAD)
                cases.append("empty_upgrade_repeat_downgrade_upgrade")
            engine.dispose()
            engine = None
    finally:
        if engine is not None:
            engine.dispose()
        for name in databases:
            assert name.startswith(migration.PREFIX) and name != migration.ADMIN_DATABASE
            with migration.connect(admin) as connection:
                owner, marker = connection.execute(
                    "SELECT pg_get_userbyid(datdba),shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s",
                    (name,),
                ).fetchone()
                assert owner == migration.ROLE and marker == name, "G22_DATABASE_OWNER_CHANGED"
                connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (name,),
                )
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    print(
        json.dumps(
            {
                "status": "G22_SYNTHETIC_POSTGRES_PASS",
                "head": HEAD,
                "cases": cases,
                "case_count": len(cases),
                "source_revisions": total,
                "owned_databases_removed": len(databases),
                "protected_reads": 0,
                "business_mutations": 0,
                "production_changes": 0,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
