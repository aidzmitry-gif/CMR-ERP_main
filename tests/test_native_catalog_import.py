"""Incoming identity boundary regressions; deliberately synthetic source rows."""
import json

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from core.db.base import Base
from core.domain.models import CatalogSourceIdentity, CatalogSourceRevision, Counterparty, CounterpartyAlias, Sku
from core.domain.reference import NomenclatureCategory
from core.services.native_catalog_import import (
    COUNTERPARTIES, NOMENCLATURE, CatalogImportConflict, SourceRow, digest, import_catalog,
)


def row(number, *, folder=False, parent=None, version="v1", entity=NOMENCLATURE, **changes):
    value = {"Ref_Key": f"00000000-0000-0000-0000-{number:012x}", "DataVersion": version,
             "Code": "repeated-code", "Description": "Repeated name", "DeletionMark": False}
    if entity == NOMENCLATURE:
        value.update(IsFolder=folder, Parent_Key=f"00000000-0000-0000-0000-{parent:012x}" if parent else None,
                     ЕдиницаИзмерения_Key="11111111-1111-1111-1111-111111111111")
    value.update(changes)
    return SourceRow(entity, json.dumps(value, ensure_ascii=False, sort_keys=True))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    tables = [Counterparty.__table__, CounterpartyAlias.__table__, NomenclatureCategory.__table__,
              Sku.__table__, CatalogSourceIdentity.__table__, CatalogSourceRevision.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session
    engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def load(db, rows, namespace="1c:ka_copy", **kwargs):
    return import_catalog(db, namespace, rows, actor="synthetic-test", **kwargs)


def test_same_name_code_different_guid_and_namespace(db):
    result = load(db, [row(1, folder=True), row(2, parent=1), row(3, parent=1)])
    assert result["native_groups"] == 1 and result["native_skus"] == 2
    load(db, [row(2)], namespace="other-copy")
    assert count(db, Sku) == 3
    assert len(set(db.scalars(select(Sku.code)))) == 3
    assert all(v.unit == "" and not v.is_active for v in db.scalars(select(Sku)))
    assert db.scalar(select(NomenclatureCategory)).unit is None


def test_replay_and_versioned_correction_keep_old_text(db):
    original = row(1)
    load(db, [original]); db.commit()
    result = load(db, [original]); db.commit()
    assert result["replayed"] == 1 and count(db, CatalogSourceRevision) == 1
    changed = row(1, version="v2", Description="New name")
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    load(db, [changed], expected_previous={key: digest(original.source_text)})
    assert count(db, CatalogSourceRevision) == 2
    revisions = list(db.scalars(select(CatalogSourceRevision).order_by(CatalogSourceRevision.revision_no)))
    assert revisions[0].source_text == original.source_text
    assert revisions[1].previous_sha == revisions[0].source_sha
    assert db.scalar(select(Sku)).title == "New name"


def test_stale_correction_and_same_version_change_fail(db):
    original = row(1); load(db, [original]); db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [row(1, version="v2", Description="Changed")])
    with pytest.raises(CatalogImportConflict, match="DATA_VERSION_REUSED"):
        load(db, [row(1, Description="Changed")], expected_previous={key: digest(original.source_text)})
    assert count(db, CatalogSourceRevision) == 1


def test_batch_rollback_even_after_first_insert(db):
    original = row(2); load(db, [original]); db.commit()
    with pytest.raises(CatalogImportConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [row(1), row(2, version="v2")])
    assert count(db, Sku) == 1 and count(db, CatalogSourceIdentity) == 1
    assert count(db, CatalogSourceRevision) == 1


def test_native_manual_change_blocks_replay(db):
    original = row(1); load(db, [original]); db.commit()
    db.scalar(select(Sku)).title = "Human correction"; db.commit()
    with pytest.raises(CatalogImportConflict, match="NATIVE_TARGET_CHANGED"):
        load(db, [original])
    assert db.scalar(select(Sku)).title == "Human correction"


@pytest.mark.parametrize("records,reason", [
    ([row(1, parent=9)], "GROUP_PARENT_MISSING"),
    ([row(1, folder=True, parent=2), row(2, folder=True, parent=1)], "GROUP_CYCLE"),
    ([row(1), row(1)], "DUPLICATE_SOURCE_GUID"),
])
def test_invalid_tree_or_duplicate_has_no_partial_writes(db, records, reason):
    with pytest.raises(CatalogImportConflict, match=reason): load(db, records)
    assert count(db, CatalogSourceIdentity) == count(db, Sku) == 0


