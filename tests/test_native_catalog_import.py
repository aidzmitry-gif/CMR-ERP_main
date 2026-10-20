"""Incoming identity boundary regressions; deliberately synthetic source rows."""

import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db.base import Base
from core.domain.models import (
    CatalogSourceIdentity,
    CatalogSourceRevision,
    Counterparty,
    CounterpartyAlias,
    Sku,
)
from core.domain.reference import NomenclatureCategory
from core.services.native_catalog_import import (
    COUNTERPARTIES,
    NOMENCLATURE,
    CatalogImportConflict,
    SourceRow,
    SourceUnitBinding,
    bind_source_units,
    digest,
    import_catalog,
)


def row(number, *, folder=False, parent=None, version="v1", entity=NOMENCLATURE, **changes):
    value = {
        "Ref_Key": f"00000000-0000-0000-0000-{number:012x}",
        "DataVersion": version,
        "Code": "repeated-code",
        "Description": "Repeated name",
        "DeletionMark": False,
    }
    if entity == NOMENCLATURE:
        value.update(
            IsFolder=folder,
            Parent_Key=f"00000000-0000-0000-0000-{parent:012x}" if parent else None,
            ЕдиницаИзмерения_Key="11111111-1111-1111-1111-111111111111",
        )
    value.update(changes)
    return SourceRow(entity, json.dumps(value, ensure_ascii=False, sort_keys=True))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    tables = [
        Counterparty.__table__,
        CounterpartyAlias.__table__,
        NomenclatureCategory.__table__,
        Sku.__table__,
        CatalogSourceIdentity.__table__,
        CatalogSourceRevision.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        yield session
    engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def load(db, rows, namespace="1c:ka_copy", **kwargs):
    return import_catalog(db, namespace, rows, actor="synthetic-test", **kwargs)


def unit_binding(db, incoming, **unit_changes):
    identity = db.scalar(
        select(CatalogSourceIdentity).where(
            CatalogSourceIdentity.source_guid == json.loads(incoming.source_text)["Ref_Key"]
        )
    )
    unit = {
        "Ref_Key": "11111111-1111-1111-1111-111111111111",
        "DataVersion": "unit-v1",
        "DeletionMark": False,
        "Description": "упак",
    }
    unit.update(unit_changes)
    return SourceUnitBinding(
        incoming,
        json.dumps(unit, ensure_ascii=True),
        identity.revision_no,
        identity.target_sha,
        "a" * 64,
    )


def test_unit_binding_preserves_history_and_replays_without_activation(db):
    incoming = row(1)
    load(db, [incoming])
    db.commit()
    binding = unit_binding(db, incoming)
    old = db.scalar(select(CatalogSourceRevision))
    old_values = old.source_text, old.source_sha, old.target_sha, list(old.holds)
    result = bind_source_units(db, "1c:ka_copy", [binding], actor="unit-test")
    db.commit()
    assert result == {"bound": 1, "replayed": 0}
    target = db.scalar(select(Sku))
    assert target.unit == "упак" and target.is_active is False
    assert target.attributes["source_catalog"]["group_review"] == "PENDING"
    assert target.attributes["source_catalog"]["holds"] == []
    assert target.provenance["source_unit"]["source_text"] == binding.unit_source_text
    revisions = list(
        db.scalars(select(CatalogSourceRevision).order_by(CatalogSourceRevision.revision_no))
    )
    assert len(revisions) == 2
    assert (old.source_text, old.source_sha, old.target_sha, old.holds) == old_values
    assert revisions[1].source_text == incoming.source_text
    assert revisions[1].source_sha == revisions[1].previous_sha == digest(incoming.source_text)
    assert bind_source_units(db, "1c:ka_copy", [binding], actor="unit-test") == {
        "bound": 0,
        "replayed": 1,
    }
    assert load(db, [incoming])["replayed"] == 1
    assert count(db, CatalogSourceRevision) == 2


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"DeletionMark": True}, "UNIT_DELETED_OR_UNKNOWN"),
        ({"DeletionMark": None}, "UNIT_DELETED_OR_UNKNOWN"),
        ({"Ref_Key": "22222222-2222-2222-2222-222222222222"}, "UNIT_REFERENCE_MISMATCH"),
        ({"Description": ""}, "UNIT_LABEL_INVALID"),
        ({"Description": " шт"}, "UNIT_LABEL_INVALID"),
        ({"Description": "x" * 17}, "UNIT_LABEL_INVALID"),
        ({"Description": "шт\u0000"}, "UNIT_LABEL_INVALID"),
        ({"Description": "шт\ud800"}, "UNIT_LABEL_INVALID"),
        ({"Description": "шт\u0085"}, "UNIT_LABEL_INVALID"),
        ({"DataVersion": ""}, "SOURCE_DATA_VERSION"),
        ({"DataVersion": "v\u0000"}, "SOURCE_DATA_VERSION"),
        ({"DataVersion": "v\ud800"}, "SOURCE_DATA_VERSION"),
    ],
)
def test_invalid_unit_leaves_unknown_unit_and_source_unchanged(db, changes, code):
    incoming = row(1)
    load(db, [incoming])
    db.commit()
    with pytest.raises(CatalogImportConflict, match=code):
        bind_source_units(
            db, "1c:ka_copy", [unit_binding(db, incoming, **changes)], actor="unit-test"
        )
    assert count(db, CatalogSourceRevision) == 1
    assert db.scalar(select(Sku)).unit == ""
    assert db.scalar(select(CatalogSourceIdentity)).holds == ["UNKNOWN_UNIT"]


