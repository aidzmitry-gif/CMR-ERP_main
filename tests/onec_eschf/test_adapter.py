"""Synthetic local checks only: no 1C platform, tax approval or native XML execution."""

import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from lxml import etree
from pydantic import ValidationError

from integrations.onec_eschf import adapter as adapter_module
from integrations.onec_eschf.adapter import (
    NS,
    AdapterError,
    Binding,
    Identity,
    LocalEnvelope,
    NativeCapture,
    NativeResult,
    NativeRow,
    Selection,
    SourceOriginal,
    canonical,
    capture_local,
    compare_local,
    row_values,
    sha256,
    validate_binding,
)

FIXTURE = Path(__file__).parent / "fixtures/original-p02.xml"


@pytest.fixture(scope="module")
def pinned_schema():
    path = Path(__file__).parents[2] / "modules/eschf/xsd/MNSATI_original.xsd"
    return etree.XMLSchema(etree.parse(str(path), etree.XMLParser(no_network=True)))


def identity(metadata, suffix, base="synthetic-isolated-ib"):
    return Identity(information_base_id=base, metadata_object=metadata,
                    reference=f"10000000-0000-0000-0000-{suffix:012d}")


def row(**changes):
    data = dict(source_kind="native_invoice_row", number=1, name="Синтетическая строка",
                quantity="1", price="100", net="100", vat="20", gross="120", excise="0",
                native_rate="20", vat_kind="ordinary", calculated=False,
                tnved=None, oked=None, unit_code=None)
    data.update(changes)
    return NativeRow(**data)


def setup_case(rows=None, *, shared=False):
    rows = tuple(rows or [row()])
    selection = Selection(
        legal_entity_id=101, legal_entity_revision=3,
        branch_id=201 if shared else None, branch_revision=4 if shared else None,
        branch_legal_entity_id=101 if shared else None,
        branch_tax_mode="shared" if shared else "head",
        portal_branch_code="0007" if shared else None)
    party = selection.model_dump()
    if not shared:
        party["branch_tax_mode"] = None  # Exact CP head normalization contract.
    party.update(identity_status="selected", display_name="Одинаковое имя",
                 legal_name="Синтетический получатель", legal_entity_unp="111111111")
    snapshot = {"schema_version": 1, "document_id": 301, "version": 1, "party": party,
                "seller": {"name": "Синтетический поставщик", "unp": "123456789"},
                "items": [{"name": r.name, "qty": r.quantity, "price": r.price,
                           "net": r.net, "tax": r.vat, "total": r.gross} for r in rows],
                "amount": str(sum(Decimal(r.gross) for r in rows))}
    html = "<p>Синтетический неизменяемый оригинал</p>"
    source = SourceOriginal(document_id=301, version=1, content_sha256=sha256(html.encode()),
                            snapshot=snapshot, original_html=html, issued=True, superseded=False)
    native = NativeCapture(
        invoice=identity("Document.СчетФактураВыданный", 1),
        provider=identity("Catalog.Организации", 2), recipient=identity("Catalog.Контрагенты", 3),
        basis=identity("Document.РеализацияТоваровУслуг", 4),
        number="123456789-2026-0000000001", posted=True, summary=False,
        document_type="ORIGINAL", rows=rows,
        captured_dependencies={"invoice_version_observed": "AAAAAAAAAAA=",
                               "legal_address": "Синтетический адрес",
                               "fixture_only": True})
    binding = binding_for(source, native, selection)
    return source, binding, native


def binding_for(source, native, selection):
    return Binding(source_document_id=source.document_id, source_document_version=source.version,
                   source_content_sha256=source.content_sha256,
                   source_snapshot_sha256=sha256(canonical(source.snapshot)),
                   seller_snapshot_sha256=sha256(canonical(source.snapshot["seller"])),
                   recipient_selection=selection, invoice=native.invoice, provider=native.provider,
                   recipient=native.recipient, basis=native.basis,
                   native_capture_sha256=sha256(canonical(native.model_dump(mode="json"))),
                   reconciliation_evidence_ref="synthetic-reconciliation-fixture-v1",
                   provider_evidence_ref="synthetic-provider-selection-v1")


