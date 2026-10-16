"""Public organization-access contract; consumers never read accounting tables."""
from typing import Any, Protocol


class AccountingGateway(Protocol):
    async def physical_shipment_preview(self, session: Any, organization_id: int,
                                        user: Any, receipt: dict, document: dict) -> dict:
        """Calculate a trusted physical shipment using verified acquisition costs."""
        ...

    async def additional_expense_status(self, session: Any, organization_id: int,
                                        user: Any, expense_id: int) -> dict | None:
        """Return immutable local posting identity, or None for an unposted source."""
        ...

    async def invoice_fulfillment_snapshot(self, session: Any, organization_id: int,
                                         user: Any, document_id: int) -> dict:
        """Exact local ledger references and correction chains, under org lock.

        Returns facts plus digest; never asserts complete external coverage or
        absence of shipment. Caller retains the transaction through cancellation.
        """
        ...

    async def invoice_seller(self, session: Any, organization_id: int, user: Any,
                             on: Any, currency: str) -> dict:
        """Return confirmed, immutable seller requisites for exact org/date/currency.

        Holds org lock and checks membership. Caller must call before deal/doc
        locks and preserve profile_id/digest/seller in its original snapshot.
        Missing requisites block issuance; no global branding or config fallback.
        """
        ...

    async def lock_event_organization(self, session: Any, organization_id: int) -> None:
        """Internal event serialization only; never a user authorization grant.

        Consumer must derive the owner from trusted source identity, acquire this
        lock before document/task locks, then validate the source again. No commit.
        """
        ...

    async def invoice_bank_basis(self, session: Any, organization_id: int, user: Any,
                                 document_id: int) -> dict:
        """Discover exact-invoice bank facts and corrections, including unallocated ones.

        Caller holds org/deal/invoice locks. Return organization_id, document_id,
        entries[{entry_id, digest, correction_of, fact, blockers}]. No commit.
        This is known local ledger scope, not external-history completeness.
        """
        ...

    async def bank_settlement(self, session: Any, organization_id: int, user: Any,
                              entry_id: int) -> dict:
        """Return immutable posted BYN bank evidence; reject corrected/non-bank entries."""
        ...

    async def sale_posting(self, session: Any, organization_id: int, user: Any,
                           document: dict, *, confirm_digest: str | None,
                           basis_digest: str | None = None, event_bus: Any = None) -> dict:
        """Validate/post a registered immutable sale revision in the caller's transaction."""
        ...

    async def source_member(self, session: Any, organization_id: int, user: Any) -> str:
        """Authorize a source member and hold the organization lock until transaction end.

        Call before reading source keys; this does not grant ledger write access.
        """
        ...

    async def source_organizations(self, session: Any, user: Any) -> list[dict]: ...

    async def source_owner_authority(self, session: Any, organization_id: int, user: Any) -> str:
        """Authorize an explicit source-ownership decision by the book's chief."""
        ...

    async def source_changed(self, session: Any, organization_id: int, user: Any,
                             source: str, version: int, operation_date: str) -> None:
        """Register source completeness and invalidate closing checks in caller's transaction."""
        ...

    async def receipt_posting(self, session: Any, organization_id: int, user: Any,
                              document: dict, *, confirm_digest: str | None,
                              event_bus: Any = None) -> dict:
        """Validate/post immutable source facts; caller commits source link and ledger atomically."""
        ...