def test_invalid_unit_source_encoding_fails_before_mutation(db):
    from dataclasses import replace

    incoming = row(1)
    load(db, [incoming])
    db.commit()
    binding = unit_binding(db, incoming)
    with pytest.raises(CatalogImportConflict, match="SOURCE_JSON"):
        bind_source_units(
            db, "1c:ka_copy", [replace(binding, unit_source_text='"\ud800"')], actor="unit-test"
        )
    assert count(db, CatalogSourceRevision) == 1
    assert db.scalar(select(Sku)).unit == ""


def test_unit_binding_batch_rolls_back_when_later_target_was_edited(db):
    first, second = row(1), row(2)
    load(db, [first, second])
    db.commit()
    bindings = [unit_binding(db, value) for value in (first, second)]
    edited = db.get(
        Sku,
        db.scalar(
            select(CatalogSourceIdentity).where(
                CatalogSourceIdentity.source_guid == json.loads(second.source_text)["Ref_Key"]
            )
        ).sku_id,
    )
    edited.title = "Manual edit"
    db.commit()
    with pytest.raises(CatalogImportConflict, match="NATIVE_TARGET_CHANGED"):
        bind_source_units(db, "1c:ka_copy", bindings, actor="unit-test")
    assert count(db, CatalogSourceRevision) == 2
    assert all(value.unit == "" for value in db.scalars(select(Sku)))
    assert edited.title == "Manual edit"


def test_unit_binding_rejects_changed_source_and_stale_revision(db):
    from dataclasses import replace

    incoming = row(1)
    load(db, [incoming])
    db.commit()
    binding = unit_binding(db, incoming)
    with pytest.raises(CatalogImportConflict, match="UNIT_SKU_SOURCE_CHANGED"):
        bind_source_units(
            db, "1c:ka_copy", [replace(binding, sku=row(1, version="v2"))], actor="unit-test"
        )
    with pytest.raises(CatalogImportConflict, match="EXPECTED_TARGET_REVISION"):
        bind_source_units(
            db, "1c:ka_copy", [replace(binding, expected_revision=2)], actor="unit-test"
        )
    assert count(db, CatalogSourceRevision) == 1


def test_unit_binding_preserves_other_holds(db):
    from core.services.native_catalog_import import _target_sha

    incoming = row(1)
    load(db, [incoming])
    db.commit()
    target = db.scalar(select(Sku))
    identity = db.scalar(select(CatalogSourceIdentity))
    current = db.scalar(select(CatalogSourceRevision))
    holds = ["UNKNOWN_UNIT", "EXTERNAL_REVIEW"]
    target.attributes = {"source_catalog": {**target.attributes["source_catalog"], "holds": holds}}
    identity.holds = current.holds = holds
    identity.target_sha = current.target_sha = _target_sha(target)
    db.commit()
    bind_source_units(db, "1c:ka_copy", [unit_binding(db, incoming)], actor="unit-test")
    assert identity.holds == ["EXTERNAL_REVIEW"]
    assert target.is_active is False
    db.commit()
    with pytest.raises(CatalogImportConflict, match="UNIT_ACTIVATION_HELD"):
        bind_source_units(
            db, "1c:ka_copy", [unit_binding(db, incoming)], actor="unit-test", activate=True
        )
    assert target.is_active is False


