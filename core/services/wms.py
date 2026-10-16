"""Transactional facade for exact invoice reservations; no user routes here."""
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol


class WmsReservationGateway(Protocol):
    async def production_receipt_status(self, session, organization_id: int, event_id: int, source: dict) -> dict: ...

    async def receiving_places(self, session, query: str) -> list[dict]: ...

    async def receiving_place(self, session, warehouse: str, location_id: int) -> dict: ...

    async def receipt_reconciliation(self, session: Any, organization_id: int, source: dict) -> dict:
        """Read explicit primary bindings and QC quantities for an authorized, locked book."""
        ...

    async def invoice_fulfillment_snapshot(self, session: Any, organization_id: int,
                                          source: dict) -> dict:
        """Verified local reservation/pick/physical history, not legacy coverage.

        Caller owns organization/deal/document locks. Preserve any physical act
        even if later movements restore the balance; corruption raises. Return
        actual persisted facts and a deterministic digest, never commit or issue
        a no-shipment certificate from absence of locally observed movements.
        """
        ...

    async def accounting_shipment_source(self, session: Any, organization_id: int,
                                         key: str, sales_source: Any) -> dict | None:
        """Read a verified existing act and its printable view for an authorized book.

        Caller authorizes book membership and holds the org lock. Revalidate Sales
        ownership/exact original and WMS links; never create stock or commit.
        """
        ...

    async def invoice_shipment_preview(self, session: Any, organization_id: int, source: dict) -> dict:
        """Caller authorizes org, locks it and supplies verified exact Sales facts."""
        ...

    async def create_invoice_shipment(self, session: Any, organization_id: int, source: dict,
                                      request: dict, actor: str) -> dict:
        """Atomic physical/reservation act inside the caller's transaction.

        Caller owns authorization, org/Sales locks, source_changed for first
        creation and exact-ID outbox emission; this facade never commits.
        """
        ...

    async def invoice_shipment_by_key(self, session: Any, organization_id: int,
                                     document_id: int, key: str) -> dict | None:
        """Return verified historical receipt only within caller-authorized scope."""
        ...

    async def invoice_shipments_register(self, session: Any, organization_id: int,
                                        document_ids: list[int]) -> dict:
        """Return verified internal WMS acts for exact invoice IDs.

        The result is a read-only document-register projection.  It must keep
        internal acts distinct from statutory TN/TTN documents and return an
        explicit coverage status when no certified external document exists.
        """
        ...

    async def invoice_availability(self, session: Any, organization_id: int,
                                   sku_codes: list[str]) -> dict:
        """Caller authorizes and holds org lock. Null physical/free means unknown.

        Exact physical minus current ERP reserves, no global stock or 1C fallback.
        This observation neither reserves stock nor confirms journal completeness.
        """
        ...

    async def reserve_invoice(self, session: Any, organization_id: int, source: dict,
                              request: dict, actor: str) -> dict:
        """Reserve exact original invoice lines in the caller's transaction.

        Caller authorizes the actor, holds org/deal/invoice locks and supplies
        verified Sales source facts. Request contains explicit warehouse/line
        allocations and physical-journal evidence. Never commit, move physical
        stock, call 1C, or substitute global/default-warehouse availability.
        """
        ...

    async def invoice_release_preview(self, session: Any, organization_id: int,
                                      source: dict) -> dict:
        """Caller holds org/deal/invoice locks and provides verified Sales facts."""
        ...

    async def release_invoice(self, session: Any, organization_id: int, source: dict,
                              request: dict, actor: str, fulfillment_verifier: Any) -> dict:
        """Release exact unshipped reserve under caller's transaction; never commit.

        Caller owns money/CRM permissions. Verifier must dereference persisted
        fulfillment evidence, not trust client flags. This does not cancel sales.
        """
        ...


@dataclass(frozen=True)
class EvidenceReference:
    scope: str
    record_id: str
    revision: str
    sha256: str


@dataclass(frozen=True)
class VerifiedNoShipment:
    organization_id: int
    document_id: int
    document_version: int
    content_sha256: str
    reservation_digest: str
    review_id: str
    review_digest: str
    reviewed_by: str
    references: tuple[EvidenceReference, ...]


class FulfillmentVerifier(Protocol):
    async def verify_no_shipment(self, session, organization_id, source, review_id,
                                 expected_review_digest) -> VerifiedNoShipment:
        """Dereference current server-side records under caller's locks, or raise.

        Required scopes: wms_issue, wms_pick, logistics_shipment, accounting_issue,
        legacy_fulfillment. Each record_id/revision/hash must resolve to stored
        evidence, including explicit negative inventory/coverage reviews for an
        empty scope. Do not construct this result from client flags or echo IDs.
        Review signature/authority and external-history coverage are verifier
        responsibilities. No unknown/partial review may return VerifiedNoShipment.
        Revalidate generation/coverage on every FIRST release, never commit.
        """
        ...


def no_shipment_review_digest(review: VerifiedNoShipment):
    """Canonical manifest fingerprint; verifier must also resolve its references."""
    return _review_hash({"organization_id": review.organization_id, "document_id": review.document_id,
        "document_version": review.document_version, "content_sha256": review.content_sha256,
        "reservation_digest": review.reservation_digest, "review_id": review.review_id,
        "reviewed_by": review.reviewed_by, "references": sorted([
            {"scope": r.scope, "record_id": r.record_id, "revision": r.revision, "sha256": r.sha256}
            for r in review.references], key=_review_json)})



def _review_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _review_hash(value):
    return hashlib.sha256(_review_json(value).encode()).hexdigest()
