"""Sealed source-price imports and reference reads. No stock or customer-price writes.

The caller owns the transaction. A source price remains reference-only: an empty
package GUID does not establish a conversion, and zero does not authorize a free sale.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from core.domain.models import CatalogSourceIdentity, CatalogSourceRevision, Sku
from core.services.native_catalog_import import NOMENCLATURE, _target_sha, digest
from modules.integrations.models import CatalogPriceObservation, CatalogPriceSnapshot

ZERO = "00000000-0000-0000-0000-000000000000"
DIMS = ("Номенклатура_Key", "Характеристика_Key", "ВидЦены_Key", "Упаковка_Key", "Валюта_Key")
SHA = re.compile(r"[0-9a-f]{64}\Z")


class CatalogPriceError(ValueError):
    """Safe codes only: source bodies, names and URLs never enter errors."""


@dataclass(frozen=True)
class PricePacket:
    request_key: str
    namespace: str
    selected_kind: str
    source_as_of: datetime
    observed_at: datetime
    prices_text: str
    kinds_text: str
    currencies_text: str
    prices_sha: str
    kinds_sha: str
    currencies_sha: str


def _guid(value, *, zero=True):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        if not zero and value == ZERO:
            raise ValueError
    except (ValueError, AttributeError):
        raise CatalogPriceError("GUID") from None
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogPriceError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _json(raw, limit):
    if not isinstance(raw, str):
        raise CatalogPriceError("SOURCE_TEXT")
    try:
        if len(raw.encode("utf8")) > limit:
            raise CatalogPriceError("SOURCE_SIZE")
        return json.loads(raw, parse_float=Decimal, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              CatalogPriceError("NONFINITE_JSON")))
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise CatalogPriceError("SOURCE_JSON") from None


def _envelope(raw, limit, cap):
    payload = _json(raw, limit)
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
        raise CatalogPriceError("SOURCE_ENVELOPE")
    if len(payload["value"]) >= cap or any(
        key in payload for key in ("odata.nextLink", "@odata.nextLink", "__next")
    ):
        raise CatalogPriceError("PARTIAL_SOURCE")
    if any(not isinstance(row, dict) for row in payload["value"]):
        raise CatalogPriceError("SOURCE_ROW")
    return payload["value"]


def decode_packet(packet: PricePacket):
    """Validate the entire packet before any SQL, preserving precise source numbers."""
    _guid(packet.request_key, zero=False)
    _guid(packet.selected_kind, zero=False)
    if not isinstance(packet.namespace, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9:._-]{0,63}", packet.namespace
    ):
        raise CatalogPriceError("NAMESPACE")
    if not isinstance(packet.source_as_of, datetime) or packet.source_as_of.tzinfo is not None:
        raise CatalogPriceError("SOURCE_DATE")
    if (not isinstance(packet.observed_at, datetime) or packet.observed_at.tzinfo is None
            or packet.observed_at.utcoffset() is None):
        raise CatalogPriceError("OBSERVATION_DATE")
    for name in ("prices", "kinds", "currencies"):
        raw, expected = getattr(packet, name + "_text"), getattr(packet, name + "_sha")
        if (not isinstance(expected, str) or not SHA.fullmatch(expected)
                or not isinstance(raw, str)):
            raise CatalogPriceError("SOURCE_HASH")
        try:
            actual = digest(raw)
        except UnicodeError:
            raise CatalogPriceError("SOURCE_TEXT") from None
        if actual != expected:
            raise CatalogPriceError("SOURCE_HASH")
    kinds = _envelope(packet.kinds_text, 65536, 101)
    currencies = _envelope(packet.currencies_text, 65536, 101)
    selected = None
    seen = set()
    for kind in kinds:
        key = _guid(kind.get("Ref_Key"), zero=False)
        if key in seen:
            raise CatalogPriceError("DUPLICATE_KIND")
        seen.add(key)
        if any(type(kind.get(k)) is not bool for k in ("IsFolder", "DeletionMark")):
            raise CatalogPriceError("KIND_FLAGS")
        if key == packet.selected_kind:
            selected = kind
    if (selected is None or selected["IsFolder"] or selected["DeletionMark"]
            or selected.get("ИспользоватьПриПродаже") is not True
            or type(selected.get("ЦенаВключаетНДС")) is not bool
            or not isinstance(selected.get("Description"), str)
            or not 0 < len(selected["Description"].strip()) <= 255):
        raise CatalogPriceError("SELECTED_KIND")
    currency_codes = {}
    seen = set()
    for currency in currencies:
        key = _guid(currency.get("Ref_Key"), zero=False)
        if key in seen or type(currency.get("DeletionMark")) is not bool:
            raise CatalogPriceError("CURRENCY")
        seen.add(key)
        if not isinstance(currency.get("Code"), str) or not 0 < len(currency["Code"]) <= 32:
            raise CatalogPriceError("CURRENCY_CODE")
        if not currency["DeletionMark"]:
            currency_codes[key] = currency["Code"]
    source_rows = _envelope(packet.prices_text, 8 * 1024 * 1024, 10001)
    rows, seen = [], set()
    for row in source_rows:
        key = tuple(_guid(row.get(k), zero=k not in (DIMS[0], DIMS[2])) for k in DIMS)
        if key in seen:
            raise CatalogPriceError("DUPLICATE_DIMENSIONS")
        seen.add(key)
        if key[2] != packet.selected_kind:
            raise CatalogPriceError("PRICE_KIND")
        try:
            if not isinstance(row.get("Period"), str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", row["Period"]
            ):
                raise ValueError
            period = datetime.fromisoformat(row["Period"])
        except ValueError:
            raise CatalogPriceError("PRICE_DATE") from None
        if period.tzinfo is not None or period > packet.source_as_of:
            raise CatalogPriceError("PRICE_DATE")
        value = row.get("Цена")
        if type(value) not in (int, Decimal):
            raise CatalogPriceError("PRICE_TYPE")
        value = Decimal(value)
        if (not value.is_finite() or value < 0 or value >= Decimal("1e18")
                or max(0, -value.as_tuple().exponent) > 10):
            raise CatalogPriceError("PRICE_PRECISION")
        rows.append(dict(product_guid=key[0], characteristic_guid=key[1], kind_guid=key[2],
                         package_guid=key[3], currency_guid=key[4],
                         currency_code=currency_codes.get(key[4]), effective_at=period,
                         price=value, price_text=str(value)))
    content = dict(namespace=packet.namespace, selected_kind=packet.selected_kind,
                   source_as_of=packet.source_as_of.isoformat(),
                   observed_at=packet.observed_at.astimezone(UTC).isoformat(),
                   prices_sha=packet.prices_sha, kinds_sha=packet.kinds_sha,
                   currencies_sha=packet.currencies_sha)
    content_sha = digest(json.dumps(content, sort_keys=True, separators=(",", ":")))
    return selected, rows, content_sha


def _bindings(session, namespace, keys, *, lock=False):
    if not keys:
        return {}
    stmt = select(CatalogSourceIdentity, CatalogSourceRevision, Sku).outerjoin(
        CatalogSourceRevision, and_(
            CatalogSourceRevision.identity_id == CatalogSourceIdentity.id,
            CatalogSourceRevision.revision_no == CatalogSourceIdentity.revision_no,
        ),
    ).outerjoin(Sku, Sku.id == CatalogSourceIdentity.sku_id).where(
        CatalogSourceIdentity.namespace == namespace,
        CatalogSourceIdentity.entity == NOMENCLATURE,
        CatalogSourceIdentity.source_guid.in_(keys),
    ).order_by(CatalogSourceIdentity.id)
    if lock:
        stmt = stmt.with_for_update(of=CatalogSourceIdentity)
    return {identity.source_guid: (identity, revision, sku)
            for identity, revision, sku in session.execute(
                stmt.execution_options(populate_existing=True))}


def _binding_state(binding):
    if binding is None:
        return "unmapped", "SOURCE_IDENTITY_MISSING"
    identity, revision, sku = binding
    if identity.kind != "sku" or sku is None or not sku.is_active:
        return "held", "NATIVE_SKU_UNAVAILABLE"
    if revision is None or identity.holds != [] or revision.holds != []:
        return "held", "SOURCE_HELD"
    try:
        if (revision.source_sha != identity.source_sha
                or digest(revision.source_text) != identity.source_sha
                or revision.target_sha != identity.target_sha
                or _target_sha(sku) != identity.target_sha):
            return "held", "SOURCE_IDENTITY_CHANGED"
        source = _json(revision.source_text, 2 * 1024 * 1024)
        proof = sku.provenance.get("source_unit", {})
        unit = _json(proof.get("source_text"), 65536)
        if (_guid(source.get("Ref_Key"), zero=False) != identity.source_guid
                or source.get("DeletionMark") is not False or source.get("IsFolder") is not False
                or source.get("DataVersion") != revision.data_version
                or proof.get("entity") != "Catalog_УпаковкиЕдиницыИзмерения"
                or proof.get("sha") != digest(proof["source_text"])
                or not SHA.fullmatch(proof.get("evidence_sha", ""))
                or _guid(unit.get("Ref_Key"), zero=False) != proof.get("guid")
                or proof["guid"] != _guid(source.get("ЕдиницаИзмерения_Key"), zero=False)
                or unit.get("DataVersion") != proof.get("data_version")
                or unit.get("DeletionMark") is not False
                or not sku.unit or unit.get("Description") != sku.unit):
            return "held", "UNIT_PROOF_UNCONFIRMED"
    except (CatalogPriceError, ValueError, TypeError, KeyError, AttributeError):
        return "held", "UNIT_PROOF_UNCONFIRMED"
    return "mapped", None


def _validated_snapshot(snapshot, observations):
    observed = snapshot.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    selected, source_rows, content_sha = decode_packet(PricePacket(
        request_key=snapshot.id, namespace=snapshot.namespace, selected_kind=snapshot.selected_kind,
        source_as_of=snapshot.source_as_of, observed_at=observed,
        prices_text=snapshot.prices_text, kinds_text=snapshot.kinds_text,
        currencies_text=snapshot.currencies_text, prices_sha=snapshot.prices_sha,
        kinds_sha=snapshot.kinds_sha, currencies_sha=snapshot.currencies_sha,
    ))
    if (snapshot.content_sha != content_sha or len(source_rows) != snapshot.row_count
            or len(observations) != snapshot.row_count or not snapshot.response_complete
            or snapshot.full_coverage or snapshot.activity_verified
            or selected["Description"] != snapshot.kind_name
            or selected["ЦенаВключаетНДС"] != snapshot.price_includes_vat):
        raise CatalogPriceError("SNAPSHOT_INTEGRITY")
    expected = {tuple(row[k] for k in ("product_guid", "characteristic_guid", "kind_guid",
                                      "package_guid", "currency_guid")): row for row in source_rows}
    seen = set()
    for row in observations:
        key = (row.product_guid, row.characteristic_guid, row.kind_guid,
               row.package_guid, row.currency_guid)
        original = expected.get(key)
        if (original is None or key in seen or any(
            getattr(row, name) != value for name, value in original.items()
        )):
            raise CatalogPriceError("OBSERVATION_INTEGRITY")
        seen.add(key)


def import_prices(session: Session, packet: PricePacket):
    """Atomically retain all rows and select this reference snapshot; never commit."""
    selected, rows, content_sha = decode_packet(packet)
    if session.new or session.dirty or session.deleted:
        raise CatalogPriceError("CLEAN_SESSION_REQUIRED")
    with session.begin_nested():
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": int.from_bytes(sha256(b"catalog-price-current").digest()[:8],
                                                   "big", signed=True)})
        existing = session.get(CatalogPriceSnapshot, packet.request_key, populate_existing=True)
        if existing is not None:
            if existing.content_sha != content_sha:
                raise CatalogPriceError("REQUEST_CONFLICT")
            existing_rows = list(session.scalars(select(CatalogPriceObservation).where(
                CatalogPriceObservation.snapshot_id == existing.id
            ).execution_options(populate_existing=True)))
            _validated_snapshot(existing, existing_rows)
            return {"snapshot_id": existing.id, "replayed": True, "rows": existing.row_count,
                    "is_current": existing.is_current}
        bindings = _bindings(session, packet.namespace, {r["product_guid"] for r in rows}, lock=True)
        snapshot = CatalogPriceSnapshot(
            id=packet.request_key, namespace=packet.namespace, content_sha=content_sha,
            selected_kind=packet.selected_kind, kind_name=selected["Description"],
            price_includes_vat=selected["ЦенаВключаетНДС"], source_as_of=packet.source_as_of,
            observed_at=packet.observed_at.astimezone(UTC), prices_sha=packet.prices_sha,
            kinds_sha=packet.kinds_sha, currencies_sha=packet.currencies_sha,
            prices_text=packet.prices_text, kinds_text=packet.kinds_text,
            currencies_text=packet.currencies_text, row_count=len(rows), response_complete=True,
            full_coverage=False, activity_verified=False, is_current=False,
        )
        session.add(snapshot)
        session.flush()
        counts = Counter()
        for row in rows:
            binding = bindings.get(row["product_guid"])
            status, reason = _binding_state(binding)
            if status == "mapped" and row["currency_code"] is None:
                status, reason = "held", "CURRENCY_UNKNOWN"
            identity, _, sku = binding if binding else (None, None, None)
            session.add(CatalogPriceObservation(
                snapshot_id=snapshot.id, **row, mapping_status=status, mapping_reason=reason,
                sku_id=sku.id if sku else None, identity_id=identity.id if identity else None,
                identity_revision=identity.revision_no if identity else None,
                identity_target_sha=identity.target_sha if identity else None,
            ))
            counts[status] += 1
        session.flush()
        for old in session.scalars(select(CatalogPriceSnapshot).where(
            CatalogPriceSnapshot.is_current.is_(True)
        ).with_for_update().execution_options(populate_existing=True)):
            old.is_current = False
        session.flush()
        snapshot.is_current = True
        session.flush()
    return {"snapshot_id": snapshot.id, "replayed": False, "rows": len(rows),
            **{key: counts[key] for key in ("mapped", "held", "unmapped")}}


def read_reference_prices(session: Session):
    """Read current reference values only, rechecking identity before exposure."""
    # Refresh committed state without overwriting or autoflushing caller edits.
    if session.new or session.dirty or session.deleted:
        raise CatalogPriceError("CLEAN_SESSION_REQUIRED")
    snapshots = list(session.scalars(select(CatalogPriceSnapshot).where(
        CatalogPriceSnapshot.is_current.is_(True)
    ).execution_options(populate_existing=True)))
    if not snapshots:
        return {"status": "unavailable", "snapshot": None, "rows": []}
    if len(snapshots) != 1:
        raise CatalogPriceError("AMBIGUOUS_CURRENT_SNAPSHOT")
    snapshot = snapshots[0]
    observations = list(session.scalars(select(CatalogPriceObservation).where(
        CatalogPriceObservation.snapshot_id == snapshot.id
    ).order_by(CatalogPriceObservation.id).execution_options(populate_existing=True)))
    _validated_snapshot(snapshot, observations)
    bindings = _bindings(session, snapshot.namespace, {r.product_guid for r in observations})
    rows, counts = [], Counter()
    for row in observations:
        binding = bindings.get(row.product_guid)
        status, _ = _binding_state(binding)
        if status == "mapped":
            identity, _, sku = binding
            if (row.mapping_status != "mapped" or row.sku_id != sku.id
                    or row.identity_id != identity.id or row.identity_revision != identity.revision_no
                    or row.identity_target_sha != identity.target_sha or row.currency_code is None):
                status = "held"
        counts[status] += 1
        if status != "mapped":
            continue
        rows.append(dict(sku_id=sku.id, sku_code=sku.code, unit=sku.unit,
                         price=row.price_text, currency=row.currency_code,
                         kind=snapshot.kind_name, price_includes_vat=snapshot.price_includes_vat,
                         effective_at=row.effective_at.isoformat(),
                         characteristic_guid=row.characteristic_guid, package_guid=row.package_guid,
                         application_status="reference_only"))
    observed_at = snapshot.observed_at
    if observed_at.tzinfo is None:  # SQLite test dialect loses timezone metadata.
        observed_at = observed_at.replace(tzinfo=UTC)
    return dict(status="reference", snapshot=dict(
        id=snapshot.id, kind=snapshot.kind_name, source_as_of=snapshot.source_as_of.isoformat(),
        observed_at=observed_at.isoformat(), row_count=snapshot.row_count,
        response_complete=snapshot.response_complete, full_coverage=snapshot.full_coverage,
        activity_verified=snapshot.activity_verified,
        **{key: counts[key] for key in ("mapped", "held", "unmapped")},
    ), rows=rows)