def synthetic_xml(native):
    # Test-only data variants of an independent hand-written, XSD-checked fixture.
    # Do not use row_values or any adapter XML generation/shape decisions here.
    ET.register_namespace("", NS)
    root = ET.fromstring(FIXTURE.read_bytes())
    root.find(f"{{{NS}}}general/{{{NS}}}number").text = native.number
    roster = root.find(f"{{{NS}}}roster")
    for existing in list(roster):
        roster.remove(existing)
    for item in native.rows:
        node = ET.SubElement(roster, f"{{{NS}}}rosterItem")
        # Explicit order from the pinned XSD, independent of the adapter's mapping.
        fields = [("number", str(item.number)), ("name", item.name),
                  ("code", item.tnved), ("code_oced", item.oked),
                  ("units", str(int(item.unit_code)) if item.unit_code and
                   item.unit_code.strip() else None),
                  ("count", item.quantity), ("price", item.price),
                  ("cost", item.net), ("summaExcise", item.excise)]
        for name, value in fields:
            if value is not None:
                ET.SubElement(node, f"{{{NS}}}{name}").text = value
        vat = ET.SubElement(node, f"{{{NS}}}vat")
        rate_type = {"ordinary": "DECIMAL", "zero": "ZERO", "no_vat": "NO_VAT"}[item.vat_kind]
        if item.calculated:
            rate_type = "CALCULATED"
        for name, value in (("rate", item.native_rate), ("rateType", rate_type),
                            ("summaVat", item.vat)):
            ET.SubElement(vat, f"{{{NS}}}{name}").text = value
        ET.SubElement(node, f"{{{NS}}}costVat").text = item.gross
    for name, field in (("totalCost", "net"), ("totalVat", "vat"),
                        ("totalExcise", "excise"), ("totalCostVat", "gross")):
        roster.set(name, str(sum(Decimal(getattr(r, field)) for r in native.rows)))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def result_for(native, payload, **changes):
    data = dict(status="candidate", xml_text=payload.decode("utf-8"), number=native.number,
                native_error="", refusal=False, diagnostic_capture="unresolved", native_messages=())
    data.update(changes)
    return NativeResult(**data)


def capture(case, payload=None, result=None, codec="utf-8"):
    source, binding, native = case
    payload = synthetic_xml(native) if payload is None else payload
    result = result_for(native, payload) if result is None else result
    return capture_local(source, binding, native, result, payload, codec=codec,
                         byte_evidence_ref="synthetic-codec-hypothesis-only")


# Independent expected values, not expectations derived from the adapter implementation.
TAX_CASES = [
    ("P01", [row(quantity="2", net="200", vat="40", gross="240", tnved="8506501000",
                  unit_code="796 ")], "DECIMAL", "20", "240"),
    ("P02", [row()], "DECIMAL", "20", "120"),
    ("P03", [row(vat_kind="zero", native_rate="0", vat="0", gross="100")],
     "ZERO", "0", "100"),
    ("P04", [row(vat_kind="no_vat", native_rate="0", vat="0", gross="100")],
     "NO_VAT", "0", "100"),
    ("P05", [row(calculated=True, native_rate="16.6667")], "CALCULATED", "16.6667", "120"),
    ("P06", [row(quantity="2", net="200", vat="40", gross="240"),
             row(number=2, vat_kind="no_vat", native_rate="0", vat="0", gross="100")],
     "DECIMAL", "20", "340"),
    ("P07", [row(excise="5", vat="21", gross="126")], "DECIMAL", "20", "126"),
    ("P08", [row(oked="62010", unit_code="798 ")], "DECIMAL", "20", "120"),
]


@pytest.mark.parametrize("case_id,rows,rate_type,rate,gross", TAX_CASES, ids=[c[0] for c in TAX_CASES])
def test_tax_values_are_preserved(case_id, rows, rate_type, rate, gross, pinned_schema):
    case = setup_case(rows)
    envelope = capture(case)
    pinned_schema.assertValid(etree.fromstring(envelope.xml_bytes))
    first = row_values(rows[0])
    assert first["vat/rateType"] == rate_type
    assert first["vat/rate"] == rate
    assert sum(Decimal(r.gross) for r in rows) == Decimal(gross)
    assert envelope.verification_scope == "local_envelope_only"
    if case_id == "P01":
        assert first["code"] == "8506501000" and first["units"] == "796"
    if case_id == "P02":
        assert not {"code", "code_oced", "units"} & first.keys()
    if case_id == "P06":
        assert row_values(rows[1])["vat/rateType"] == "NO_VAT"
    if case_id == "P07":
        assert (first["summaExcise"], first["vat/summaVat"], first["costVat"]) == ("5", "21", "126")
    if case_id == "P08":
        assert first["code_oced"] == "62010" and first["units"] == "798"


