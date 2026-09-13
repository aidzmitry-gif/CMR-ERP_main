"""Production-owned confirmation verification for warehouse delivery."""
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class ProductionOutputGateway(Protocol):
    async def cost_orders(self, session: AsyncSession, organization_id: int, order_ids: list[int]) -> list[dict]:
        """Verify explicit owners and snapshot cost targets; caller holds authorized org lock."""
        ...

    async def validate_delivery(self, session: AsyncSession, event_id: int, payload: dict) -> dict: ...

    async def output_reconciliation(self, session: AsyncSession, organization_id: int,
                                    order_id: int, warehouse_gateway) -> dict:
        """Return accepted warehouse facts for an owned production order."""
        ...
