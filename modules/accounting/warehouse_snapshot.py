"""Validate an organization-owned warehouse and its saved document snapshot."""

import re

from sqlalchemy import select

from modules.accounting import service
from modules.wms.models import WarehouseDirectory


async def verified_warehouse_snapshot(session, org_id: int, dimensions: dict[str, str]):
    raw_id = dimensions.get("warehouse_id", "")
    if (not isinstance(raw_id, str) or not re.fullmatch(r"[1-9][0-9]*", raw_id)
            or len(raw_id) > 10 or int(raw_id) > 2147483647):
        raise service.AccountingError("Select the warehouse from the organization directory")
    row = await session.scalar(select(WarehouseDirectory).where(
        WarehouseDirectory.id == int(raw_id),
        WarehouseDirectory.organization_id == org_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if (row is None or not row.is_active or dimensions.get("warehouse") != row.name
            or dimensions.get("warehouse_title") != row.title):
        raise service.AccountingError("Warehouse directory record changed; select it again")
    return row