def test_native_calculated_rate_has_priority_and_no_numeric_rate_whitelist():
    assert row_values(row(calculated=True, vat_kind="no_vat"))["vat/rateType"] == "CALCULATED"
    assert row_values(row(native_rate="10"))["vat/rate"] == "10"
    assert "units" not in row_values(row(unit_code=" "))


@pytest.mark.parametrize("shared", [False, True], ids=["F01-head", "F02-shared"])
def test_explicit_recipient_selection(shared):
    case = setup_case(shared=shared)
    capture(case)
    if shared:
        assert case[1].recipient_selection.portal_branch_code == "0007"


def test_F03_foreign_branch_is_rejected():
    selection = setup_case(shared=True)[1].recipient_selection.model_dump()
    selection["branch_legal_entity_id"] = 102
    with pytest.raises(ValidationError, match="shared branch"):
        Selection(**selection)


def test_F04_stale_revision_against_supplied_resolved_selection():
    source, binding, native = setup_case()
    data = binding.model_dump()
    data["recipient_selection"]["legal_entity_revision"] = 4
    with pytest.raises(AdapterError, match="recipient_selection_mismatch"):
        capture((source, Binding(**data), native))


@pytest.mark.parametrize("case_id", ["F05-name-only", "F13-party-substitution"])
def test_same_name_does_not_authorize_another_recipient(case_id):
    source, binding, native = setup_case()
    data = binding.model_dump()
    data["recipient_selection"]["legal_entity_id"] = 102
    with pytest.raises(AdapterError, match="recipient_selection_mismatch"):
        capture((source, Binding(**data), native))


@pytest.mark.parametrize("mode", ["unknown", "independent"])
def test_F06_unproven_branch_mode(mode):
    values = setup_case(shared=True)[1].recipient_selection.model_dump()
    values["branch_tax_mode"] = mode
    with pytest.raises(ValidationError):
        Selection(**values)


def test_F07_replaced_or_unissued_original():
    case = setup_case()
    for changes in ({"superseded": True}, {"issued": False}, {"version": 2}):
        with pytest.raises(AdapterError):
            capture((case[0].model_copy(update=changes), *case[1:]))


def test_F08_one_original_byte_changed():
    source, binding, native = setup_case()
    with pytest.raises(AdapterError, match="source_content_hash_mismatch"):
        capture((source.model_copy(update={"original_html": source.original_html + " "}), binding,
                 native))


def test_F09_native_reference_is_scoped_to_information_base():
    source, binding, native = setup_case()
    other = native.invoice.model_copy(update={"information_base_id": "other-ib"})
    with pytest.raises(AdapterError, match="native_identity_mismatch"):
        capture((source, binding, native.model_copy(update={"invoice": other})))


def test_F10_malformed_rate_is_not_resolved_from_caption():
    with pytest.raises(ValidationError):
        row(native_rate="20%")


def test_F11_provider_requires_native_identity_and_selection_evidence():
    source, binding, native = setup_case()
    with pytest.raises(ValidationError):
        Binding(**(binding.model_dump() | {"provider_evidence_ref": ""}))
    data = binding.model_dump()
    data["provider"]["metadata_object"] = "Branding"
    with pytest.raises(AdapterError, match="native_identity_mismatch"):
        capture((source, Binding(**data), native))


def test_F12_canonical_snapshot_hash_is_distinct_from_html_and_other_json_format():
    source, binding, native = setup_case()
    data = binding.model_dump()
    data["source_snapshot_sha256"] = sha256(json.dumps(source.snapshot, indent=2).encode())
    with pytest.raises(AdapterError, match="source_snapshot_hash_mismatch"):
        capture((source, Binding(**data), native))
    assert binding.source_snapshot_sha256 != source.content_sha256


@pytest.mark.parametrize("missing", ["party", "revision"])
def test_F14_legacy_schema_one_is_not_cp_selection(missing):
    source, binding, native = setup_case()
    snapshot = deepcopy(source.snapshot)
    if missing == "party":
        del snapshot["party"]
    else:
        del snapshot["party"]["legal_entity_revision"]
    source = source.model_copy(update={"snapshot": snapshot})
    binding = binding.model_copy(update={"source_snapshot_sha256": sha256(canonical(snapshot))})
    with pytest.raises((AdapterError, ValidationError)):
        capture((source, binding, native))