def test_explicit_unit_activation_is_audited_and_replays(db):
    incoming = row(1)
    load(db, [incoming])
    db.commit()
    first = unit_binding(db, incoming)
    bind_source_units(db, "1c:ka_copy", [first], actor="unit-test")
    db.commit()
    with pytest.raises(CatalogImportConflict, match="EXPECTED_TARGET_REVISION"):
        bind_source_units(db, "1c:ka_copy", [first], actor="unit-test", activate=True)
    current = unit_binding(db, incoming)
    assert bind_source_units(db, "1c:ka_copy", [current], actor="unit-test", activate=True) == {
        "bound": 1,
        "replayed": 0,
    }
    db.commit()
    target = db.scalar(select(Sku))
    assert target.is_active is True
    assert target.attributes["source_catalog"]["group_review"] == "PENDING"
    assert count(db, CatalogSourceRevision) == 3
    assert bind_source_units(db, "1c:ka_copy", [current], actor="unit-test", activate=True) == {
        "bound": 0,
        "replayed": 1,
    }
    assert count(db, CatalogSourceRevision) == 3


def test_initial_explicit_activation_clears_only_unknown_unit(db):
    incoming = row(1)
    load(db, [incoming])
    db.commit()
    binding = unit_binding(db, incoming)
    with pytest.raises(CatalogImportConflict, match="UNIT_ACTIVATION_MODE"):
        bind_source_units(db, "1c:ka_copy", [binding], actor="unit-test", activate="true")
    bind_source_units(db, "1c:ka_copy", [binding], actor="unit-test", activate=True)
    assert db.scalar(select(Sku)).is_active is True
    assert count(db, CatalogSourceRevision) == 2


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
    load(db, [original])
    db.commit()
    result = load(db, [original])
    db.commit()
    assert result["replayed"] == 1 and count(db, CatalogSourceRevision) == 1
    changed = row(1, version="v2", Description="New name")
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    load(db, [changed], expected_previous={key: digest(original.source_text)})
    assert count(db, CatalogSourceRevision) == 2
    revisions = list(
        db.scalars(select(CatalogSourceRevision).order_by(CatalogSourceRevision.revision_no))
    )
    assert revisions[0].source_text == original.source_text
    assert revisions[1].previous_sha == revisions[0].source_sha
    assert db.scalar(select(Sku)).title == "New name"


def test_stale_correction_and_same_version_change_fail(db):
    original = row(1)
    load(db, [original])
    db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [row(1, version="v2", Description="Changed")])
    with pytest.raises(CatalogImportConflict, match="DATA_VERSION_REUSED"):
        load(
            db,
            [row(1, Description="Changed")],
            expected_previous={key: digest(original.source_text)},
        )
    assert count(db, CatalogSourceRevision) == 1


def test_batch_rollback_even_after_first_insert(db):
    original = row(2)
    load(db, [original])
    db.commit()
    with pytest.raises(CatalogImportConflict, match="EXPECTED_PREVIOUS_SHA"):
        load(db, [row(1), row(2, version="v2")])
    assert count(db, Sku) == 1 and count(db, CatalogSourceIdentity) == 1
    assert count(db, CatalogSourceRevision) == 1


def test_native_manual_change_blocks_replay(db):
    original = row(1)
    load(db, [original])
    db.commit()
    db.scalar(select(Sku)).title = "Human correction"
    db.commit()
    with pytest.raises(CatalogImportConflict, match="NATIVE_TARGET_CHANGED"):
        load(db, [original])
    assert db.scalar(select(Sku)).title == "Human correction"


@pytest.mark.parametrize(
    "records,reason",
    [
        ([row(1, parent=9)], "GROUP_PARENT_MISSING"),
        ([row(1, folder=True, parent=2), row(2, folder=True, parent=1)], "GROUP_CYCLE"),
        ([row(1), row(1)], "DUPLICATE_SOURCE_GUID"),
    ],
)
def test_invalid_tree_or_duplicate_has_no_partial_writes(db, records, reason):
    with pytest.raises(CatalogImportConflict, match=reason):
        load(db, records)
    assert count(db, CatalogSourceIdentity) == count(db, Sku) == 0


