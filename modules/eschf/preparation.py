"""Internal draft contract, pending CRM-CP-001 integration (see docs/eschf).

Only ORIGINAL / resident SELLER -> CUSTOMER. Output is an unsigned candidate,
not an issued ESCHF. Reference evidence is supplied by a future trusted resolver;
this library does not claim to verify a taxpayer or branch against the portal.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Annotated, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(strict=True, min_length=1, max_length=1000)]
UNP = Annotated[str, Field(strict=True, pattern=r"^[0-9]{9}$")]
SHA256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
ID = Annotated[int, Field(strict=True, gt=0)]
CENT = Decimal("0.01")
NS = "http://www.w3schools.com"  # Literal namespace in the official XSD, not a URL to fetch.


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=False)

    @field_validator("*", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            if not value.strip() or any(
                ord(c) < 32 and c not in "\t\n\r" or 0xD800 <= ord(c) <= 0xDFFF
                or ord(c) in {0xFFFE, 0xFFFF} for c in value
            ):
                raise ValueError("blank text or invalid XML character")
        return value


class PartySnapshot(Frozen):
    legal_entity_id: ID
    branch_id: ID | None = None
    legal_entity_revision: ID
    branch_revision: ID | None = None
    # Explicit relationship from the directory, never inferred from a name or UNP.
    branch_legal_entity_id: ID | None = None
    display_name: Text
    legal_name: Text
    legal_entity_unp: UNP
    taxpayer_unp: UNP
    taxpayer_name: Text
    taxpayer_address: Text
    branch_name: Text | None = None
    branch_tax_mode: Literal["head", "shared", "independent", "unknown"]
    portal_branch_code: Annotated[str, Field(strict=True, pattern=r"^[0-9]{4}$")] | None = None
    reference_evidence_ref: Text
    dependent_person: bool = Field(strict=True)
    residents_of_offshore: bool = Field(strict=True)
    special_deal_goods: bool = Field(strict=True)
    big_company: bool = Field(strict=True)

    @model_validator(mode="after")
    def check_relationship(self):
        if self.branch_tax_mode in {"independent", "unknown"}:
            raise ValueError("tax registration mode requires a verified resolver; unsupported locally")
        if self.branch_tax_mode == "head":
            if any(x is not None for x in (self.branch_id, self.branch_revision,
                                          self.branch_legal_entity_id, self.branch_name,
                                          self.portal_branch_code)):
                raise ValueError("head cannot contain branch requisites")
        elif (self.branch_id is None or self.branch_revision is None or self.branch_name is None
              or self.branch_legal_entity_id != self.legal_entity_id
              or self.portal_branch_code is None):
            raise ValueError("shared branch needs a parent, revision, name and portal code")
        if self.taxpayer_unp != self.legal_entity_unp:
            raise ValueError("head/shared branch must use the legal entity taxpayer UNP")
        # Full official name is explicit; never replace it with an internal display name.
        if self.taxpayer_name != self.legal_name:
            raise ValueError("head/shared taxpayer name must equal the approved legal name")
        return self


class PartySelection(Frozen):
    legal_entity_id: ID
    branch_id: ID | None = None
    legal_entity_revision: ID
    branch_revision: ID | None = None


def resolve_party(selection: PartySelection, records: tuple[PartySnapshot, ...]) -> PartySnapshot:
    """Resolve only trusted directory records, with explicit optimistic revisions."""
    matches = [p for p in records if (p.legal_entity_id, p.branch_id)
               == (selection.legal_entity_id, selection.branch_id)]
    if len(matches) != 1:
        raise ValueError("party reference missing or ambiguous")
    party = matches[0]
    if (party.legal_entity_revision, party.branch_revision) != (
            selection.legal_entity_revision, selection.branch_revision):
        raise ValueError("stale party revision; refresh preview")
    return party


class Line(Frozen):
    name: Text
    # Only ordinary domestic services in this first slice; goods need classifiers/marking.
    kind: Literal["service"]
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6, allow_inf_nan=False)
    price: Decimal = Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)
    vat_rate: Literal["20"]

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def no_float(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("use decimal strings, never binary floats")
        return value

    def amounts(self) -> tuple[Decimal, Decimal, Decimal]:
        with localcontext() as ctx:
            ctx.prec = 60
            net = (self.quantity * self.price).quantize(CENT, rounding=ROUND_HALF_UP)
            vat = (net * Decimal(self.vat_rate) / 100).quantize(CENT, rounding=ROUND_HALF_UP)
            return net, vat, net + vat


class Candidate(Frozen):
    environment: Literal["offline"]
    document_type: Literal["ORIGINAL"]
    source_document_id: ID
    source_document_version: ID
    source_content_sha256: SHA256
    source_snapshot_sha256: SHA256
    # ESCHF number is separately allocated; not the ERP PDF invoice number.
    number: Annotated[str, Field(strict=True, pattern=r"^[0-9]{9}-[0-9]{4}-[0-9]{10}$")]
    issuance_year: Annotated[int, Field(strict=True, ge=2000, le=9999)]
    transaction_date: date
    provider: PartySnapshot
    recipient: PartySnapshot
    lines: Annotated[tuple[Line, ...], Field(min_length=1, max_length=1000)]
    basis_description: Text

    @model_validator(mode="after")
    def check_parties(self):
        if not self.number.startswith(f"{self.provider.taxpayer_unp}-{self.issuance_year}-"):
            raise ValueError("number must match the issuing taxpayer and issuance year")
        if self.provider.taxpayer_unp == self.recipient.taxpayer_unp:
            if self.provider.portal_branch_code == self.recipient.portal_branch_code:
                raise ValueError("equal taxpayer UNPs require distinct portal branch codes (rule 12)")
        return self


@dataclass(frozen=True)
class Prepared:
    snapshot: bytes
    snapshot_sha256: str
    unsigned_xml: bytes
    unsigned_xml_sha256: str
    identity_key: str


def decimal_sum(values) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return sum(values, Decimal("0.00"))


def same_decimal(source, expected: Decimal) -> bool:
    try:
        return isinstance(source, str) and Decimal(source).is_finite() and Decimal(source) == expected
    except InvalidOperation:
        return False


def prepare(candidate: Candidate, source_snapshot: dict, source_original_html: str,
            reference_records: tuple[PartySnapshot, ...]) -> Prepared:
    """Copy the exact source; mutations to live cards/source cannot alter the result.

    The caller must obtain source_snapshot from the document owner's authorized
    immutable-snapshot service. This function verifies binding, not authorization.
    """
    source = canonical(source_snapshot)
    if (source_snapshot.get("document_id") != candidate.source_document_id
            or source_snapshot.get("version") != candidate.source_document_version
            or sha256(source) != candidate.source_snapshot_sha256):
        raise ValueError("source snapshot identity/version/hash mismatch")
    # sales.documents.digest hashes the raw UTF-8 bytes when its argument is a string.
    if sha256(source_original_html.encode("utf-8")) != candidate.source_content_sha256:
        raise ValueError("source original hash mismatch")
    for party in (candidate.provider, candidate.recipient):
        selection = PartySelection(**{k: getattr(party, k) for k in PartySelection.model_fields})
        if resolve_party(selection, reference_records) != party:
            raise ValueError("party snapshot differs from the trusted directory")
    if source_snapshot.get("currency") != "BYN" or source_snapshot.get("kind") != "invoice":
        raise ValueError("only priced BYN invoice sources are supported")
    source_lines = source_snapshot.get("items", [])
    if len(source_lines) != len(candidate.lines):
        raise ValueError("source line count mismatch")
    for line, original in zip(candidate.lines, source_lines):
        values = {"qty": line.quantity, "price": line.price, "vat_rate": Decimal(line.vat_rate)}
        values.update(zip(("net", "tax", "total"), line.amounts()))
        if original.get("name") != line.name or any(
            not same_decimal(original.get(key), value)
            for key, value in values.items()
        ):
            raise ValueError("source line differs from candidate")
    total = decimal_sum(line.amounts()[2] for line in candidate.lines)
    if not same_decimal(source_snapshot.get("amount"), total):
        raise ValueError("source amount differs from candidate")
    payload = candidate.model_dump(mode="json")
    payload["source_snapshot"] = json.loads(source)
    payload["preparation_schema"] = 1
    payload["readiness"] = "unsigned_candidate_only"
    snapshot = canonical(payload)
    root = ET.Element("issuance", {"xmlns": NS, "sender": candidate.provider.taxpayer_unp})

    def add(parent, tag, value=None):
        node = ET.SubElement(parent, tag)
        if value is not None:
            node.text = str(value)
        return node

    add(add(root, "system"), "modelVersion", "1.6.0")
    general = add(root, "general")
    add(general, "number", candidate.number)
    # dateIssuance is assigned by the portal, never fabricated from a local clock.
    add(general, "dateTransaction", candidate.transaction_date.isoformat())
    add(general, "documentType", "ORIGINAL")
    for role, party, status in (("provider", candidate.provider, "SELLER"),
                                ("recipient", candidate.recipient, "CUSTOMER")):
        node = add(root, role)
        add(node, role + "Status", status)
        for tag, flag in (("dependentPerson", party.dependent_person),
                          ("residentsOfOffshore", party.residents_of_offshore),
                          ("specialDealGoods", party.special_deal_goods),
                          ("bigCompany", party.big_company)):
            add(node, tag, str(flag).lower())
        add(node, "countryCode", "112")
        add(node, "unp", party.taxpayer_unp)
        if party.portal_branch_code is not None:
            add(node, "branchCode", party.portal_branch_code)
        add(node, "name", party.taxpayer_name)
        add(node, "address", party.taxpayer_address)
    add(root, "senderReceiver")
    add(add(root, "deliveryCondition"), "description", candidate.basis_description)
    totals = [line.amounts() for line in candidate.lines]
    roster = add(root, "roster")
    for attr, idx in (("totalCost", 0), ("totalVat", 1), ("totalCostVat", 2)):
        roster.set(attr, str(decimal_sum(a[idx] for a in totals)))
    roster.set("totalExcise", "0.00")
    for index, (line, (net, vat, gross)) in enumerate(zip(candidate.lines, totals), 1):
        row = add(roster, "rosterItem")
        for key, val in (("number", index), ("name", line.name), ("count", line.quantity),
                         ("price", line.price), ("cost", net), ("summaExcise", "0.00")):
            add(row, key, val)
        tax = add(row, "vat")
        for key, val in (("rate", line.vat_rate), ("rateType", "DECIMAL"), ("summaVat", vat)):
            add(tax, key, val)
        add(row, "costVat", gross)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    identity = sha256(canonical([candidate.provider.taxpayer_unp, candidate.number]))
    return Prepared(snapshot, sha256(snapshot), xml, sha256(xml), identity)


def check_existing(existing: Prepared, proposed: Prepared) -> Literal["replay"]:
    """Pure collision policy; durable uniqueness/locking belongs to the later DB slice."""
    if existing.identity_key != proposed.identity_key:
        raise ValueError("different ESCHF identities")
    if existing.snapshot_sha256 != proposed.snapshot_sha256:
        raise ValueError("same ESCHF number with different snapshot; explicit correction required")
    return "replay"


def validate_xsd(xml: bytes, xsd_path, expected_sha256: str) -> None:
    """Offline XSD check, separate from portal business/dictionary validation."""
    from pathlib import Path

    from lxml import etree

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid schema fingerprint")
    schema = Path(xsd_path).read_bytes()
    if sha256(schema) != expected_sha256:
        raise ValueError("schema fingerprint mismatch")
    for data in (schema, xml):
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("DTD/entities are forbidden")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    schema_root = etree.fromstring(schema, parser)
    if schema_root.xpath("//xs:include|//xs:import|//xs:redefine",
                         namespaces={"xs": "http://www.w3.org/2001/XMLSchema"}):
        raise ValueError("external schema references are forbidden")
    etree.XMLSchema(schema_root).assertValid(etree.fromstring(xml, parser))
