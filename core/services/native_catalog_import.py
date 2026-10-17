"""Transactional incoming catalogs. No posting, stock, outbound sync or commit.

The caller supplies sealed observed JSON text and owns its outer transaction.
Nomenclature starts as a projection; enrichment preserves its existing fields.
An enriched observation does not establish full source validation. Counterparties are
retained on hold until a separate, authoritative requisites mapper is accepted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from hashlib import blake2b, sha256
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.domain.models import CatalogSourceIdentity, CatalogSourceRevision, Sku
from core.domain.reference import NomenclatureCategory

NOMENCLATURE = "Catalog_Номенклатура"
COUNTERPARTIES = "Catalog_Контрагенты"
ZERO = "00000000-0000-0000-0000-000000000000"


class CatalogImportConflict(ValueError):
    """Safe error codes only: never include source names, addresses or payloads."""


def digest(value: str) -> str:
    return sha256(value.encode("utf8")).hexdigest()


def guid(value: object, *, nullable=False):
    if nullable and value in (None, "", ZERO):
        return None
    if not isinstance(value, str):
        raise CatalogImportConflict("GUID_TYPE")
    try:
        result = str(UUID(value))
    except (ValueError, AttributeError):
        raise CatalogImportConflict("GUID_INVALID") from None
    if result == ZERO:
        raise CatalogImportConflict("GUID_ZERO")
    return result


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise CatalogImportConflict("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


@dataclass(frozen=True)
class SourceRow:
    entity: str
    source_text: str

    def parse(self):
        if self.entity not in {NOMENCLATURE, COUNTERPARTIES}:
            raise CatalogImportConflict("SOURCE_ENTITY")
        if not isinstance(self.source_text, str) or len(self.source_text.encode("utf8")) > 2 * 1024 * 1024:
            raise CatalogImportConflict("SOURCE_ROW_SIZE")
        try:
            row = json.loads(self.source_text, parse_float=Decimal, object_pairs_hook=_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(CatalogImportConflict("JSON_NONFINITE")))
        except (json.JSONDecodeError, UnicodeError):
            raise CatalogImportConflict("SOURCE_JSON") from None
        if not isinstance(row, dict):
            raise CatalogImportConflict("SOURCE_ROW_TYPE")
        key = guid(row.get("Ref_Key"))
        if not isinstance(row.get("DataVersion"), str) or not 0 < len(row["DataVersion"]) <= 255:
            raise CatalogImportConflict("SOURCE_DATA_VERSION")
        code_required_or_present = self.entity == NOMENCLATURE or "Code" in row
        if not isinstance(row.get("Description"), str) or code_required_or_present and not isinstance(row.get("Code"), str):
            raise CatalogImportConflict("SOURCE_NAME_CODE")
        if type(row.get("DeletionMark")) is not bool:
            raise CatalogImportConflict("SOURCE_TOMBSTONE")
        if self.entity == NOMENCLATURE:
            if type(row.get("IsFolder")) is not bool:
                raise CatalogImportConflict("SOURCE_FOLDER")
            row["Parent_Key"] = guid(row.get("Parent_Key"), nullable=True)
            row["ЕдиницаИзмерения_Key"] = guid(row.get("ЕдиницаИзмерения_Key"), nullable=True)
        return key, row


def _native(identity, session):
    model, key = ((Sku, identity.sku_id) if identity.kind == "sku" else
                  (NomenclatureCategory, identity.group_id))
    if identity.kind == "counterparty":
        if identity.counterparty_id is not None:
            raise CatalogImportConflict("COUNTERPARTY_SCOPE_CHANGED")
        return None
    if key is None:
        return None
    value = session.scalar(select(model).where(model.id == key).with_for_update().execution_options(populate_existing=True))
    if value is None:
        raise CatalogImportConflict("NATIVE_TARGET_MISSING")
    return value


def _target_sha(target):
    if target is None:
        return None
    values = {column.name: getattr(target, column.name) for column in target.__table__.columns}
    return digest(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _preserves_source_fields(previous_text, incoming_text):
    # Compare before GUID normalization and preserve number spellings and types.
    def parse(value):
        return json.loads(value, parse_int=lambda token: ("number", token),
                          parse_float=lambda token: ("number", token), object_pairs_hook=_pairs)

    previous, incoming = parse(previous_text), parse(incoming_text)
    return previous.keys() < incoming.keys() and all(incoming[key] == value for key, value in previous.items())


def import_catalog(session: Session, namespace: str, rows: list[SourceRow], *, actor: str,
                   expected_previous: dict[tuple[str, str], str | None] | None = None,
                   enrich_projection: bool = False):
    """Load one bounded source batch; every failure rolls back this entire batch.

    Units deliberately remain unknown until sealed unit entity mappings are
    implemented. Neither default 'шт' nor a catalogue folder default is guessed.
    Enrichment only adds observed fields to an existing, unchanged projection.
    """
    if not isinstance(namespace, str) or not 0 < len(namespace) <= 64 or not isinstance(actor, str) or not 0 < len(actor) <= 128:
        raise CatalogImportConflict("IMPORT_SCOPE")
    if type(enrich_projection) is not bool:
        raise CatalogImportConflict("ENRICHMENT_MODE")
    if session.new or session.dirty or session.deleted:
        raise CatalogImportConflict("CLEAN_SESSION_REQUIRED")
    if not 0 < len(rows) <= 30000:
        raise CatalogImportConflict("BATCH_SIZE")
    parsed = {}
    for incoming in rows:
        key, row = incoming.parse()
        identity_key = (incoming.entity, key)
        if identity_key in parsed:
            raise CatalogImportConflict("DUPLICATE_SOURCE_GUID")
        parsed[identity_key] = incoming, row
    expected_previous = expected_previous or {}
    totals = dict(created=0, corrected=0, replayed=0, native_groups=0, native_skus=0,
                  held_counterparties=0, unknown_units=0, tombstones=0)
    with session.begin_nested():
        # Serialize a source namespace, including not-yet-existing identities.
        if session.get_bind().dialect.name == "postgresql":
            lock = int.from_bytes(blake2b(("catalog:" + namespace).encode(), digest_size=8).digest(), "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        existing = {(v.entity, v.source_guid): v for v in session.scalars(
            select(CatalogSourceIdentity).where(CatalogSourceIdentity.namespace == namespace)
                .with_for_update().execution_options(populate_existing=True))}
        # Validate the resulting tree before writing. Partial updates must not
        # introduce a cycle through a parent absent from the incoming batch.
        parents = {}
        for key, identity in existing.items():
            if identity.kind == "group":
                revision = session.scalar(select(CatalogSourceRevision).where(
                    CatalogSourceRevision.identity_id == identity.id,
                    CatalogSourceRevision.revision_no == identity.revision_no).execution_options(populate_existing=True))
                if (revision is None or revision.source_sha != identity.source_sha
                    or digest(revision.source_text) != revision.source_sha
                    or revision.target_sha != identity.target_sha or revision.holds != identity.holds):
                    raise CatalogImportConflict("CURRENT_REVISION_INTEGRITY")
                if _target_sha(_native(identity, session)) != identity.target_sha:
                    raise CatalogImportConflict("NATIVE_TARGET_CHANGED")
                parents[key[1]] = SourceRow(NOMENCLATURE, revision.source_text).parse()[1]["Parent_Key"]
        for (entity, key), (_, row) in parsed.items():
            if entity == NOMENCLATURE and row["IsFolder"]:
                parents[key] = row["Parent_Key"]
        ordered_groups = []
        visited, visiting = set(), set()

        def visit(key):
            if key in visiting:
                raise CatalogImportConflict("GROUP_CYCLE")
            if key in visited:
                return
            if len(visiting) >= 128:
                raise CatalogImportConflict("GROUP_DEPTH_LIMIT")
            visiting.add(key)
            parent = parents[key]
            if parent:
                if parent not in parents:
                    raise CatalogImportConflict("GROUP_PARENT_MISSING")
                visit(parent)
            visiting.remove(key)
            visited.add(key)
            ordered_groups.append(key)

        for key in sorted(parents):
            visit(key)
        for (entity, _), (_, row) in parsed.items():
            if entity == NOMENCLATURE and row["Parent_Key"] and row["Parent_Key"] not in parents:
                raise CatalogImportConflict("GROUP_PARENT_MISSING")
        order = [(NOMENCLATURE, key) for key in ordered_groups if (NOMENCLATURE, key) in parsed]
        group_keys = set(order)
        order += sorted(key for key in parsed if key not in group_keys)
        for key in order:
            incoming, row = parsed[key]
            kind = ("counterparty" if incoming.entity == COUNTERPARTIES else "group" if row["IsFolder"] else "sku")
            identity = existing.get(key)
            if enrich_projection and (identity is None or kind == "counterparty"):
                raise CatalogImportConflict("ENRICHMENT_REQUIRES_PROJECTION")
            source_sha = digest(incoming.source_text)
            target = _native(identity, session) if identity else None
            previous = identity.source_sha if identity else None
            if identity:
                if identity.kind != kind:
                    raise CatalogImportConflict("SOURCE_KIND_CHANGED")
                if _target_sha(target) != identity.target_sha:
                    raise CatalogImportConflict("NATIVE_TARGET_CHANGED")
                revisions = list(session.scalars(select(CatalogSourceRevision).where(
                    CatalogSourceRevision.identity_id == identity.id).execution_options(populate_existing=True)))
                current = next((v for v in revisions if v.revision_no == identity.revision_no), None)
                if (current is None or current.source_sha != previous or digest(current.source_text) != previous
                    or current.target_sha != identity.target_sha or current.holds != identity.holds):
                    raise CatalogImportConflict("CURRENT_REVISION_INTEGRITY")
                if previous == source_sha:
                    totals["replayed"] += 1
                    continue
                if enrich_projection:
                    if (target is None or "NATIVE_TITLE_INVALID" in current.holds or current.data_version != row["DataVersion"]
                        or target.attributes.get("source_catalog", {}).get("observed_shape") != "projection"):
                        raise CatalogImportConflict("ENRICHMENT_REQUIRES_PROJECTION")
                    if not _preserves_source_fields(current.source_text, incoming.source_text):
                        raise CatalogImportConflict("ENRICHMENT_FIELDS_CHANGED")
                elif any(v.data_version == row["DataVersion"] and v.source_sha != source_sha for v in revisions):
                    raise CatalogImportConflict("DATA_VERSION_REUSED")
            if expected_previous.get(key) != previous:
                raise CatalogImportConflict("EXPECTED_PREVIOUS_SHA")
            holds = []
            if row["DeletionMark"]:
                holds.append("SOURCE_TOMBSTONE")
                totals["tombstones"] += 1
            if not row["Description"].strip() or len(row["Description"]) > 255:
                holds.append("NATIVE_TITLE_INVALID")
            if kind == "counterparty":
                holds.append("COUNTERPARTY_REQUISITES_UNVERIFIED")
                totals["held_counterparties"] += 1
            elif kind == "sku":
                holds.append("UNKNOWN_UNIT")
                totals["unknown_units"] += 1
            if identity is None:
                identity = CatalogSourceIdentity(namespace=namespace, entity=key[0], source_guid=key[1],
                                                 kind=kind, source_sha=source_sha, revision_no=0, holds=[])
                session.add(identity)
                session.flush()
                existing[key] = identity
                totals["created"] += 1
            else:
                totals["corrected"] += 1
            if kind != "counterparty" and "NATIVE_TITLE_INVALID" not in holds:
                code = "SRC-" + digest(namespace + ":" + key[0] + ":" + key[1])[:48]
                if target is None:
                    target = Sku(code=code, title=row["Description"], unit="") if kind == "sku" else NomenclatureCategory(code=code, name=row["Description"])
                    session.add(target)
                parent = existing.get((NOMENCLATURE, row["Parent_Key"])) if row["Parent_Key"] else None
                if parent and parent.group_id is None:
                    raise CatalogImportConflict("GROUP_PARENT_HELD")
                attributes = {"source_catalog": {"namespace": namespace, "entity": key[0], "guid": key[1],
                    "code": row["Code"], "unit_guid": row["ЕдиницаИзмерения_Key"],
                    "observed_shape": "enriched" if enrich_projection else "projection", "group_review": "PENDING", "holds": holds}}
                target.attributes = attributes
                target.is_active = not holds
                if kind == "sku":
                    target.title, target.unit, target.category_id = row["Description"], "", parent.group_id if parent else None
                    target.provenance = {"source_catalog": {"namespace": namespace, "guid": key[1], "sha": source_sha}}
                    totals["native_skus"] += 1
                else:
                    target.name, target.parent_id, target.unit = row["Description"], parent.group_id if parent else None, None
                    totals["native_groups"] += 1
                session.flush()
                if kind == "sku":
                    identity.sku_id = target.id
                else:
                    identity.group_id = target.id
            elif target is not None:
                target.is_active = False
                session.flush()
            identity.source_sha, identity.revision_no = source_sha, identity.revision_no + 1
            identity.target_sha, identity.holds = _target_sha(target), holds
            session.add(CatalogSourceRevision(identity_id=identity.id, revision_no=identity.revision_no,
                source_sha=source_sha, data_version=row["DataVersion"], previous_sha=previous,
                source_text=incoming.source_text, target_sha=identity.target_sha, holds=holds, actor=actor))
            session.flush()
    return totals


@dataclass(frozen=True)
class SourceUnitBinding:
    sku: SourceRow
    unit_source_text: str
    expected_revision: int
    expected_target_sha: str
    evidence_sha: str


def bind_source_units(session: Session, namespace: str, bindings: list[SourceUnitBinding], *, actor: str,
                      activate: bool = False):
    """Bind exact source unit labels without conversion or commit.

    The caller verifies the sealed source observation and supplies its evidence
    digest. This records unit identity only; it does not approve quantity factors,
    source groups, financial admission, or document posting. Explicit activation
    is allowed only with no remaining holds; group review stays pending.
    """
    if (not isinstance(namespace, str) or not 0 < len(namespace) <= 64
        or not isinstance(actor, str) or not 0 < len(actor) <= 128):
        raise CatalogImportConflict("IMPORT_SCOPE")
    if type(activate) is not bool:
        raise CatalogImportConflict("UNIT_ACTIVATION_MODE")
    if session.new or session.dirty or session.deleted:
        raise CatalogImportConflict("CLEAN_SESSION_REQUIRED")
    if not 0 < len(bindings) <= 30000:
        raise CatalogImportConflict("BATCH_SIZE")
    parsed = {}
    for binding in bindings:
        key, sku = binding.sku.parse()
        if binding.sku.entity != NOMENCLATURE or sku["IsFolder"] or sku["DeletionMark"]:
            raise CatalogImportConflict("UNIT_SKU_SCOPE")
        if key in parsed:
            raise CatalogImportConflict("DUPLICATE_SOURCE_GUID")
        if (type(binding.expected_revision) is not int or binding.expected_revision <= 0
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in (binding.expected_target_sha, binding.evidence_sha))):
            raise CatalogImportConflict("UNIT_BINDING_EVIDENCE")
        if not isinstance(binding.unit_source_text, str):
            raise CatalogImportConflict("SOURCE_ROW_SIZE")
        try:
            size = len(binding.unit_source_text.encode("utf8"))
        except UnicodeEncodeError:
            raise CatalogImportConflict("SOURCE_JSON") from None
        if size > 2 * 1024 * 1024:
            raise CatalogImportConflict("SOURCE_ROW_SIZE")
        try:
            unit = json.loads(binding.unit_source_text, parse_float=Decimal, object_pairs_hook=_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(CatalogImportConflict("JSON_NONFINITE")))
        except (json.JSONDecodeError, UnicodeError):
            raise CatalogImportConflict("SOURCE_JSON") from None
        if not isinstance(unit, dict) or guid(unit.get("Ref_Key")) != sku["ЕдиницаИзмерения_Key"]:
            raise CatalogImportConflict("UNIT_REFERENCE_MISMATCH")
        if unit.get("DeletionMark") is not False:
            raise CatalogImportConflict("UNIT_DELETED_OR_UNKNOWN")
        if not isinstance(unit.get("DataVersion"), str) or not 0 < len(unit["DataVersion"]) <= 255:
            raise CatalogImportConflict("SOURCE_DATA_VERSION")
        label = unit.get("Description")
        if not isinstance(label, str) or not label.strip() or label != label.strip() or len(label) > 16:
            raise CatalogImportConflict("UNIT_LABEL_INVALID")
        for value, code in ((label, "UNIT_LABEL_INVALID"), (unit["DataVersion"], "SOURCE_DATA_VERSION")):
            try:
                value.encode("utf8")
            except UnicodeEncodeError:
                raise CatalogImportConflict(code) from None
            if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
                raise CatalogImportConflict(code)
        parsed[key] = binding, sku, unit
    totals = dict(bound=0, replayed=0)
    with session.begin_nested():
        if session.get_bind().dialect.name == "postgresql":
            lock = int.from_bytes(blake2b(("catalog:" + namespace).encode(), digest_size=8).digest(), "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        for key in sorted(parsed):
            binding, sku, unit = parsed[key]
            identity = session.scalar(select(CatalogSourceIdentity).where(
                CatalogSourceIdentity.namespace == namespace, CatalogSourceIdentity.entity == NOMENCLATURE,
                CatalogSourceIdentity.source_guid == key).with_for_update().execution_options(populate_existing=True))
            if identity is None or identity.kind != "sku":
                raise CatalogImportConflict("UNIT_SKU_IDENTITY_MISSING")
            target = _native(identity, session)
            current = session.scalar(select(CatalogSourceRevision).where(
                CatalogSourceRevision.identity_id == identity.id,
                CatalogSourceRevision.revision_no == identity.revision_no).execution_options(populate_existing=True))
            if (current is None or current.source_sha != identity.source_sha
                or digest(current.source_text) != identity.source_sha or current.target_sha != identity.target_sha
                or current.holds != identity.holds):
                raise CatalogImportConflict("CURRENT_REVISION_INTEGRITY")
            if target is None or _target_sha(target) != identity.target_sha:
                raise CatalogImportConflict("NATIVE_TARGET_CHANGED")
            if (binding.sku.source_text != current.source_text or digest(binding.sku.source_text) != identity.source_sha
                or sku["DataVersion"] != current.data_version):
                raise CatalogImportConflict("UNIT_SKU_SOURCE_CHANGED")
            unit_proof = {"entity": "Catalog_УпаковкиЕдиницыИзмерения", "guid": guid(unit["Ref_Key"]),
                          "data_version": unit["DataVersion"], "sha": digest(binding.unit_source_text),
                          "source_text": binding.unit_source_text, "evidence_sha": binding.evidence_sha}
            already_bound = (target.provenance.get("source_unit") == unit_proof
                             and target.unit == unit["Description"] and "UNKNOWN_UNIT" not in identity.holds)
            holds = [value for value in identity.holds if value != "UNKNOWN_UNIT"]
            if activate and holds:
                raise CatalogImportConflict("UNIT_ACTIVATION_HELD")
            if already_bound and (not activate or target.is_active):
                totals["replayed"] += 1
                continue
            if identity.revision_no != binding.expected_revision or identity.target_sha != binding.expected_target_sha:
                raise CatalogImportConflict("EXPECTED_TARGET_REVISION")
            if not already_bound and ("UNKNOWN_UNIT" not in identity.holds or target.unit):
                raise CatalogImportConflict("UNIT_BINDING_ALREADY_SET")
            attributes = dict(target.attributes)
            attributes["source_catalog"] = {**attributes["source_catalog"], "holds": holds}
            target.attributes = attributes
            target.provenance = {**target.provenance, "source_unit": unit_proof}
            target.unit = unit["Description"]
            if activate:
                target.is_active = True
            # Group review and every other hold remain unchanged.
            session.flush()
            identity.revision_no += 1
            identity.target_sha, identity.holds = _target_sha(target), holds
            session.add(CatalogSourceRevision(identity_id=identity.id, revision_no=identity.revision_no,
                source_sha=identity.source_sha, data_version=current.data_version, previous_sha=identity.source_sha,
                source_text=current.source_text, target_sha=identity.target_sha, holds=holds, actor=actor))
            session.flush()
            totals["bound"] += 1
    return totals
