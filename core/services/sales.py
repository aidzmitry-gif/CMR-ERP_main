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
