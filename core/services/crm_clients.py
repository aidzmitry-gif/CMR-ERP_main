"""Read-only CRM link contract; implementation belongs to Sales."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from core.services.crm_access import CrmAccess


@dataclass(frozen=True)
class CrmClientLink:
    client_id: int
    contact_id: int | None
    owner_id: int
    client_name: str
    client_unp: str | None
    contact_name: str | None
    phone: str | None
    email: str | None


class CrmClientLookupGateway(Protocol):
    async def resolve_link(self, session: AsyncSession, *, actor: CrmAccess,
                           client_id: int, contact_id: int | None,
                           expected_owner_id: int, lock: bool | Literal["shared"] = False) -> CrmClientLink: ...
