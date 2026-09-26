"""Validate a SKU ID and its saved accounting-document description."""

import re

from sqlalchemy import select

from core.domain.models import Sku
from modules.accounting import service


async def verified_sku_snapshot(session, dimensions: dict[str, str]):
    raw_id = dimensions.get("sku_id", "")
    if (not isinstance(raw_id, str) or not re.fullmatch(r"[1-9][0-9]*", raw_id)
            or len(raw_id) > 10 or int(raw_id) > 2147483647):
        raise service.AccountingError("Select the item from the SKU directory")
    row = await session.scalar(select(Sku).where(Sku.id == int(raw_id))
                               .with_for_update(read=True).execution_options(populate_existing=True))
    if (row is None or not row.is_active or dimensions.get("sku") != row.code
            or dimensions.get("sku_title") != row.title
            or dimensions.get("sku_unit") != row.unit):
        raise service.AccountingError("SKU directory record changed; select it again")
    return row
