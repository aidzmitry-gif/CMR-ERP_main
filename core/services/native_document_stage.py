"""Stage exact held source text. Caller owns commit; no business or outbound writes."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, select, text, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.domain.document_source import DocumentSourceRevision
from core.services.native_catalog_import import CatalogImportConflict, _pairs, digest, guid

BOUND = "BOUND_ORGANIZATION"
SHARED = "SHARED_OR_ORG_UNEXPOSED_NOT_POSTABLE"
REQUIRED_HOLDS = {"OPERATIONAL_DOCUMENT_MAPPING_NOT_ACCEPTED", "FINANCIAL_POSTING_NOT_ACCEPTED"}
ENVELOPE = {
    "entity",
    "source_guid",
    "data_version",
    "source_text",
    "source_sha256",
    "source_scope",
    "status",
    "holds",
}
CONTEXT = (
    "organization_sha256",
    "period_start",
    "period_end",
    "entity_scopes_sha256",
    "entity_scopes_text",
)
MAX_ROW_BYTES = 16 * 1024 * 1024
MAX_BATCH_BYTES = 64 * 1024 * 1024
NAIVE_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?)?"


class DocumentStageConflict(ValueError):
    """Safe codes only; never expose original payloads or bound SQL parameters."""


def _bounded(value, limit):
    if not isinstance(value, str) or not 0 < len(value) <= limit or "\x00" in value:
        return False
    try:
        value.encode("utf8")
    except UnicodeError:
        return False
    return True


def _sha(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def _guid(value):
    try:
        result = guid(value)
    except CatalogImportConflict as error:
        raise DocumentStageConflict(str(error)) from None
    if result != value:
        raise DocumentStageConflict("SOURCE_GUID_CANONICAL")
    return result


def _context(entity_scopes, organization_sha256, period_start, period_end):
    if (
        type(entity_scopes) is not dict
        or not 0 < len(entity_scopes) <= 128
        or any(
            not _bounded(k, 128) or not re.fullmatch(r"Document_\w+", k) or v not in (BOUND, SHARED)
            for k, v in entity_scopes.items()
        )
        or not _sha(organization_sha256)
        or type(period_start) is not datetime
        or type(period_end) is not datetime
        or period_start.tzinfo is not None
        or period_end.tzinfo is not None
        or period_start >= period_end
    ):
        raise DocumentStageConflict("IMPORT_CONTEXT")
    scopes = json.dumps(entity_scopes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(scopes.encode("utf8")) > 32768:
        raise DocumentStageConflict("IMPORT_CONTEXT_SIZE")
    return dict(
        organization_sha256=organization_sha256,
        period_start=period_start,
        period_end=period_end,
        entity_scopes_sha256=digest(scopes),
        entity_scopes_text=scopes,
    )


def _parse(incoming, entity_scopes, context):
    if type(incoming) is not dict or set(incoming) != ENVELOPE:
        raise DocumentStageConflict("SOURCE_ENVELOPE")
    entity = incoming["entity"]
    if not isinstance(entity, str) or entity not in entity_scopes:
        raise DocumentStageConflict("SOURCE_ENTITY")
    scope = entity_scopes[entity]
    if incoming["source_scope"] != scope or incoming["status"] != "HELD_SOURCE_ONLY":
        raise DocumentStageConflict("SOURCE_SCOPE_STATUS")
    holds = incoming["holds"]
    required = REQUIRED_HOLDS | ({"ORG_UNEXPOSED_NOT_POSTABLE"} if scope == SHARED else set())
    if (
        type(holds) is not list
        or not 0 < len(holds) <= 64
        or any(not _bounded(v, 128) for v in holds)
        or len(set(holds)) != len(holds)
        or not required <= set(holds)
    ):
        raise DocumentStageConflict("SOURCE_HOLDS")
    raw = incoming["source_text"]
    try:
        size = len(raw.encode("utf8")) if isinstance(raw, str) else 0
    except UnicodeError:
        raise DocumentStageConflict("SOURCE_JSON") from None
    if not 0 < size <= MAX_ROW_BYTES:
        raise DocumentStageConflict("SOURCE_ROW_SIZE")
    if not _sha(incoming["source_sha256"]) or digest(raw) != incoming["source_sha256"]:
        raise DocumentStageConflict("SOURCE_SEAL")
    try:

        def nonfinite(_):
            raise DocumentStageConflict("JSON_NONFINITE")

        row = json.loads(
            raw, parse_float=Decimal, object_pairs_hook=_pairs, parse_constant=nonfinite
        )
    except CatalogImportConflict as error:
        raise DocumentStageConflict(str(error)) from None
    except DocumentStageConflict:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise DocumentStageConflict("SOURCE_JSON") from None
    if type(row) is not dict:
        raise DocumentStageConflict("SOURCE_ROW_TYPE")
    key = _guid(row.get("Ref_Key"))
    if incoming["source_guid"] != key:
        raise DocumentStageConflict("SOURCE_IDENTITY")
    version = row.get("DataVersion")
    if not _bounded(version, 255) or incoming["data_version"] != version:
        raise DocumentStageConflict("SOURCE_DATA_VERSION")
    if type(row.get("Posted")) is not bool or type(row.get("DeletionMark")) is not bool:
        raise DocumentStageConflict("SOURCE_STATE")
    date = row.get("Date")
    if not isinstance(date, str) or not re.fullmatch(NAIVE_DATE, date):
        raise DocumentStageConflict("SOURCE_PERIOD")
    try:
        observed = datetime.fromisoformat(date)
    except ValueError:
        raise DocumentStageConflict("SOURCE_PERIOD") from None
    if (
        observed.tzinfo is not None
        or not context["period_start"] <= observed < context["period_end"]
    ):
        raise DocumentStageConflict("SOURCE_PERIOD")
    if (
        scope == BOUND
        and digest(_guid(row.get("Организация_Key"))) != context["organization_sha256"]
    ):
        raise DocumentStageConflict("SOURCE_ORGANIZATION")
    return dict(
        entity=entity,
        source_guid=key,
        source_scope=scope,
        source_sha=digest(raw),
        data_version=version,
        source_text=raw,
        holds=list(holds),
    ), size


def _same_context(stored, context):
    return all(getattr(stored, k) == v for k, v in context.items())


def stage_documents(
    session: Session,
    namespace: str,
    rows: list[dict],
    *,
    actor: str,
    entity_scopes: dict[str, str],
    organization_sha256: str,
    period_start: datetime,
    period_end: datetime,
    expected_previous: dict[tuple[str, str], str | None] | None = None,
):
    """Atomic bounded held-source batch. Exact replay never appends a revision."""
    if not _bounded(namespace, 64) or not _bounded(actor, 128):
        raise DocumentStageConflict("IMPORT_SCOPE")
    if session.new or session.dirty or session.deleted:
        raise DocumentStageConflict("CLEAN_SESSION_REQUIRED")
    if type(rows) is not list or not 0 < len(rows) <= 4000:
        raise DocumentStageConflict("BATCH_SIZE")
    context = _context(entity_scopes, organization_sha256, period_start, period_end)
    parsed, size = {}, 0
    for incoming in rows:
        value, amount = _parse(incoming, entity_scopes, context)
        key = value["entity"], value["source_guid"]
        if key in parsed:
            raise DocumentStageConflict("DUPLICATE_SOURCE_GUID")
        parsed[key] = value
        size += amount
        if size > MAX_BATCH_BYTES:
            raise DocumentStageConflict("BATCH_BYTES")
    previous = {} if expected_previous is None else expected_previous
    if type(previous) is not dict or any(
        type(k) is not tuple or len(k) != 2 or k not in parsed or (v is not None and not _sha(v))
        for k, v in previous.items()
    ):
        raise DocumentStageConflict("EXPECTED_PREVIOUS_SCOPE")
    totals = dict(created=0, corrected=0, replayed=0, held=len(parsed))
    model = DocumentSourceRevision
    try:
        with session.begin_nested():
            if session.get_bind().dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope,0))"),
                    {"scope": "document:" + namespace},
                )
            policy = session.execute(
                select(*(getattr(model, k) for k in CONTEXT))
                .where(model.namespace == namespace)
                .order_by(model.id)
                .limit(1)
            ).first()
            if policy is not None and not _same_context(policy, context):
                raise DocumentStageConflict("NAMESPACE_CONTEXT_CHANGED")
            heads = (
                select(model.entity, model.source_guid, func.max(model.revision_no).label("n"))
                .where(
                    model.namespace == namespace,
                    tuple_(model.entity, model.source_guid).in_(list(parsed)),
                )
                .group_by(model.entity, model.source_guid)
                .subquery()
            )
            current = {
                (v.entity, v.source_guid): v
                for v in session.scalars(
                    select(model)
                    .join(
                        heads,
                        and_(
                            model.entity == heads.c.entity,
                            model.source_guid == heads.c.source_guid,
                            model.revision_no == heads.c.n,
                        ),
                    )
                    .where(model.namespace == namespace)
                    .execution_options(populate_existing=True)
                )
            }
            versions = {
                tuple(v)
                for v in session.execute(
                    select(model.entity, model.source_guid, model.data_version).where(
                        model.namespace == namespace,
                        tuple_(model.entity, model.source_guid, model.data_version).in_(
                            [(k[0], k[1], v["data_version"]) for k, v in parsed.items()]
                        ),
                    )
                )
            }
            for key, value in sorted(parsed.items()):
                old = current.get(key)
                if old is not None:
                    envelope = dict(
                        entity=old.entity,
                        source_guid=old.source_guid,
                        data_version=old.data_version,
                        source_text=old.source_text,
                        source_sha256=old.source_sha,
                        source_scope=old.source_scope,
                        status="HELD_SOURCE_ONLY",
                        holds=old.holds,
                    )
                    _parse(envelope, entity_scopes, context)
                    if not _same_context(old, context) or old.revision_no <= 0:
                        raise DocumentStageConflict("CURRENT_REVISION_INTEGRITY")
                    if old.source_sha == value["source_sha"]:
                        if (
                            old.source_text != value["source_text"]
                            or old.data_version != value["data_version"]
                            or old.source_scope != value["source_scope"]
                            or old.holds != value["holds"]
                        ):
                            raise DocumentStageConflict("REPLAY_POLICY_CHANGED")
                        totals["replayed"] += 1
                        continue
                    if not set(old.holds) <= set(value["holds"]):
                        raise DocumentStageConflict("SOURCE_HOLDS_WEAKENED")
                if (key[0], key[1], value["data_version"]) in versions:
                    raise DocumentStageConflict("DATA_VERSION_REUSED")
                if previous.get(key) != (old.source_sha if old else None):
                    raise DocumentStageConflict("EXPECTED_PREVIOUS_SHA")
                session.add(
                    model(
                        namespace=namespace,
                        revision_no=old.revision_no + 1 if old else 1,
                        previous_sha=old.source_sha if old else None,
                        actor=actor,
                        **context,
                        **value,
                    )
                )
                session.flush()
                totals["corrected" if old else "created"] += 1
    except DBAPIError as error:
        message = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        code = (
            message
            if re.fullmatch(r"DOCUMENT_[A-Z_]+", message or "")
            else "DATABASE_STAGE_REJECTED"
        )
        raise DocumentStageConflict(code) from None
    return totals
