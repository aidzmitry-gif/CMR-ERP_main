"""Internal logistics boundary. DTOs contain identities, never authorization proofs."""
from datetime import UTC, date, datetime
from decimal import Decimal
from math import isfinite
from typing import Annotated, Any, Literal, Protocol

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExactInvoiceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    organization_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    expected_version: int = Field(gt=0)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


SnapshotHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveId = Annotated[int, Field(gt=0)]


class SnapshotDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourceDiscoveryV1(SnapshotDTO):
    source_kind: Literal["order", "office"]
    exact_invoice: ExactInvoiceIdentity
    source_keys: list[str]
    source_document_ids: list[PositiveId]


class SnapshotSourceIdentity(SnapshotDTO):
    kind: Literal["order", "office"]
    key: str = Field(min_length=1, max_length=200)
    revision: str = Field(pattern=r"^[1-9][0-9]*$")


class SnapshotEnvelope(SnapshotDTO):
    record_id: str = Field(min_length=1)
    row_sha256: SnapshotHash
    payload_sha256: SnapshotHash
    payload: dict

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value):
        # Lazy import: shipping_payload itself depends on ExactInvoiceIdentity.
        from core.services.shipping_payload import ShippingPayload

        return ShippingPayload.model_validate(value).model_dump()


class SnapshotAssociation(SnapshotDTO):
    record_id: str = Field(min_length=1)
    revision: Literal["1"]
    row_sha256: SnapshotHash


class ProducerSourceSnapshot(SnapshotDTO):
    source: SnapshotSourceIdentity
    envelope: SnapshotEnvelope
    association: SnapshotAssociation
    execution_id: str = Field(min_length=36, max_length=36)
    intent_digest: SnapshotHash
    source_state_sha256: SnapshotHash
    fulfillment_allowed: bool

    @model_validator(mode="after")
    def consistent(self):
        from uuid import UUID

        if (self.envelope.payload["source"] != self.source.model_dump()
                or snapshot_hash(self.envelope.payload) != self.envelope.payload_sha256
                or str(UUID(self.execution_id)) != self.execution_id):
            raise ValueError("Producer snapshot attribution mismatch")
        return self


class ProducerSourcesSnapshotV1(SnapshotDTO):
    schema_version: Literal[1]
    exact_invoice: ExactInvoiceIdentity
    sources: list[ProducerSourceSnapshot]
    coverage_complete: Literal[False]
    coverage_gaps: list[Literal["unassociated_sources_not_attributable"]]
    sha256: SnapshotHash

    @field_validator("schema_version", "coverage_complete", mode="before")
    @classmethod
    def exact_literals(cls, value, info):
        if (info.field_name == "schema_version" and type(value) is not int
                or info.field_name == "coverage_complete" and value is not False):
            raise ValueError("Snapshot literals must be exact")
        return value

    @model_validator(mode="after")
    def consistent(self):
        keys = [(s.source.kind, s.source.key, s.source.revision) for s in self.sources]
        if (keys != sorted(set(keys)) or self.coverage_gaps != ["unassociated_sources_not_attributable"]
                or snapshot_hash(self.model_dump(exclude={"sha256"})) != self.sha256):
            raise ValueError("Producer snapshot digest or ordering mismatch")
        return self


