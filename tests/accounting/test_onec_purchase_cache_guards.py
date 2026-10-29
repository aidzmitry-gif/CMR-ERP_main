"""Untrusted 1C purchase caches and maps cannot produce a partial draft plan."""
import hashlib
import json
from copy import deepcopy

import pytest

from modules.accounting import onec_purchase_import as imports
from tests.accounting.test_onec_purchase_import import mapping as mapping
from tests.accounting.test_onec_purchase_import import metadata as metadata
from tests.accounting.test_onec_purchase_import import source_doc as source_doc


def write_cache(path, payload=b"{}\n", **changes):
    meta = {"schema_version": imports.CACHE_SCHEMA, "source_system": "onec",
            "entity": "Document_SyntheticPurchase", "date_from": "2026-09-01",
            "date_to": "2026-10-01", "record_count": 1,
            "source_sha256": hashlib.sha256(payload).hexdigest(), **changes}
    (path / "onec_purchases.jsonl").write_bytes(payload)
    (path / "onec_purchases.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


@pytest.mark.parametrize(("changes", "message"), [
    ({"schema_version": "unrecognized-cache"}, "unsupported schema"),
    ({"source_system": "unknown"}, "source_system"),
    ({"record_count": True}, "nonnegative integer"),
    ({"record_count": -1}, "nonnegative integer"),
    ({"record_count": 2}, "record count does not match"),
    ({"entity": None}, "missing entity"),
    ({"date_from": None}, "missing date_from"),
    ({"date_to": ""}, "missing date_to"),
    ({"date_from": "2026-10-01", "date_to": "2026-09-01"}, "invalid date window"),
])
def test_sidecar_cannot_claim_unverified_rows(tmp_path, changes, message):
    write_cache(tmp_path, **changes)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(imports.PurchaseImportError, match=message):
        imports.load_verified_cache(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize(("payload", "message"), [
    (b"\xff\n", "invalid JSONL"), (b"{bad-json}\n", "invalid JSONL"),
    (b"[]\n", "JSON objects"), (b"null\n", "JSON objects"),
])
def test_correct_digest_does_not_certify_corrupt_cache(tmp_path, payload, message):
    write_cache(tmp_path, payload)
    with pytest.raises(imports.PurchaseImportError, match=message):
        imports.load_verified_cache(tmp_path)
    assert (tmp_path / "onec_purchases.jsonl").read_bytes() == payload


@pytest.mark.parametrize("kind", ["missing", "bad_json", "nonobject"])
def test_missing_or_malformed_sidecar_has_a_typed_refusal(tmp_path, kind):
    if kind != "missing":
        write_cache(tmp_path)
        (tmp_path / "onec_purchases.meta.json").write_bytes(b"{bad-json}" if kind == "bad_json" else b"[]")
    with pytest.raises(imports.PurchaseImportError):
        imports.load_verified_cache(tmp_path)


@pytest.mark.parametrize(("key", "value", "message"), [
    ("schema_version", "unrecognized-map", "unsupported"),
    ("organization_id", True, "positive integer"),
    ("organization_id", 0, "positive integer"),
    ("entity", "Catalog_Items", "Document_"),
    ("entity", "Document_", "unsupported OData"),
    ("entity", "Document_Bad/Path", "unsupported OData"),
    ("entity", "Document_" + "A" * 181, "exceeds"),
    ("entity", "Document_Bad\x7fName", "control character"),
    ("currency_refs", {}, "at least one"),
    ("paths", [], "must be an object"),
])
def test_mapping_cannot_guess_identity_or_entity(mapping, key, value, message):
    bad = deepcopy(mapping)
    bad[key] = value
    with pytest.raises(imports.PurchaseImportError, match=message):
        imports.validate_mapping_profile(bad)


def test_document_date_cannot_be_redirected_to_an_unreviewed_date(mapping):
    mapping["paths"]["document"]["document_date"] = "/OperationDate"
    with pytest.raises(imports.PurchaseImportError, match="system Date field"):
        imports.validate_mapping_profile(mapping)


@pytest.mark.parametrize("row", [None, [], {"Ref_Key": " padded "}, {"Ref_Key": None}])
def test_unstable_source_identity_blocks_entire_package(mapping, source_doc, metadata, row):
    before = deepcopy(source_doc)
    with pytest.raises(imports.UnmappedPurchaseDocuments):
        imports.build_receipt_drafts([source_doc, row], metadata, mapping)
    assert source_doc == before


@pytest.mark.parametrize("value", [None, "2026/09/12", "2026-02-30", "2026-09-12Tbad-time"])
def test_unreviewed_source_date_blocks_package(mapping, source_doc, metadata, value):
    source_doc["Date"] = value
    with pytest.raises(imports.UnmappedPurchaseDocuments):
        imports.build_receipt_drafts([source_doc], metadata, mapping)


def test_reversed_month_does_not_map_any_document(mapping, source_doc, metadata):
    with pytest.raises(imports.PurchaseImportError, match="date window"):
        imports.build_receipt_drafts([source_doc], {**metadata, "date_from": metadata["date_to"]}, mapping)


@pytest.mark.parametrize("index", ["0", "1"])
def test_list_pointer_requires_an_existing_exact_index(mapping, source_doc, metadata, index):
    source_doc["ExplicitSupplierRefs"] = [source_doc["Контрагент_Key"]]
    mapping["paths"]["document"]["supplier_ref"] = "/ExplicitSupplierRefs/" + index
    if index == "0":
        draft, = imports.build_receipt_drafts([source_doc], metadata, mapping)
        assert draft["document"]["supplier_id"] == mapping["suppliers"][source_doc["Контрагент_Key"]]["id"]
    else:
        with pytest.raises(imports.UnmappedPurchaseDocuments) as error:
            imports.build_receipt_drafts([source_doc], metadata, mapping)
        assert "out of range" in error.value.issues[0]["reason"]


def test_invalid_decimal_is_not_coerced_to_zero(mapping, source_doc, metadata):
    source_doc["Товары"][0]["СуммаБезНДС"] = "not-a-decimal"
    with pytest.raises(imports.UnmappedPurchaseDocuments) as error:
        imports.build_receipt_drafts([source_doc], metadata, mapping)
    assert "not a valid decimal" in error.value.issues[0]["reason"]


def test_existing_plan_cannot_be_replaced_by_different_bytes(tmp_path):
    path = tmp_path / "owned-plan.jsonl"
    path.write_bytes(b"original synthetic plan")
    with pytest.raises(imports.PurchaseImportError, match="refusing to replace"):
        imports._write_once(path, b"different synthetic plan")
    assert path.read_bytes() == b"original synthetic plan"


def test_another_writers_temporary_plan_is_preserved(tmp_path):
    path = tmp_path / "owned-plan.jsonl"
    temporary = tmp_path / "owned-plan.jsonl.tmp"
    temporary.write_bytes(b"other synthetic writer")
    with pytest.raises(imports.PurchaseImportError, match="another plan writer"):
        imports._write_once(path, b"new synthetic plan")
    assert not path.exists() and temporary.read_bytes() == b"other synthetic writer"


def test_failed_plan_replace_cleans_only_its_own_temporary_file(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "owned-plan.jsonl"

    def failed_replace(self, target):
        raise OSError("Synthetic failed atomic replace")

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError, match="Synthetic failed"):
        imports._write_once(path, b"new synthetic plan")
    assert list(tmp_path.iterdir()) == []