def test_F15_no_service_coercion_or_silent_source_rounding():
    with pytest.raises(ValidationError):
        row(source_kind="service")
    with pytest.raises(ValidationError):
        row(quantity=0.1)
    source, binding, native = setup_case()
    snapshot = deepcopy(source.snapshot)
    snapshot["amount"] = "119.99"
    with pytest.raises(AdapterError, match="source_snapshot_hash_mismatch"):
        capture((source.model_copy(update={"snapshot": snapshot}), binding, native))


@pytest.mark.parametrize("changes", [
    {"status": "native_failure", "native_error": "Точный текст\r\nошибки", "refusal": True},
    {"status": "native_empty_result", "xml_text": None},
    {"status": "candidate", "native_error": "XDTO property failure"},
    {"status": "candidate", "refusal": True},
    {"status": "unsupported_scenario"},
])
def test_native_failure_is_never_an_envelope(changes):
    case = setup_case()
    payload = synthetic_xml(case[2])
    result = result_for(case[2], payload, **changes)
    assert result.native_error == changes.get("native_error", "")
    with pytest.raises(AdapterError, match="native_result_failed"):
        capture(case, payload, result)


def test_exact_bytes_bom_and_whitespace_are_preserved_not_reserialized():
    case = setup_case()
    payload = synthetic_xml(case[2]).replace(b"><", b">\r\n<")
    envelope = capture(case, payload)
    assert envelope.xml_bytes == payload
    assert envelope.xml_sha256 == sha256(payload)
    result = result_for(case[2], payload)
    with_bom = capture(case, b"\xef\xbb\xbf" + payload, result, codec="utf-8-sig")
    assert with_bom.xml_sha256 != envelope.xml_sha256
    with pytest.raises(AdapterError, match="native_bom_mismatch"):
        capture(case, b"\xef\xbb\xbf" + payload, result)
    with pytest.raises(AdapterError, match="native_text_bytes_mismatch"):
        capture(case, payload + b" ", result)


@pytest.mark.parametrize("change,code", [
    (lambda b: b.replace(b"<cost>100</cost>", b"<cost>99</cost>"), "native_xml_amount_mismatch"),
    (lambda b: b.replace(b"</issuance>", b"<Signature /></issuance>"), "signed_xml_forbidden"),
    (lambda b: b.replace(b"0000000001", b"0000000002"), "native_xml_identity_mismatch"),
    (lambda b: b.replace(b'totalVat="20"', b'totalVat="19"'),
     "native_xml_total_mismatch"),
])
def test_native_xml_mismatch_is_rejected(change, code):
    case = setup_case()
    payload = change(synthetic_xml(case[2]))
    with pytest.raises(AdapterError, match=code):
        capture(case, payload)


def test_local_refresh_can_succeed_with_zero_observed_token_but_detects_changes():
    case = setup_case()
    first = capture(case)
    compare_local(first, capture(case))
    source, binding, native = case
    changed = native.model_copy(update={"captured_dependencies":
                                       native.captured_dependencies | {"legal_address": "Другой"}})
    with pytest.raises(AdapterError, match="native_capture_changed"):
        capture((source, binding, changed))
    # A NEW synthetic reconciliation permits a new local envelope, never old approval reuse.
    rebound = binding_for(source, changed, binding.recipient_selection)
    refreshed = capture((source, rebound, changed))
    compare_local(refreshed, capture((source, rebound, changed)))
    with pytest.raises(AdapterError, match="prepared_material_changed"):
        compare_local(first, refreshed)
    with pytest.raises(AdapterError, match="envelope_hash_mismatch"):
        compare_local(first, replace(first, xml_bytes=first.xml_bytes + b" "))


def test_inputs_cannot_mutate_a_captured_envelope():
    source, binding, native = setup_case()
    envelope = capture((source, binding, native))
    saved = envelope.snapshot
    source.snapshot["amount"] = "0"
    native.captured_dependencies["legal_address"] = "changed"
    assert envelope.snapshot == saved and sha256(saved) == envelope.snapshot_sha256


def test_independent_valid_fixture_is_accepted_with_totals_as_attributes(pinned_schema):
    payload = FIXTURE.read_bytes()
    pinned_schema.assertValid(etree.fromstring(payload))
    envelope = capture(setup_case(), payload)
    assert envelope.xml_bytes == payload and envelope.xml_sha256 == sha256(payload)
    roster = ET.fromstring(payload).find(f"{{{NS}}}roster")
    assert roster.attrib == {"totalCostVat": "120", "totalExcise": "0",
                             "totalVat": "20", "totalCost": "100"}
    assert roster.find(f"{{{NS}}}totalCost") is None