def snapshot_value(value):
    """Deterministic lossless JSON representation of persisted column values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Nonfinite persisted decimal")
        return format(value, "f")
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Nonfinite persisted float")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(UTC).isoformat(timespec="microseconds")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [snapshot_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: snapshot_value(item) for key, item in value.items()}
    raise ValueError("Unsupported persisted snapshot value")


def snapshot_row(row):
    return {column.name: snapshot_value(getattr(row, column.name)) for column in row.__table__.columns}


def snapshot_hash(value):
    from core.services.shipping_payload import canonical_hash

    return canonical_hash(snapshot_value(value))


def producer_sources_snapshot(exact_invoice, sources):
    body = {"schema_version": 1, "exact_invoice": ExactInvoiceIdentity.model_validate(exact_invoice).model_dump(),
        "sources": sorted(sources, key=lambda s: (s["source"]["kind"], s["source"]["key"], s["source"]["revision"])),
        "coverage_complete": False, "coverage_gaps": ["unassociated_sources_not_attributable"]}
    return ProducerSourcesSnapshotV1.model_validate({**body, "sha256": snapshot_hash(body)}).model_dump()


class ShippingProducerGateway(Protocol):
    async def discover_invoice_shipping_sources(self, session: Any, *, exact_invoice: dict, user: Any) -> dict:
        """Discovery only: exact-bound source IDs, no row locks or inferred links."""
        ...

    async def lock_invoice_shipping_sources_snapshot(self, session: Any, *, exact_invoice: dict,
                                                     user: Any, discovery: dict) -> dict:
        """Caller holds org; Sales locks deal/all docs before Office locks own sources."""
        ...

    async def verify_shipping_source(self, session: Any, *, source_kind: str, source_key: str,
                                     source_revision: str, actual_payload_hash: str, user: Any = None) -> dict | None:
        """Under caller org/doc locks, lock own source and verify persisted provenance.

        Return exact_invoice, execution_id, intent_digest, payload_sha256 and association identity.
        Include strict bool fulfillment_allowed, rechecked under the source lock.
        False preserves immutable attribution but forbids a new fulfillment;
        only an already resolved persisted intake may replay that attribution.
        Recheck record authorization for manual requests; no commit or payload-based authority.
        """
        ...

    async def resolve_shipping_source(self, session: Any, *, source_kind: str,
                                     source_key: str, source_revision: str) -> dict | None:
        """Dereference persisted producer association; never infer from payload.

        Return ExactInvoiceIdentity fields, or None for unresolved. No commit.
        Must verify producer revision and ownership, not accept client proof.
        Discovery only: no row locks, writes, or commit; caller locks and revalidates.
        Association writers must serialize on the affected organization lock.
        """
        ...

    async def authorize_shipping_intake(self, session: Any, *, source_kind: str,
                                       source_key: str, user: Any) -> None:
        """Raise unless user is assigned access to this producer-owned record."""
        ...


class LogisticsGateway(Protocol):
    def assert_unexecuted_invoice(self, snapshot: dict) -> None:
        """Reject known engagement/execution in caller-collected exact snapshot."""
        ...

    async def withdraw_unexecuted_invoice(self, session: Any, *, prepared: Any, current_snapshot: dict,
                                         expected_digest: str, cancel_receipt_identity: dict) -> dict:
        """Internal app-only withdrawal; caller owns atomic Sales receipt/cancel."""
        ...

    async def prepare_invoice_fulfillment_snapshot(self, session: Any, *, exact_invoice: dict,
                                                  user: Any) -> Any:
        """Lock org/all producer sources; return internal same-root-transaction context.

        Between prepare and collect, trusted caller only reads and acquires locks,
        never changes business/source rows (including raw SQL or flushed writes).
        No savepoints. Context is not serializable authority or coverage evidence.
        """
        ...

    async def collect_prepared_invoice_fulfillment_snapshot(self, session: Any, prepared: Any) -> dict:
        """Collect under Logistics gate, without new organization/source callbacks."""
        ...

    async def invoice_fulfillment_snapshot(self, session: Any, *, exact_invoice: dict, user: Any) -> dict:
        """Read current exact source rows; enter before partial source/gate locks.

        Holds org -> Sales union docs -> Office sources -> existing Logistics gate.
        No commit or business writes; technical gate initialization is allowed.
        """
        ...

    async def claim_execution(self, session: Any, *, exact_invoice: dict, intent: dict,
                              expected_digest: str) -> dict:
        """Claim or match immutable intent under caller org/doc/source locks, no commit."""
        ...

    async def invoice_shipments_snapshot(self, session: Any, source: dict) -> dict:
        """Caller holds org/deal/doc locks. Application-only journal, not DB proof."""
        ...


class ShippingProducerDispatcher:
    """Route only to the two explicit source owners; never inspect foreign ORM."""
    def __init__(self, *, order: ShippingProducerGateway | None = None, office: ShippingProducerGateway | None = None):
        self._adapters = {}
        for kind, adapter in (("order", order), ("office", office)):
            if adapter is not None:
                self.register(kind, adapter)

    def register(self, source_kind: str, adapter: ShippingProducerGateway) -> None:
        if source_kind not in {"order", "office"} or adapter is None:
            raise ValueError("Unsupported shipping producer registration")
        if source_kind in self._adapters:
            raise ValueError("Shipping producer already registered")
        self._adapters[source_kind] = adapter

    def _adapter(self, source_kind: str):
        if not isinstance(source_kind, str) or source_kind not in self._adapters:
            raise HTTPException(409, "Unsupported shipping producer")
        return self._adapters[source_kind]

    async def invoice_shipping_sources_snapshot(self, session, *, exact_invoice, user):
        """Caller holds org, no partial Sales/Office/gate locks. Never commits."""
        exact = ExactInvoiceIdentity.model_validate(exact_invoice).model_dump()
        if set(self._adapters) != {"order", "office"}:
            raise HTTPException(503, "Shipping snapshot adapters unavailable")
        discoveries = {}
        for kind in ("order", "office"):
            adapter = self._adapter(kind)
            if not callable(getattr(adapter, "discover_invoice_shipping_sources", None)) or not callable(
                getattr(adapter, "lock_invoice_shipping_sources_snapshot", None)
            ):
                raise HTTPException(503, "Shipping snapshot adapter contract unavailable")
            discovery = SourceDiscoveryV1.model_validate(await adapter.discover_invoice_shipping_sources(
                session, exact_invoice=exact, user=user))
            if discovery.source_kind != kind or discovery.exact_invoice.model_dump() != exact:
                raise HTTPException(409, "Shipping source discovery changed")
            discoveries[kind] = discovery.model_dump()
        sources = []
        for kind in ("order", "office"):
            result = ProducerSourcesSnapshotV1.model_validate(await self._adapter(kind).lock_invoice_shipping_sources_snapshot(
                session, exact_invoice=exact, user=user, discovery=discoveries[kind]))
            if result.exact_invoice.model_dump() != exact or any(row.source.kind != kind for row in result.sources):
                raise HTTPException(409, "Shipping snapshot source changed")
            sources.extend(row.model_dump() for row in result.sources)
        return producer_sources_snapshot(exact, sources)

    async def resolve_shipping_source(self, session, *, source_kind, source_key, source_revision):
        return await self._adapter(source_kind).resolve_shipping_source(session, source_kind=source_kind,
            source_key=source_key, source_revision=source_revision)

    async def authorize_shipping_intake(self, session, *, source_kind, source_key, user):
        return await self._adapter(source_kind).authorize_shipping_intake(session, source_kind=source_kind,
            source_key=source_key, user=user)

    async def verify_shipping_source(self, session, *, source_kind, source_key, source_revision,
                                     actual_payload_hash, user=None):
        return await self._adapter(source_kind).verify_shipping_source(session, source_kind=source_kind,
            source_key=source_key, source_revision=source_revision, actual_payload_hash=actual_payload_hash, user=user)