def test_partial_parent_correction_cannot_create_cycle(db):
    parent, child = row(1, folder=True), row(2, folder=True, parent=1)
    load(db, [parent, child]); db.commit()
    key = (NOMENCLATURE, json.loads(parent.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="GROUP_CYCLE"):
        load(db, [row(1, folder=True, parent=2, version="v2")], expected_previous={key: digest(parent.source_text)})
    assert count(db, CatalogSourceRevision) == 2


def test_explicit_tombstone_not_absence_archives(db):
    parent, child = row(1, folder=True), row(2, folder=True)
    load(db, [parent, child]); db.commit()
    key = (NOMENCLATURE, json.loads(parent.source_text)["Ref_Key"])
    load(db, [row(1, folder=True, version="v2", DeletionMark=True)], expected_previous={key: digest(parent.source_text)})
    identities = {v.source_guid: v for v in db.scalars(select(CatalogSourceIdentity))}
    assert "SOURCE_TOMBSTONE" in identities[key[1]].holds
    assert db.get(NomenclatureCategory, identities[key[1]].group_id).is_active is False
    assert db.get(NomenclatureCategory, identities[json.loads(child.source_text)["Ref_Key"]].group_id).is_active is True
    assert count(db, CatalogSourceIdentity) == 2


def test_all_counterparties_retained_without_cards_or_aliases(db):
    result = load(db, [row(1, entity=COUNTERPARTIES), row(2, entity=COUNTERPARTIES, УНП="123456789", ЮридическийАдрес="unverified")])
    assert result["held_counterparties"] == count(db, CatalogSourceIdentity) == count(db, CatalogSourceRevision) == 2
    assert count(db, Counterparty) == count(db, CounterpartyAlias) == 0
    assert all("COUNTERPARTY_REQUISITES_UNVERIFIED" in v.holds for v in db.scalars(select(CatalogSourceIdentity)))


def test_counterparty_without_source_code_keeps_exact_payload_and_replays(db):
    value = json.loads(row(1, entity=COUNTERPARTIES).source_text)
    del value["Code"]
    incoming = SourceRow(COUNTERPARTIES, json.dumps(value, ensure_ascii=False))
    first = load(db, [incoming]); db.commit()
    second = load(db, [incoming]); db.commit()
    assert first["held_counterparties"] == second["replayed"] == 1
    assert count(db, CatalogSourceIdentity) == count(db, CatalogSourceRevision) == 1
    assert db.scalar(select(CatalogSourceRevision)).source_text == incoming.source_text
    assert "Code" not in json.loads(db.scalar(select(CatalogSourceRevision)).source_text)
    assert count(db, Counterparty) == count(db, CounterpartyAlias) == 0


@pytest.mark.parametrize("entity", [NOMENCLATURE, COUNTERPARTIES])
def test_present_nonstring_code_is_never_coerced(db, entity):
    with pytest.raises(CatalogImportConflict, match="SOURCE_NAME_CODE"):
        load(db, [row(1, entity=entity, Code=42)])
    assert count(db, CatalogSourceIdentity) == count(db, CatalogSourceRevision) == 0


def test_nomenclature_still_requires_source_code(db):
    value = json.loads(row(1).source_text)
    del value["Code"]
    with pytest.raises(CatalogImportConflict, match="SOURCE_NAME_CODE"):
        load(db, [SourceRow(NOMENCLATURE, json.dumps(value))])
    assert count(db, CatalogSourceIdentity) == count(db, Sku) == 0


def test_exact_numeric_text_is_preserved(db):
    incoming = row(1)
    precise = incoming.source_text[:-1] + ', "ObservedNumber": 0.100000000000000000001}'
    load(db, [SourceRow(NOMENCLATURE, precise)])
    assert db.scalar(select(CatalogSourceRevision)).source_text == precise


def test_projection_not_full_source_entity_and_unknown_unit_explicit(db):
    load(db, [row(1)])
    saved = db.scalar(select(Sku)).attributes["source_catalog"]
    assert saved["observed_shape"] == "projection" and saved["group_review"] == "PENDING"
    assert "UNKNOWN_UNIT" in saved["holds"] and saved["unit_guid"] == "11111111-1111-1111-1111-111111111111"


def test_sql_failure_rolls_back_created_group_and_source_identity(db):
    key = json.loads(row(2).source_text)["Ref_Key"]
    code = "SRC-" + digest("1c:ka_copy:" + NOMENCLATURE + ":" + key)[:48]
    db.add(Sku(code=code, title="Existing manual record", unit="шт")); db.commit()
    with pytest.raises(IntegrityError): load(db, [row(1, folder=True), row(2, parent=1)])
    assert count(db, CatalogSourceIdentity) == count(db, CatalogSourceRevision) == count(db, NomenclatureCategory) == 0
    assert count(db, Sku) == 1


def test_existing_parent_manual_change_blocks_partial_item_load(db):
    load(db, [row(1, folder=True)]); db.commit()
    db.scalar(select(NomenclatureCategory)).parent_id = 1; db.commit()
    with pytest.raises(CatalogImportConflict, match="NATIVE_TARGET_CHANGED"):
        load(db, [row(2, parent=1)])
    assert count(db, Sku) == 0


def test_invalid_source_title_correction_archives_existing_group(db):
    original = row(1, folder=True); load(db, [original]); db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    load(db, [row(1, folder=True, version="v2", Description="")], expected_previous={key: digest(original.source_text)})
    assert not db.scalar(select(NomenclatureCategory)).is_active
    assert "NATIVE_TITLE_INVALID" in db.scalar(select(CatalogSourceIdentity)).holds