def test_partial_parent_correction_cannot_create_cycle(db):
    parent, child = row(1, folder=True), row(2, folder=True, parent=1)
    load(db, [parent, child])
    db.commit()
    key = (NOMENCLATURE, json.loads(parent.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="GROUP_CYCLE"):
        load(
            db,
            [row(1, folder=True, parent=2, version="v2")],
            expected_previous={key: digest(parent.source_text)},
        )
    assert count(db, CatalogSourceRevision) == 2


def test_explicit_tombstone_not_absence_archives(db):
    parent, child = row(1, folder=True), row(2, folder=True)
    load(db, [parent, child])
    db.commit()
    key = (NOMENCLATURE, json.loads(parent.source_text)["Ref_Key"])
    load(
        db,
        [row(1, folder=True, version="v2", DeletionMark=True)],
        expected_previous={key: digest(parent.source_text)},
    )
    identities = {v.source_guid: v for v in db.scalars(select(CatalogSourceIdentity))}
    assert "SOURCE_TOMBSTONE" in identities[key[1]].holds
    assert db.get(NomenclatureCategory, identities[key[1]].group_id).is_active is False
    assert (
        db.get(
            NomenclatureCategory, identities[json.loads(child.source_text)["Ref_Key"]].group_id
        ).is_active
        is True
    )
    assert count(db, CatalogSourceIdentity) == 2


def test_all_counterparties_retained_without_cards_or_aliases(db):
    result = load(
        db,
        [
            row(1, entity=COUNTERPARTIES),
            row(2, entity=COUNTERPARTIES, УНП="123456789", ЮридическийАдрес="unverified"),
        ],
    )
    assert (
        result["held_counterparties"]
        == count(db, CatalogSourceIdentity)
        == count(db, CatalogSourceRevision)
        == 2
    )
    assert count(db, Counterparty) == count(db, CounterpartyAlias) == 0
    assert all(
        "COUNTERPARTY_REQUISITES_UNVERIFIED" in v.holds
        for v in db.scalars(select(CatalogSourceIdentity))
    )


def test_counterparty_without_source_code_keeps_exact_payload_and_replays(db):
    value = json.loads(row(1, entity=COUNTERPARTIES).source_text)
    del value["Code"]
    incoming = SourceRow(COUNTERPARTIES, json.dumps(value, ensure_ascii=False))
    first = load(db, [incoming])
    db.commit()
    second = load(db, [incoming])
    db.commit()
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
    assert (
        "UNKNOWN_UNIT" in saved["holds"]
        and saved["unit_guid"] == "11111111-1111-1111-1111-111111111111"
    )


def test_sql_failure_rolls_back_created_group_and_source_identity(db):
    key = json.loads(row(2).source_text)["Ref_Key"]
    code = "SRC-" + digest("1c:ka_copy:" + NOMENCLATURE + ":" + key)[:48]
    db.add(Sku(code=code, title="Existing manual record", unit="шт"))
    db.commit()
    with pytest.raises(IntegrityError):
        load(db, [row(1, folder=True), row(2, parent=1)])
    assert (
        count(db, CatalogSourceIdentity)
        == count(db, CatalogSourceRevision)
        == count(db, NomenclatureCategory)
        == 0
    )
    assert count(db, Sku) == 1


def test_existing_parent_manual_change_blocks_partial_item_load(db):
    load(db, [row(1, folder=True)])
    db.commit()
    db.scalar(select(NomenclatureCategory)).parent_id = 1
    db.commit()
    with pytest.raises(CatalogImportConflict, match="NATIVE_TARGET_CHANGED"):
        load(db, [row(2, parent=1)])
    assert count(db, Sku) == 0


def test_invalid_source_title_correction_archives_existing_group(db):
    original = row(1, folder=True)
    load(db, [original])
    db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    load(
        db,
        [row(1, folder=True, version="v2", Description="")],
        expected_previous={key: digest(original.source_text)},
    )
    assert not db.scalar(select(NomenclatureCategory)).is_active
    assert "NATIVE_TITLE_INVALID" in db.scalar(select(CatalogSourceIdentity)).holds


@pytest.mark.parametrize("folder", [False, True])
@pytest.mark.parametrize("tombstone", [False, True])
def test_enrichment_keeps_identity_history_holds_and_replays(db, folder, tombstone):
    original = row(1, folder=folder, DeletionMark=tombstone)
    load(db, [original])
    db.commit()
    identity = db.scalar(select(CatalogSourceIdentity))
    before = (identity.id, identity.sku_id, identity.group_id, list(identity.holds))
    model = NomenclatureCategory if folder else Sku
    active = db.scalar(select(model)).is_active
    value = json.loads(original.source_text)
    value["AdditionalSourceFields"] = {"weight": 1.25, "codes": ["unchanged-source"]}
    full = SourceRow(NOMENCLATURE, json.dumps(value, ensure_ascii=False, sort_keys=True))
    key = (NOMENCLATURE, value["Ref_Key"])
    result = load(
        db, [full], enrich_projection=True, expected_previous={key: digest(original.source_text)}
    )
    db.commit()
    assert result["created"] == 0 and result["corrected"] == 1
    assert (identity.id, identity.sku_id, identity.group_id, identity.holds) == before
    native = db.scalar(select(model))
    assert native.is_active == active and native.unit == (None if folder else "")
    assert native.attributes["source_catalog"]["observed_shape"] == "enriched"
    assert native.attributes["source_catalog"]["group_review"] == "PENDING"
    revisions = list(
        db.scalars(select(CatalogSourceRevision).order_by(CatalogSourceRevision.revision_no))
    )
    assert [v.source_text for v in revisions] == [original.source_text, full.source_text]
    assert revisions[1].previous_sha == revisions[0].source_sha
    assert revisions[0].data_version == revisions[1].data_version
    for options in ({"enrich_projection": True}, {}):
        assert load(db, [full], **options)["replayed"] == 1
        db.commit()
    assert count(db, CatalogSourceIdentity) == 1 and count(db, CatalogSourceRevision) == 2


def test_enrichment_requires_explicit_mode_and_exact_previous_sha(db):
    original = row(1)
    load(db, [original])
    db.commit()
    full = row(1, AdditionalSourceField="extra")
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="DATA_VERSION_REUSED"):
        load(db, [full], expected_previous={key: digest(original.source_text)})
    for previous in ({}, {key: "0" * 64}):
        with pytest.raises(CatalogImportConflict, match="EXPECTED_PREVIOUS_SHA"):
            load(db, [full], enrich_projection=True, expected_previous=previous)
    assert count(db, CatalogSourceRevision) == 1


