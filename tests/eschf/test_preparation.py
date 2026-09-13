"""Offline acceptance tests; no ERP database, credentials or portal access."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from modules.eschf.__main__ import SCHEMA_SHA256
from modules.eschf.preparation import (
    NS,
    Candidate,
    PartySelection,
    PartySnapshot,
    canonical,
    check_existing,
    prepare,
    resolve_party,
    sha256,
    validate_xsd,
)


def party(entity=1, branch=None, code=None):
    return PartySnapshot(
        legal_entity_id=entity, branch_id=branch,
        legal_entity_revision=3, branch_revision=2 if branch else None,
        branch_legal_entity_id=entity if branch else None,
        display_name=f"ДЕМО предприятие {entity}", legal_name=f"ООО «ДЕМО {entity}»",
        legal_entity_unp=f"{entity}00000000", taxpayer_unp=f"{entity}00000000",
        taxpayer_name=f"ООО «ДЕМО {entity}»", taxpayer_address="ДЕМО адрес",
        branch_name=f"ДЕМО филиал {branch}" if branch else None,
        branch_tax_mode="shared" if branch else "head", portal_branch_code=code,
        reference_evidence_ref="synthetic-fixture:2026-09-09:revision3",
        dependent_person=False, residents_of_offshore=False, special_deal_goods=False,
        big_company=False,
    )


def bundle(provider=None, recipient=None):
    source = {
        "document_id": 10, "version": 2, "kind": "invoice", "currency": "BYN",
        "amount": "240.00", "items": [{"name": "ДЕМО услуга & <работа>",
            "qty": "2.000", "price": "100.0000", "vat_rate": "20", "net": "200.00",
            "tax": "40.00", "total": "240.00"}],
    }
    html = "<h1>ДЕМО оригинал</h1>"
    provider, recipient = provider or party(1), recipient or party(2, 21, "0007")
    draft = Candidate(
        environment="offline", document_type="ORIGINAL", source_document_id=10,
        source_document_version=2, source_content_sha256=sha256(html.encode()),
        source_snapshot_sha256=sha256(canonical(source)), number="100000000-2026-0000000001",
        issuance_year=2026, transaction_date="2026-09-08", provider=provider,
        recipient=recipient, lines=({"kind": "service", "name": source["items"][0]["name"],
            "quantity": "2", "price": "100", "vat_rate": "20"},),
        basis_description="ДЕМО акт выполненных работ №1 от 08.09.2026",
    )
    return draft, source, html, (provider, recipient)


def changed(model, **values):
    return type(model).model_validate({**model.model_dump(), **values})


def test_xml_matches_official_schema_and_preserves_party_identity():
    result = prepare(*bundle())
    path = Path("modules/eschf/xsd/MNSATI_original.xsd")
    validate_xsd(result.unsigned_xml, path, SCHEMA_SHA256)
    root = ET.fromstring(result.unsigned_xml)
    ns = {"e": NS}
    assert root.findtext("e:recipient/e:branchCode", namespaces=ns) == "0007"
    assert root.findtext("e:recipient/e:name", namespaces=ns) == "ООО «ДЕМО 2»"
    assert root.find("e:general/e:dateIssuance", ns) is None
    assert root.findtext("e:roster/e:rosterItem/e:name", namespaces=ns) == "ДЕМО услуга & <работа>"
    assert root.find("e:roster", ns).attrib["totalCostVat"] == "240.00"
    assert b"Signature" not in result.unsigned_xml
    assert json.loads(result.snapshot)["recipient"]["branch_id"] == 21


@pytest.mark.parametrize("changes", [
    {"branch_legal_entity_id": 9}, {"branch_id": None}, {"branch_revision": None},
    {"portal_branch_code": "7"}, {"portal_branch_code": 7}, {"portal_branch_code": "０００７"},
    {"branch_tax_mode": "unknown"}, {"branch_tax_mode": "independent"},
    {"taxpayer_unp": "900000000"}, {"taxpayer_name": "Название для системы"},
    {"legal_name": "  "}, {"taxpayer_address": "a\x00b"}, {"big_company": "false"},
])
def test_invalid_party_is_blocked(changes):
    with pytest.raises(ValidationError):
        changed(party(2, 21, "0007"), **changes)


def test_head_cannot_impersonate_a_branch():
    with pytest.raises(ValidationError):
        changed(party(), portal_branch_code="0007")


def test_same_unp_distinct_branches_are_not_duplicates():
    draft, source, html, refs = bundle(party(1, 11, "0001"), party(1, 12, "0002"))
    assert prepare(draft, source, html, refs).unsigned_xml
    with pytest.raises(ValidationError, match="equal taxpayer"):
        changed(draft, recipient=party(1, 11, "0001"))
    with pytest.raises(ValidationError, match="equal taxpayer"):
        bundle(party(1), party(1))


def test_stale_revision_untrusted_fields_and_ambiguous_reference():
    draft, source, html, refs = bundle()
    updated = changed(refs[1], branch_revision=3)
    with pytest.raises(ValueError, match="stale party"):
        prepare(draft, source, html, (refs[0], updated))
    with pytest.raises(ValueError, match="trusted directory"):
        prepare(draft, source, html, (refs[0], changed(refs[1], taxpayer_address="Another")))
    selection = PartySelection(legal_entity_id=2, branch_id=21,
                               legal_entity_revision=3, branch_revision=2)
    for records in ((), (refs[1], refs[1])):
        with pytest.raises(ValueError, match="missing or ambiguous"):
            resolve_party(selection, records)


def test_snapshot_survives_rename_and_source_mutation():
    draft, source, html, refs = bundle()
    result = prepare(draft, source, html, refs)
    before = result.snapshot
    source["items"][0]["name"] = "Changed later"
    renamed = changed(refs[1], display_name="Новое рабочее название")
    assert renamed.display_name != refs[1].display_name
    assert result.snapshot == before and sha256(before) == result.snapshot_sha256
    with pytest.raises(FrozenInstanceError):
        result.snapshot = b"{}"
    with pytest.raises(ValidationError):
        draft.recipient.legal_name = "Changed"


@pytest.mark.parametrize("field,value", [("document_id", 11), ("version", 3),
                                         ("amount", "240.01"), ("currency", "USD")])
def test_source_binding(field, value):
    draft, source, html, refs = bundle()
    source[field] = value
    with pytest.raises(ValueError, match="source snapshot"):
        prepare(draft, source, html, refs)


def test_original_and_financial_mismatch():
    draft, source, html, refs = bundle()
    with pytest.raises(ValueError, match="original hash"):
        prepare(draft, source, html + "changed", refs)
    source["items"][0]["price"] = "101.00"
    draft = changed(draft, source_snapshot_sha256=sha256(canonical(source)))
    with pytest.raises(ValueError, match="source line"):
        prepare(draft, source, html, refs)


def test_replay_and_number_collision():
    args = bundle()
    first = prepare(*args)
    assert check_existing(first, prepare(*args)) == "replay"
    draft, source, html, refs = args
    other = prepare(changed(draft, basis_description="New basis"), source, html, refs)
    with pytest.raises(ValueError, match="different snapshot"):
        check_existing(first, other)
    other = prepare(changed(draft, number="100000000-2026-0000000002"), source, html, refs)
    with pytest.raises(ValueError, match="different ESCHF"):
        check_existing(first, other)


@pytest.mark.parametrize("changes", [
    {"quantity": "NaN"}, {"price": "Infinity"}, {"quantity": "0"}, {"price": "-1"},
    {"price": 0.1}, {"quantity": True}, {"kind": "goods"}, {"vat_rate": "0"},
])
def test_out_of_scope_or_unsafe_money_is_blocked(changes):
    draft, *_ = bundle()
    with pytest.raises(ValidationError):
        changed(draft, lines=[{**draft.lines[0].model_dump(), **changes}])


@pytest.mark.parametrize("changes", [
    {"environment": "production"}, {"document_type": "FIXED"},
    {"number": "900000000-2026-0000000001"}, {"issuance_year": 2025}, {"lines": []},
])
def test_unsupported_candidate_is_blocked(changes):
    with pytest.raises(ValidationError):
        changed(bundle()[0], **changes)


def test_schema_hash_entities_and_invalid_xml_are_blocked(tmp_path):
    from lxml import etree

    schema = Path("modules/eschf/xsd/MNSATI_original.xsd")
    result = prepare(*bundle())
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        validate_xsd(result.unsigned_xml, schema, "0" * 64)
    with pytest.raises(ValueError, match="DTD/entities"):
        validate_xsd(b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x/>',
                     schema, SCHEMA_SHA256)
    with pytest.raises(etree.DocumentInvalid):
        validate_xsd(b"<wrong/>", schema, SCHEMA_SHA256)
    remote = tmp_path / "schema.xsd"
    data = b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="file:///secret"/></xs:schema>'
    remote.write_bytes(data)
    with pytest.raises(ValueError, match="external schema"):
        validate_xsd(result.unsigned_xml, remote, sha256(data))


def test_cli_creates_an_explicitly_unsigned_preview_and_never_overwrites(tmp_path, monkeypatch):
    from modules.eschf.__main__ import main

    draft, source, html, records = bundle()
    payload = {"candidate": draft.model_dump(mode="json"), "source_snapshot": source,
               "source_original_html": html,
               "reference_records": [p.model_dump(mode="json") for p in records]}
    src = tmp_path / "bundle.json"
    src.write_bytes(canonical(payload))
    target = tmp_path / "preview"
    monkeypatch.setattr("sys.argv", ["eschf", str(src), "--out", str(target)])
    main()
    result = json.loads((target / "preview.json").read_text(encoding="utf-8"))
    assert result["xsd_valid"] is True
    assert result["signed"] is False and result["sent"] is False
    assert result["portal_dictionary_verified"] is False
    assert result["snapshot_sha256"] == sha256((target / "snapshot.json").read_bytes())
    with pytest.raises(FileExistsError):
        main()