@pytest.mark.parametrize("path", ["general/number", "general/documentType", "general", "roster",
                                  "roster/rosterItem/cost", "roster/rosterItem/vat",
                                  "roster/rosterItem/vat/rate"])
@pytest.mark.parametrize("conflicting", [False, True], ids=["identical", "conflicting"])
def test_duplicate_checked_fields_and_sections_are_rejected(path, conflicting):
    root = ET.fromstring(FIXTURE.read_bytes())
    parts = path.split("/")
    parent = root
    for part in parts[:-1]:
        parent = parent.find(f"{{{NS}}}{part}")
    duplicate = deepcopy(parent.find(f"{{{NS}}}{parts[-1]}"))
    if conflicting and len(duplicate) == 0:
        duplicate.text = "999"
    parent.append(duplicate)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with pytest.raises(AdapterError, match="native_xml_duplicate_field"):
        capture(setup_case(), payload)


def test_child_totals_are_rejected_even_if_correct_attributes_are_present():
    root = ET.fromstring(FIXTURE.read_bytes())
    roster = root.find(f"{{{NS}}}roster")
    ET.SubElement(roster, f"{{{NS}}}totalCost").text = "100"
    with pytest.raises(AdapterError, match="native_xml_roster_shape"):
        capture(setup_case(), ET.tostring(root, encoding="utf-8", xml_declaration=True))


def test_caller_mutation_during_validation_cannot_change_the_saved_input(monkeypatch):
    source, binding, native = setup_case()
    expected_source = deepcopy(source.snapshot)
    expected_native = native.model_dump(mode="json")

    def change_original_after_validation(detached_source, detached_binding, detached_native):
        validate_binding(detached_source, detached_binding, detached_native)
        source.snapshot["items"][0]["net"] = "0"
        source.snapshot["amount"] = "0"
        native.captured_dependencies["legal_address"] = "Changed during validation"

    monkeypatch.setattr(adapter_module, "validate_binding", change_original_after_validation)
    envelope = capture((source, binding, native))
    saved = json.loads(envelope.snapshot)
    assert source.snapshot["amount"] == "0"  # The race hook really ran.
    assert saved["source"]["snapshot"] == expected_source
    assert saved["native"] == expected_native
    assert sha256(canonical(saved["source"]["snapshot"])) == binding.source_snapshot_sha256
    assert sha256(canonical(saved["native"])) == binding.native_capture_sha256


def test_verification_scope_cannot_be_supplied_or_replaced():
    envelope = capture(setup_case())
    with pytest.raises(ValueError, match="init=False"):
        replace(envelope, verification_scope="runtime_ready")
    values = dict(vars(envelope), verification_scope="runtime_ready")
    with pytest.raises(TypeError, match="verification_scope"):
        LocalEnvelope(**values)
    assert envelope.verification_scope == "local_envelope_only"


@pytest.mark.parametrize("bad", [1.1, float("nan"), Decimal("1.1"), {1: "key"}])
def test_canonical_projection_refuses_lossy_values(bad):
    with pytest.raises(AdapterError):
        canonical({"bad": bad})


def test_bsl_mutation_exclusion_and_native_call_order():
    path = Path(__file__).parents[2] / "integrations/onec_eschf/native_adapter.bsl"
    # Source-bound guard, not a BSL compiler/runtime proof.
    code = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("//"))
    fill = "ЭлектронныеДокументыВнутренний_Локализация.ЗаполнитьДанныеПоСчетуФактуре("
    cleanup = "ЭлектронныеДокументыВнутренний_Локализация.УдалитьПространствоИмен("
    assert code.index(fill) < code.index(cleanup) < code.index("Результат.xml_text = ТекстXML")
    for forbidden in ("СформироватьСчетФактуруXDTO(", "ДобавитьЗаписьПоСостояниюЭД(",
                      ".Записать(", "УстановитьПривилегированныйРежим(",
                      "HTTPСоединение", "COMОбъект", "Подписать", "Отправить"):
        assert forbidden not in code
    assert 'Результат.status = "native_empty_result"' in code
    assert '"diagnostic_capture", "unresolved"' in code


def test_binding_state_and_unknown_xml_are_not_silently_accepted():
    case = setup_case()
    for native in (case[2].model_copy(update={"posted": False}),
                   case[2].model_copy(update={"summary": True})):
        with pytest.raises(AdapterError, match="unsupported_native_document_state"):
            validate_binding(case[0], case[1], native)
    with pytest.raises(AdapterError, match="native_xml_malformed"):
        capture(case, b"<invalid>")