@pytest.mark.parametrize(
    "before,after",
    [
        ("1", "1.0"),
        ("0.10", "0.1"),
        ("1e0", "1"),
        ("true", "1"),
        ("null", '""'),
        ('"1"', "1"),
        ("[1,2]", "[2,1]"),
        ('{"nested":{"flag":true}}', '{"nested":{"flag":1}}'),
        ('{"nested":{"amount":0.10}}', '{"nested":{"amount":0.1}}'),
    ],
)
def test_enrichment_rejects_raw_value_type_or_number_lexeme_change(db, before, after):
    base = row(1).source_text[:-1]
    original = SourceRow(NOMENCLATURE, base + ',"Observed":' + before + "}")
    load(db, [original])
    db.commit()
    changed = SourceRow(NOMENCLATURE, base + ',"Observed":' + after + ',"Added":true}')
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_FIELDS_CHANGED"):
        load(
            db,
            [changed],
            enrich_projection=True,
            expected_previous={key: digest(original.source_text)},
        )
    assert count(db, CatalogSourceRevision) == 1


@pytest.mark.parametrize("change", ["removed", "normalized_guid", "same_keys", "title"])
def test_enrichment_requires_preserved_raw_proper_superset(db, change):
    original = row(1, Parent_Key="00000000-0000-0000-0000-000000000000", Observed=None)
    load(db, [original])
    db.commit()
    value = json.loads(original.source_text)
    if change == "removed":
        del value["Observed"]
    if change == "normalized_guid":
        value["Parent_Key"] = None
    if change == "title":
        value["Description"] = "Changed"
    if change != "same_keys":
        value["Added"] = True
    changed = SourceRow(
        NOMENCLATURE,
        json.dumps(value, ensure_ascii=False, indent=1 if change == "same_keys" else None),
    )
    key = (NOMENCLATURE, value["Ref_Key"])
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_FIELDS_CHANGED"):
        load(
            db,
            [changed],
            enrich_projection=True,
            expected_previous={key: digest(original.source_text)},
        )
    assert count(db, CatalogSourceRevision) == 1


