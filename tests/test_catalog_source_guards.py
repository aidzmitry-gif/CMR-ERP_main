"""Untrusted 1C catalogue inputs must fail atomically with bounded error codes."""
# ruff: noqa: F811 -- import the existing dedicated SQLite fixture.
import json

import pytest

from core.domain.models import CatalogSourceIdentity, CatalogSourceRevision, Sku
from core.services.native_catalog_import import (
    NOMENCLATURE,
    CatalogImportConflict,
    SourceRow,
    guid,
    import_catalog,
)
from tests.test_native_catalog_import import count, row
from tests.test_native_catalog_import import db as catalog_db  # noqa: F401


@pytest.mark.parametrize("value, code", [
    (None, "GUID_TYPE"), (7, "GUID_TYPE"), (True, "GUID_TYPE"),
    ("synthetic-invalid-guid", "GUID_INVALID"),
    ("00000000-0000-0000-0000-000000000000", "GUID_ZERO"),
])
def test_source_guid_rejects_types_garbage_and_zero(value, code):
    with pytest.raises(CatalogImportConflict) as error:
        guid(value)
    assert str(error.value) == code


@pytest.mark.parametrize("text, code", [
    (None, "SOURCE_ROW_SIZE"), (123, "SOURCE_ROW_SIZE"),
    ("я" * (1024 * 1024 + 1), "SOURCE_ROW_SIZE"),
    ("{synthetic-malformed", "SOURCE_JSON"), ("[]", "SOURCE_ROW_TYPE"),
    ("null", "SOURCE_ROW_TYPE"),
    ('{"Ref_Key":"SYNTHETIC_PRIVATE_VALUE","Ref_Key":"duplicate"}', "DUPLICATE_JSON_KEY"),
    ('{"number":NaN}', "JSON_NONFINITE"),
    ('{"number":Infinity}', "JSON_NONFINITE"),
], ids=["none", "integer", "over-2mb-utf8", "malformed", "array", "null", "duplicate-key", "nan", "infinity"])
def test_source_parser_returns_only_safe_code_for_untrusted_json(text, code):
    with pytest.raises(CatalogImportConflict) as error:
        SourceRow(NOMENCLATURE, text).parse()
    assert str(error.value) == code
    assert "SYNTHETIC_PRIVATE_VALUE" not in str(error.value)


@pytest.mark.parametrize("changes, code", [
    ({"DataVersion": None}, "SOURCE_DATA_VERSION"),
    ({"DataVersion": ""}, "SOURCE_DATA_VERSION"),
    ({"DataVersion": "v" * 256}, "SOURCE_DATA_VERSION"),
    ({"Description": None}, "SOURCE_NAME_CODE"),
    ({"Description": 5}, "SOURCE_NAME_CODE"),
    ({"DeletionMark": 0}, "SOURCE_TOMBSTONE"),
    ({"DeletionMark": "false"}, "SOURCE_TOMBSTONE"),
    ({"IsFolder": 0}, "SOURCE_FOLDER"),
    ({"IsFolder": "false"}, "SOURCE_FOLDER"),
    ({"Parent_Key": "synthetic-invalid-parent"}, "GUID_INVALID"),
    ({"ЕдиницаИзмерения_Key": "synthetic-invalid-unit"}, "GUID_INVALID"),
])
def test_bad_second_source_row_cannot_partially_import_first(catalog_db, changes, code):
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, "synthetic:1c", [row(1), row(2, **changes)], actor="synthetic-test")
    assert str(error.value) == code
    assert count(catalog_db, CatalogSourceIdentity) == count(catalog_db, CatalogSourceRevision) == 0
    assert count(catalog_db, Sku) == 0


@pytest.mark.parametrize("namespace, actor", [
    (None, "synthetic-test"), ("", "synthetic-test"), ("n" * 65, "synthetic-test"),
    ("synthetic:1c", None), ("synthetic:1c", ""), ("synthetic:1c", "a" * 129),
])
def test_import_scope_is_explicit_bounded_and_never_coerced(catalog_db, namespace, actor):
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, namespace, [row(1)], actor=actor)
    assert str(error.value) == "IMPORT_SCOPE"
    assert count(catalog_db, CatalogSourceIdentity) == count(catalog_db, Sku) == 0


@pytest.mark.parametrize("records", [[], [row(1)] * 30001])
def test_empty_or_oversized_batch_never_starts_import(catalog_db, records):
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, "synthetic:1c", records, actor="synthetic-test")
    assert str(error.value) == "BATCH_SIZE"
    assert count(catalog_db, CatalogSourceIdentity) == 0


def test_unrelated_pending_manual_sku_is_not_flushed_by_import(catalog_db):
    manual = Sku(code="synthetic-manual", title="Synthetic pending manual item")
    catalog_db.add(manual)
    pending = set(catalog_db.new)
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, "synthetic:1c", [row(1)], actor="synthetic-test")
    assert str(error.value) == "CLEAN_SESSION_REQUIRED"
    assert set(catalog_db.new) == pending and manual.id is None


def test_excessive_source_tree_depth_is_atomic(catalog_db):
    # Descending keys force one traversal to reach the documented 128-node bound.
    records = [row(n, folder=True, parent=n + 1 if n < 129 else None) for n in range(1, 130)]
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, "synthetic:1c", records, actor="synthetic-test")
    assert str(error.value) == "GROUP_DEPTH_LIMIT"
    assert count(catalog_db, CatalogSourceIdentity) == count(catalog_db, CatalogSourceRevision) == 0


def test_unknown_source_entity_is_not_imported(catalog_db):
    incoming = SourceRow("Catalog_SYNTHETIC_PRIVATE_VALUE", json.dumps({}))
    with pytest.raises(CatalogImportConflict) as error:
        import_catalog(catalog_db, "synthetic:1c", [incoming], actor="synthetic-test")
    assert str(error.value) == "SOURCE_ENTITY"
    assert count(catalog_db, CatalogSourceIdentity) == 0
