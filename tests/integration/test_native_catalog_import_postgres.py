"""Explicit fresh local-cluster proof; no pytest skips or production defaults.

Uses the established G03 local role/database guard. The server controller must
also prove container ownership, pinned images, no bindings and network=none.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import gzip
import hashlib
from pathlib import Path
import sys
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from psycopg import sql

import crm_rel_001_migration_proof as migration
from core.domain.models import CatalogSourceIdentity, CatalogSourceRevision, Sku
from core.domain.reference import NomenclatureCategory
from core.services.native_catalog_import import (
    COUNTERPARTIES, NOMENCLATURE, CatalogImportConflict, SourceRow, digest, import_catalog,
)

HEAD = "crm_rel_001_native_catalog_01"


def real_source_proof(session):
    """A separate namespace: measured sealed source, never synthetic identities."""
    packet = Path("incoming-catalog.json.gz")
    manifest = json.loads(Path("incoming-catalog-receipt.json").read_text(encoding="utf8"))
    assert manifest["status"] == "SEALED_OBSERVED_INPUTS_ONLY"
    assert hashlib.sha256(packet.read_bytes()).hexdigest() == manifest["gzip_sha256"]
    records = []
    decoded_size = 0
    with gzip.open(packet, "rb") as stream:
        for line in stream:
            decoded_size += len(line)
            assert decoded_size <= 128 * 1024 * 1024, "INPUT_DECOMPRESSION_CAP"
            value = json.loads(line)
            assert set(value) == {"entity", "source_text"}, "INPUT_SHAPE"
            records.append(SourceRow(**value))
    assert decoded_size == manifest["decoded_bytes"] and len(records) == 14522
    assert sum(row.entity == NOMENCLATURE for row in records) == 9606
    assert sum(row.entity == COUNTERPARTIES for row in records) == 4916
    first = load(session, records, namespace="1c:ka_copy")
    session.commit()
    second = load(session, records, namespace="1c:ka_copy")
    session.commit()
    identities = list(session.scalars(select(CatalogSourceIdentity).where(CatalogSourceIdentity.namespace == "1c:ka_copy")))
    totals = {"identities": len(identities), "groups": sum(row.group_id is not None for row in identities),
              "skus": sum(row.sku_id is not None for row in identities),
              "counterparties_on_hold": sum(row.kind == "counterparty" for row in identities),
              "counterparty_cards": sum(row.counterparty_id is not None for row in identities),
              "unknown_units": sum("UNKNOWN_UNIT" in row.holds for row in identities),
              "tombstones": sum("SOURCE_TOMBSTONE" in row.holds for row in identities),
              "revisions": session.scalar(select(func.count()).select_from(CatalogSourceRevision).join(
                  CatalogSourceIdentity, CatalogSourceIdentity.id == CatalogSourceRevision.identity_id).where(CatalogSourceIdentity.namespace == "1c:ka_copy"))}
    assert first["created"] == second["replayed"] == totals["identities"] == totals["revisions"] == 14522
    assert totals["groups"] == 86 and totals["skus"] == totals["unknown_units"] == 9520
    assert totals["counterparties_on_hold"] == 4916 and totals["counterparty_cards"] == 0
    assert session.scalar(text("SELECT count(*) FROM counterparty_alias")) == 0
    assert session.scalar(text("SELECT count(*) FROM sync_link")) == 0
    assert session.scalar(text("SELECT count(*) FROM accounting.entry")) == 0
    assert session.scalar(text("SELECT count(*) FROM wms.stock_movement")) == 0
    enrichment = real_source_enrichment(session, identities)
    totals["revisions"] = enrichment["revisions_after"]
    return {"status": "VERIFIED_NATIVE_SOURCE_LOAD_AND_REPLAY_ONLY", "source_seals": manifest["source_seals"],
            "totals": totals, "enrichment": enrichment, "replay_no_duplicate_revisions": True,
            "observed_nomenclature_shape": "projection_and_enriched",
            "operational_catalog_acceptance": False, "full_counterparty_import": False,
            "postings": 0, "stock_movements": 0, "outbound_sync": 0, "production_changes": 0}


def real_source_enrichment(session, identities):
    packet = Path("incoming-catalog-enrichment.json.gz")
    manifest = json.loads(Path("incoming-catalog-enrichment-receipt.json").read_text(encoding="utf8"))
    assert manifest["status"] == "SEALED_OBSERVED_ENRICHMENT_ONLY"
    assert hashlib.sha256(packet.read_bytes()).hexdigest() == manifest["gzip_sha256"]
    records, previous, decoded_size = [], {}, 0
    with gzip.open(packet, "rb") as stream:
        for line in stream:
            decoded_size += len(line)
            assert decoded_size <= 128 * 1024 * 1024, "INPUT_DECOMPRESSION_CAP"
            value = json.loads(line)
            assert set(value) == {"entity", "source_text", "previous_sha"}, "ENRICHMENT_INPUT_SHAPE"
            source_sha = value.pop("previous_sha")
            assert isinstance(source_sha, str) and len(source_sha) == 64 and all(c in "0123456789abcdef" for c in source_sha)
            record = SourceRow(**value)
            key = (record.entity, record.parse()[0])
            assert record.entity == NOMENCLATURE and key not in previous
            records.append(record)
            previous[key] = source_sha
    assert decoded_size == manifest["decoded_bytes"] and len(records) == 1825
    selected = [identity for identity in identities if (identity.entity, identity.source_guid) in previous]
    assert len(selected) == 1825
    assert sum(identity.kind == "sku" for identity in selected) == 1786
    assert sum(identity.kind == "group" for identity in selected) == 39
    before = {(v.entity, v.source_guid): (v.id, v.sku_id, v.group_id, list(v.holds)) for v in selected}
    assert all(previous[(v.entity, v.source_guid)] == v.source_sha and v.revision_no == 1 for v in selected)
    first = load(session, records, namespace="1c:ka_copy", enrich_projection=True, expected_previous=previous)
    session.commit()
    second = load(session, records, namespace="1c:ka_copy", enrich_projection=True, expected_previous=previous)
    session.commit()
    assert first["created"] == second["created"] == 0
    assert first["corrected"] == second["replayed"] == 1825 and second["corrected"] == 0
    for identity in selected:
        assert (identity.id, identity.sku_id, identity.group_id, identity.holds) == before[(identity.entity, identity.source_guid)]
        assert identity.revision_no == 2
        target = session.get(Sku, identity.sku_id) if identity.kind == "sku" else session.get(NomenclatureCategory, identity.group_id)
        assert target.attributes["source_catalog"]["observed_shape"] == "enriched"
        assert target.attributes["source_catalog"]["group_review"] == "PENDING"
        if identity.kind == "sku": assert not target.is_active and target.unit == "" and "UNKNOWN_UNIT" in identity.holds
        if "SOURCE_TOMBSTONE" in identity.holds: assert not target.is_active
    revisions = list(session.scalars(select(CatalogSourceRevision).join(
        CatalogSourceIdentity, CatalogSourceIdentity.id == CatalogSourceRevision.identity_id).where(
            CatalogSourceIdentity.namespace == "1c:ka_copy")))
    assert len(revisions) == 14522 + 1825
    exact = {(record.entity, record.parse()[0]): record.source_text for record in records}
    current = {v.identity_id: v for v in revisions if v.revision_no == 2}
    assert len(current) == 1825 and all(current[v.id].source_text == exact[(v.entity, v.source_guid)]
        and current[v.id].previous_sha == previous[(v.entity, v.source_guid)] for v in selected)
    assert all(session.scalar(text("SELECT count(*) FROM " + table)) == 0 for table in
               ("counterparty", "counterparty_alias", "sync_link", "accounting.entry", "wms.stock_movement"))
    return {"status": "VERIFIED_SAME_IDENTITY_ENRICHMENT_AND_EXACT_REPLAY_ONLY", "records": 1825,
            "skus": 1786, "groups": 39, "revisions_before": 14522, "revisions_after": len(revisions),
            "same_native_ids_and_holds": True, "exact_source_text_and_previous_sha": True,
            "replay_new_revisions": 0, "source_comparison_sha256": manifest["source_comparison_sha256"],
            "source_seals": manifest["source_seals"], "operational_catalog_acceptance": False}


def row(number, *, folder=False, parent=None, version="v1", entity=NOMENCLATURE, **changes):
    values = dict(Ref_Key=str(UUID(int=number)), DataVersion=version,
                  Code="same", Description="Synthetic catalog", DeletionMark=False)
    if entity == NOMENCLATURE:
        values.update(IsFolder=folder, Parent_Key=str(UUID(int=parent)) if parent else None,
                      ЕдиницаИзмерения_Key=None)
    else:
        del values["Code"]  # Observed ka_copy counterparty schema has no Code.
    values.update(changes)
    return SourceRow(entity, json.dumps(values, ensure_ascii=False, sort_keys=True))


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def load(session, values, namespace="synthetic:race", **kwargs):
    return import_catalog(session, namespace, values, actor="isolated-postgres-proof", **kwargs)


def refused_sql(engine, command, expected_guard="Catalog source revision is append-only"):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(command))
        except DBAPIError as error:
            transaction.rollback()
            assert getattr(error.orig, "sqlstate", None) == "P0001", "UNEXPECTED_GUARD_SQLSTATE"
            assert getattr(getattr(error.orig, "diag", None), "message_primary", None) == expected_guard, "UNEXPECTED_GUARD_MESSAGE"
            return
        transaction.rollback()
        raise AssertionError("IMMUTABILITY_SQL_ACCEPTED")


def main():
    assert os.environ.get("CRM_REL_001_G17_ACCEPTANCE") == "1", "EXPLICIT_NATIVE_PROOF_REQUIRED"
    admin = migration.selected_url()
    database = migration.PREFIX + "native_" + uuid4().hex
    assert database.startswith(migration.PREFIX) and database != migration.ADMIN_DATABASE
    url = admin.set(database=database)
    cases = []
    engine = None
    with migration.connect(admin) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
    try:
        migration.upgrade(url, HEAD)
        with migration.connect(url) as connection:
            assert migration.revision(connection) == [HEAD]
        engine = create_engine(url, pool_size=4)

        def concurrent_load():
            with Session(engine) as session:
                result = load(session, [row(1, folder=True), row(2, parent=1)])
                session.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(concurrent_load) for _ in range(2)]
            results = [value.result(timeout=30) for value in futures]
        assert sorted(result["created"] for result in results) == [0, 2]
        assert sorted(result["replayed"] for result in results) == [0, 2]
        with Session(engine) as session:
            assert count(session, CatalogSourceIdentity) == count(session, CatalogSourceRevision) == 2
        cases.append("concurrent_replay_single_identity")

        with Session(engine, expire_on_commit=False) as stale:
            # Objects retained before a different writer changes native data.
            stale.scalar(select(CatalogSourceIdentity).where(CatalogSourceIdentity.kind == "sku"))
            cached = stale.scalar(select(Sku))
            stale.commit()
            with Session(engine) as editor:
                editor.scalar(select(Sku)).title = "Synthetic manual edit"
                editor.commit()
            try:
                load(stale, [row(3, folder=True), row(2, parent=1)])
            except CatalogImportConflict as error:
                assert str(error) == "NATIVE_TARGET_CHANGED"
            else:
                raise AssertionError("STALE_NATIVE_OVERWRITTEN")
            assert cached.title == "Synthetic manual edit"
            assert count(stale, NomenclatureCategory) == 1
            assert count(stale, CatalogSourceRevision) == 2
        cases.append("preloaded_native_refresh_and_batch_rollback")

        refused_sql(engine, "UPDATE catalog_source_revision SET actor='changed'")
        refused_sql(engine, "DELETE FROM catalog_source_revision")
        refused_sql(engine, "TRUNCATE catalog_source_revision")
        refused_sql(engine, "TRUNCATE catalog_source_identity CASCADE")
        refused_sql(engine, "UPDATE catalog_source_identity SET namespace='changed'", "Catalog source identity is immutable")
        cases.append("append_only_update_delete_truncate_and_identity_guard")

        with Session(engine) as session:
            original = row(10, folder=True)
            load(session, [original], namespace="synthetic:correction"); session.commit()
            key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
            changed = row(10, folder=True, version="v2", DeletionMark=True)
            load(session, [changed], namespace="synthetic:correction", expected_previous={key: digest(original.source_text)})
            session.commit()
            target = session.scalar(select(CatalogSourceIdentity).where(CatalogSourceIdentity.namespace == "synthetic:correction"))
            assert not session.get(NomenclatureCategory, target.group_id).is_active
            saved = list(session.scalars(select(CatalogSourceRevision).where(CatalogSourceRevision.identity_id == target.id).order_by(CatalogSourceRevision.revision_no)))
            assert [value.source_text for value in saved] == [original.source_text, changed.source_text]
        cases.append("versioned_tombstone_history_retained")

        with Session(engine) as session:
            result = load(session, [row(15, entity=COUNTERPARTIES)], namespace="synthetic:counterparty")
            session.commit()
            assert result["held_counterparties"] == 1
            assert session.scalar(text("SELECT count(*) FROM counterparty")) == 0
            assert session.scalar(text("SELECT count(*) FROM counterparty_alias")) == 0
            assert session.scalar(text("SELECT count(*) FROM sync_link")) == 0
            assert session.scalar(text("SELECT count(*) FROM accounting.entry")) == 0
            assert session.scalar(text("SELECT count(*) FROM wms.stock_movement")) == 0
            assert count(session, CatalogSourceIdentity) == count(session, CatalogSourceRevision) - 1 == 4
        cases.append("required_requisites_hold_and_no_financial_outbound_writes")

        projections = [row(20, folder=True), row(21, parent=20)]
        full = [row(20, folder=True, AdditionalSourceField=True), row(21, parent=20, AdditionalSourceField=True)]
        previous = {(v.entity, v.parse()[0]): digest(v.source_text) for v in projections}
        with Session(engine) as session:
            load(session, projections, namespace="synthetic:enrichment"); session.commit()

        def concurrent_enrich():
            with Session(engine) as session:
                result = load(session, full, namespace="synthetic:enrichment", enrich_projection=True, expected_previous=previous)
                session.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [value.result(timeout=30) for value in [pool.submit(concurrent_enrich) for _ in range(2)]]
        assert sorted(result["corrected"] for result in results) == [0, 2]
        assert sorted(result["replayed"] for result in results) == [0, 2]
        with Session(engine) as session:
            identities = list(session.scalars(select(CatalogSourceIdentity).where(CatalogSourceIdentity.namespace == "synthetic:enrichment")))
            revisions = list(session.scalars(select(CatalogSourceRevision).where(CatalogSourceRevision.identity_id.in_([v.id for v in identities]))))
            assert len(identities) == 2 and len(revisions) == 4 and all(v.revision_no == 2 for v in identities)
            assert all(v.previous_sha in previous.values() for v in revisions if v.revision_no == 2)
        refused_sql(engine, "UPDATE catalog_source_revision SET actor='changed' WHERE revision_no=2")
        cases.append("concurrent_enrichment_single_new_revision_and_immutable_history")
        # Same fresh migrated native schema; synthetic namespace stays separate.
        with Session(engine) as session:
            source_result = real_source_proof(session)
        print(json.dumps({"status": "passed", "head": HEAD, "cases": cases,
                          "source_result": source_result, "production_changes": 0}), flush=True)
    finally:
        if engine is not None:
            engine.dispose()
        with migration.connect(admin) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


if __name__ == "__main__":
    main()