def test_enrichment_refuses_new_identity_counterparty_new_version_and_chaining(db):
    original, counterparty = row(1), row(2, entity=COUNTERPARTIES)
    load(db, [original, counterparty])
    db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    for changed, options in [
        (row(3, Added=True), {}),
        (row(1, Added=True), {"namespace": "other-copy"}),
        (row(2, entity=COUNTERPARTIES, Added=True), {}),
        (
            row(1, version="v2", Added=True),
            {"expected_previous": {key: digest(original.source_text)}},
        ),
    ]:
        with pytest.raises(CatalogImportConflict, match="ENRICHMENT_REQUIRES_PROJECTION"):
            load(db, [changed], enrich_projection=True, **options)
    full = row(1, Added=True)
    load(db, [full], enrich_projection=True, expected_previous={key: digest(original.source_text)})
    db.commit()
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_REQUIRES_PROJECTION"):
        load(
            db,
            [row(1, Added=True, AddedAgain=True)],
            enrich_projection=True,
            expected_previous={key: digest(full.source_text)},
        )
    assert count(db, CatalogSourceIdentity) == 2 and count(db, CatalogSourceRevision) == 3


def test_enrichment_batch_failure_rolls_back_an_already_enriched_row(db):
    originals = [row(1), row(2)]
    load(db, originals)
    db.commit()
    previous = {
        (NOMENCLATURE, json.loads(v.source_text)["Ref_Key"]): digest(v.source_text)
        for v in originals
    }
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_FIELDS_CHANGED"):
        load(
            db,
            [row(1, Added=True), row(2, Description="Changed", Added=True)],
            enrich_projection=True,
            expected_previous=previous,
        )
    assert count(db, CatalogSourceRevision) == 2
    assert all(
        v.revision_no == 1 and v.source_sha == previous[(v.entity, v.source_guid)]
        for v in db.scalars(select(CatalogSourceIdentity))
    )
    assert all(
        v.attributes["source_catalog"]["observed_shape"] == "projection"
        for v in db.scalars(select(Sku))
    )


@pytest.mark.parametrize("tamper", ["native", "revision"])
def test_enriched_replay_checks_integrity_before_replay(db, tamper):
    original, full = row(1), row(1, Added=True)
    load(db, [original])
    db.commit()
    key = (NOMENCLATURE, json.loads(original.source_text)["Ref_Key"])
    load(db, [full], enrich_projection=True, expected_previous={key: digest(original.source_text)})
    db.commit()
    if tamper == "native":
        db.scalar(select(Sku)).title = "Human change"
        reason = "NATIVE_TARGET_CHANGED"
    else:
        db.scalar(
            select(CatalogSourceRevision).where(CatalogSourceRevision.revision_no == 2)
        ).source_text += " "
        reason = "CURRENT_REVISION_INTEGRITY"
    db.commit()
    with pytest.raises(CatalogImportConflict, match=reason):
        load(db, [full], enrich_projection=True)
    assert count(db, CatalogSourceRevision) == 2


@pytest.mark.parametrize("mode", [1, "true"])
def test_enrichment_mode_is_an_explicit_boolean(db, mode):
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_MODE"):
        load(db, [row(1)], enrich_projection=mode)
    assert count(db, CatalogSourceIdentity) == 0


@pytest.mark.parametrize("folder", [False, True])
def test_archived_invalid_title_target_cannot_be_enriched_or_chained(db, folder):
    original = row(1, folder=folder)
    load(db, [original])
    db.commit()
    key = (NOMENCLATURE, original.parse()[0])
    invalid = row(1, folder=folder, version="v2", Description="")
    load(db, [invalid], expected_previous={key: digest(original.source_text)})
    db.commit()
    identity = db.scalar(select(CatalogSourceIdentity))
    before = (
        identity.id,
        identity.sku_id,
        identity.group_id,
        identity.source_sha,
        identity.target_sha,
        identity.revision_no,
        list(identity.holds),
    )
    target = db.scalar(select(NomenclatureCategory if folder else Sku))
    native_before = {
        column.name: getattr(target, column.name) for column in target.__table__.columns
    }
    assert not target.is_active and "NATIVE_TITLE_INVALID" in identity.holds
    changed = row(1, folder=folder, version="v2", Description="", Added=True)
    with pytest.raises(CatalogImportConflict, match="ENRICHMENT_REQUIRES_PROJECTION"):
        load(
            db,
            [changed],
            enrich_projection=True,
            expected_previous={key: digest(invalid.source_text)},
        )
    assert (
        identity.id,
        identity.sku_id,
        identity.group_id,
        identity.source_sha,
        identity.target_sha,
        identity.revision_no,
        identity.holds,
    ) == before
    assert {
        column.name: getattr(target, column.name) for column in target.__table__.columns
    } == native_before
    assert load(db, [invalid], enrich_projection=True)["replayed"] == 1
    assert count(db, CatalogSourceRevision) == 2
