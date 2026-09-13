"""Local validation of an ESCHF binding and already captured native output.

No transport, native invocation, signature or authorization is implemented here.
Binding must eventually come from a trusted reconciliation store, never an HTTP
request. A nonempty evidence reference is a link, not proof of its authenticity.
LocalEnvelope is deliberately not a runtime preparation/approval capability.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NS = "http://www.w3schools.com"  # Literal native namespace; never fetched.
Text = Annotated[str, Field(strict=True, min_length=1, max_length=2000, pattern=r"\S")]
ID = Annotated[int, Field(strict=True, gt=0)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Number = Annotated[str, Field(strict=True, pattern=r"^[0-9]{9}-[0-9]{4}-[0-9]{10}$")]
DecimalText = Annotated[str, Field(strict=True, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$",
                                  max_length=64)]


class AdapterError(ValueError):
    """Stable local code; native diagnostic text remains separate and unchanged."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AdapterError(code)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    """A specified local JSON format, not native DataVersion or an XML format."""
    def check(item):
        if isinstance(item, dict):
            require(all(type(k) is str for k in item), "non_string_json_key")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        else:
            require(item is None or type(item) in (str, int, bool), "inexact_json_value")

    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Identity(Frozen):
    information_base_id: Text
    metadata_object: Text
    reference: Text

    @field_validator("reference")
    @classmethod
    def canonical_uuid(cls, value):
        if str(UUID(value)) != value or UUID(value).int == 0:
            raise ValueError("reference must be a nonzero canonical native UUID")
        return value


class Selection(Frozen):
    legal_entity_id: ID
    legal_entity_revision: ID
    branch_id: ID | None
    branch_revision: ID | None
    branch_legal_entity_id: ID | None
    branch_tax_mode: Literal["head", "shared"]
    portal_branch_code: Annotated[str, Field(pattern=r"^[0-9]{4}$")] | None

    @model_validator(mode="after")
    def branch_relationship(self):
        if self.branch_tax_mode == "head":
            if any(v is not None for v in (self.branch_id, self.branch_revision,
                                          self.branch_legal_entity_id, self.portal_branch_code)):
                raise ValueError("head has branch data")
        elif (self.branch_id is None or self.branch_revision is None
              or self.branch_legal_entity_id != self.legal_entity_id
              or self.portal_branch_code is None):
            raise ValueError("shared branch needs parent, revision and a portal code")
        return self


class SourceOriginal(Frozen):
    document_id: ID
    version: ID
    content_sha256: Digest
    snapshot: dict
    original_html: Annotated[str, Field(min_length=1)]
    issued: bool
    superseded: bool


class NativeRow(Frozen):
    # Covers native rows for goods and services. A caller cannot relabel a SKU.
    source_kind: Literal["native_invoice_row"]
    number: ID
    name: Text  # Already resolved by native ПолучитьНаименование, not a SKU label.
    quantity: DecimalText
    price: DecimalText
    net: DecimalText
    vat: DecimalText
    gross: DecimalText
    excise: DecimalText
    native_rate: DecimalText  # Result of native resolver, never a caption such as '20%'.
    vat_kind: Literal["ordinary", "zero", "no_vat"]
    calculated: bool
    tnved: str | None
    oked: str | None
    unit_code: Annotated[str, Field(pattern=r"^ *(?:[0-9]+)? *$")] | None


class NativeCapture(Frozen):
    invoice: Identity
    provider: Identity
    recipient: Identity
    basis: Identity
    number: Number
    posted: bool
    summary: bool
    document_type: Literal["ORIGINAL"]
    rows: Annotated[tuple[NativeRow, ...], Field(min_length=1, max_length=1000)]
    # Preserve all captured header/query/dependency values without float conversion.
    # Completeness and atomicity of this payload are NOT established by this model.
    captured_dependencies: dict


class Binding(Frozen):
    source_document_id: ID
    source_document_version: ID
    source_content_sha256: Digest
    source_snapshot_sha256: Digest
    seller_snapshot_sha256: Digest
    recipient_selection: Selection
    invoice: Identity
    provider: Identity
    recipient: Identity
    basis: Identity
    native_capture_sha256: Digest
    reconciliation_evidence_ref: Text
    provider_evidence_ref: Text


class NativeResult(Frozen):
    status: Literal["candidate", "native_failure", "native_empty_result", "unsupported_scenario"]
    xml_text: str | None
    number: str
    native_error: str
    refusal: bool
    diagnostic_capture: Literal["unresolved", "captured"]
    native_messages: tuple[str, ...]


def validate_binding(source: SourceOriginal, binding: Binding, native: NativeCapture) -> None:
    """Check a supplied reconciliation record; obtaining a trusted record is external."""
    snapshot = source.snapshot
    require(source.issued and not source.superseded, "source_not_current_issued_original")
    require((source.document_id, source.version) ==
            (binding.source_document_id, binding.source_document_version), "source_version_changed")
    require((snapshot.get("document_id"), snapshot.get("version")) ==
            (source.document_id, source.version), "source_snapshot_identity_mismatch")
    require(type(snapshot.get("document_id")) is int and type(snapshot.get("version")) is int,
            "source_snapshot_identity_mismatch")
    require(sha256(source.original_html.encode("utf-8")) == source.content_sha256 ==
            binding.source_content_sha256, "source_content_hash_mismatch")
    require(sha256(canonical(snapshot)) == binding.source_snapshot_sha256,
            "source_snapshot_hash_mismatch")
    require(snapshot.get("schema_version") == 1 and type(snapshot.get("schema_version")) is int,
            "unsupported_source_schema")
    party = snapshot.get("party")
    require(isinstance(party, dict) and party.get("identity_status") == "selected",
            "source_party_unproven")
    selection = {key: party.get(key) for key in Selection.model_fields}
    if all(selection[key] is None for key in Selection.model_fields if key.startswith("branch_")):
        selection["branch_tax_mode"] = "head"
    require(Selection.model_validate(selection) == binding.recipient_selection,
            "recipient_selection_mismatch")
    require(isinstance(snapshot.get("seller"), dict) and bool(snapshot["seller"]),
            "seller_source_missing")
    require(sha256(canonical(snapshot["seller"])) == binding.seller_snapshot_sha256,
            "provider_source_mismatch")
    for key, metadata in (("invoice", "Document.СчетФактураВыданный"),
                          ("provider", "Catalog.Организации"),
                          ("recipient", "Catalog.Контрагенты")):
        identity = getattr(native, key)
        require(identity == getattr(binding, key) and identity.metadata_object == metadata,
                "native_identity_mismatch")
    require(native.basis == binding.basis and native.basis.metadata_object.startswith("Document."),
            "native_basis_mismatch")
    require(len({i.information_base_id for i in
                 (native.invoice, native.provider, native.recipient, native.basis)}) == 1,
            "mixed_information_bases")
    require(native.posted and not native.summary, "unsupported_native_document_state")
    require(sha256(canonical(native.model_dump(mode="json"))) == binding.native_capture_sha256,
            "native_capture_changed")
    require(len({r.number for r in native.rows}) == len(native.rows), "duplicate_native_row")


def row_values(row: NativeRow) -> dict[str, str]:
    """Expected native row values for comparison; this does not generate XML."""
    rate_type = ("CALCULATED" if row.calculated else
                 {"zero": "ZERO", "no_vat": "NO_VAT", "ordinary": "DECIMAL"}[row.vat_kind])
    values = {"number": str(row.number), "name": row.name, "count": row.quantity,
              "price": row.price, "cost": row.net, "summaExcise": row.excise,
              "costVat": row.gross, "vat/rate": row.native_rate,
              "vat/rateType": rate_type, "vat/summaVat": row.vat}
    for key, value in (("code", row.tnved), ("code_oced", row.oked)):
        if value:
            values[key] = value
    if row.unit_code is not None and row.unit_code.strip():
        values["units"] = str(int(row.unit_code.strip()))
    return values


def _element(parent: ET.Element, path: str) -> ET.Element | None:
    for part in path.split("/"):
        matches = parent.findall(f"{{{NS}}}{part}")
        require(len(matches) <= 1, "native_xml_duplicate_field")
        if not matches:
            return None
        parent = matches[0]
    return parent


def _text(parent: ET.Element, path: str) -> str | None:
    element = _element(parent, path)
    if element is None:
        return None
    require(len(element) == 0, "native_xml_scalar_shape")
    return element.text or ""


def validate_xml(xml_bytes: bytes, native: NativeCapture) -> None:
    """Check unsigned identity/roster only, not XSD, all header semantics or portal rules."""
    require(b"<!DOCTYPE" not in xml_bytes.upper() and b"<!ENTITY" not in xml_bytes.upper(),
            "xml_declaration_forbidden")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise AdapterError("native_xml_malformed") from error
    require(root.tag == f"{{{NS}}}issuance", "native_xml_root_mismatch")
    require(not any(node.tag.rsplit("}", 1)[-1] == "Signature" for node in root.iter()),
            "signed_xml_forbidden")
    require(_text(root, "general/number") == native.number and
            _text(root, "general/documentType") == native.document_type,
            "native_xml_identity_mismatch")
    require(root.get("sender") == native.number.split("-", 1)[0], "native_xml_sender_mismatch")
    roster = _element(root, "roster")
    require(roster is not None, "native_xml_roster_missing")
    require(all(child.tag == f"{{{NS}}}rosterItem" for child in roster),
            "native_xml_roster_shape")
    xml_rows = roster.findall(f"{{{NS}}}rosterItem")
    require(len(xml_rows) == len(native.rows), "native_xml_row_count_mismatch")
    numeric = {"count", "price", "cost", "summaExcise", "costVat", "vat/rate", "vat/summaVat"}
    for actual, row in zip(xml_rows, native.rows):
        values = row_values(row)
        for path in values.keys() | {"code", "code_oced", "units"}:
            text = _text(actual, path)
            expected = values.get(path)
            if path in numeric and text is not None:
                require(bool(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", text)),
                        "native_xml_nondecimal")
                require(Decimal(text) == Decimal(expected), "native_xml_amount_mismatch")
            else:
                require(text == expected, "native_xml_row_mismatch")
    with localcontext() as context:
        context.prec = 80
        for path, field in (("totalCost", "net"), ("totalVat", "vat"),
                            ("totalExcise", "excise"), ("totalCostVat", "gross")):
            # Pinned MNSATI_original.xsd:198-201 defines totals as attributes.
            text = roster.get(path)
            require(text is not None and bool(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", text)),
                    "native_xml_total_missing")
            require(Decimal(text) == sum((Decimal(getattr(row, field)) for row in native.rows),
                                        Decimal(0)), "native_xml_total_mismatch")


@dataclass(frozen=True)
class LocalEnvelope:
    snapshot: bytes  # Immutable copy: subsequent mutation of input dicts cannot change it.
    snapshot_sha256: str
    xml_bytes: bytes
    xml_sha256: str
    number: str
    native_error: str
    native_messages: tuple[str, ...]
    verification_scope: Literal["local_envelope_only"] = field(
        default="local_envelope_only", init=False)


def capture_local(source: SourceOriginal, binding: Binding, native: NativeCapture,
                  result: NativeResult, xml_bytes: bytes, *,
                  codec: Literal["utf-8", "utf-8-sig"], byte_evidence_ref: str) -> LocalEnvelope:
    """Validate provided bytes using an explicit codec hypothesis, without generating bytes.

    Runtime evidence for that hypothesis is still required; this function is not
    an authorization gate. Synthetic positive fixtures can exercise it today.
    """
    # Frozen models still contain mutable dictionaries. Validate and serialize ONE
    # detached input set so caller changes after validation cannot enter the envelope.
    # This is a local copy boundary, not proof of an atomic native database read.
    source, binding, native, result = deepcopy((source, binding, native, result))
    validate_binding(source, binding, native)
    require(result.status == "candidate" and not result.refusal and not result.native_error
            and result.xml_text is not None, "native_result_failed")
    require(result.number == native.number, "native_result_number_mismatch")
    require(type(xml_bytes) is bytes and bool(xml_bytes), "native_bytes_missing")
    require(codec in ("utf-8", "utf-8-sig") and isinstance(byte_evidence_ref, str)
            and bool(byte_evidence_ref.strip()),
            "byte_evidence_required")
    require(xml_bytes.startswith(b"\xef\xbb\xbf") == (codec == "utf-8-sig"),
            "native_bom_mismatch")
    try:
        decoded = xml_bytes.decode(codec, errors="strict")
    except UnicodeError as error:
        raise AdapterError("native_bytes_decoding_failed") from error
    require(decoded == result.xml_text, "native_text_bytes_mismatch")
    validate_xml(xml_bytes, native)
    snapshot = canonical({"schema": 1, "scope": "local_envelope_only",
                          "source": source.model_dump(mode="json"),
                          "binding": binding.model_dump(mode="json"),
                          "native": native.model_dump(mode="json"),
                          "diagnostic_capture": result.diagnostic_capture,
                          "native_messages": list(result.native_messages),
                          "codec_hypothesis": codec, "byte_evidence_ref": byte_evidence_ref})
    return LocalEnvelope(snapshot, sha256(snapshot), xml_bytes, sha256(xml_bytes), native.number,
                         result.native_error, result.native_messages)


def compare_local(previous: LocalEnvelope, current: LocalEnvelope) -> None:
    """Detect changed captured material. This does not prove atomic native freshness."""
    for envelope in (previous, current):
        require(sha256(envelope.snapshot) == envelope.snapshot_sha256 and
                sha256(envelope.xml_bytes) == envelope.xml_sha256, "envelope_hash_mismatch")
    require((previous.snapshot, previous.xml_bytes, previous.number) ==
            (current.snapshot, current.xml_bytes, current.number), "prepared_material_changed")
