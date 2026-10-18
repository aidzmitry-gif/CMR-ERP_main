"""Internal sales source contract for transactional event consumers."""
from typing import Any, Protocol


class SalesSourceGateway(Protocol):
    async def authorize_shipping_deal(self, session: Any, deal_id: int, user: Any) -> None:
        """Verify persisted Sales visibility; no foreign-module ORM or commit."""
        ...

    async def invoice_shipping_source(
        self, session: Any, document_id: int, *, organization_id: int,
        expected_version: int, expected_content_sha256: str,
        operation: str = "fulfill",
    ) -> dict:
        """Lock and verify the exact original invoice for a logistics operation.

        Caller authorizes the actor and holds the discovered organization lock
        before invoking this internal facade; caller owns commit/rollback.
        `historical_claim` permits attribution of terminal history only, never
        new fulfillment. Neither result grants user access or proves stock.
        """
        ...

    async def invoice_organization(self, session: Any, document_id: int) -> int:
        """Read explicit immutable ownership without row locks.

        Discovery only: lock that organization, then reload the locked invoice
        and compare ownership before using any source facts.
        """
        ...

    async def invoice_reservation(self, session: Any, document_id: int) -> dict:
        """Lock source and return its explicit owner and original goods quantities.

        Internal outbox use only; this is not a user-facing authorization grant.
        The caller owns the transaction, holds the discovered organization lock,
        and must compare event facts and the locked owner to the discovery result.
        """
        ...

    async def invoice_financial_source(
        self, session: Any, document_id: int, *, organization_id: int,
        expected_version: int, expected_content_sha256: str,
    ) -> dict:
        """Return locked exact invoice/receipt facts for a receivable projection.

        Caller holds the explicit organization lock and owns the transaction.
        Includes current terminal/replacement state; supports stock/on_order.
        No user grant, reservation requirement, shipment proof or cash fact.
        """
        ...

    async def invoice_financial_lifecycle(
        self, session: Any, document_id: int, *, organization_id: int,
        expected_version: int, expected_content_sha256: str,
    ) -> dict:
        """Exact original plus verified cancellation and one predecessor only.

        Internal event caller holds the organization lock; no cash assertion.
        """
        ...
