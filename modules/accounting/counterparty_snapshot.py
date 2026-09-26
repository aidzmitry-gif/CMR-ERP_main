"""Validate an MDM counterparty ID and its historical document snapshot."""

import re

from sqlalchemy import select

from core.domain.models import Counterparty
from modules.accounting import service


async def verified_counterparty(session, dimensions: dict[str, str], *, role: str = "Counterparty"):
    raw_id = dimensions.get("counterparty_id", "")
    if (not isinstance(raw_id, str) or not re.fullmatch(r"[1-9][0-9]*", raw_id)
            or len(raw_id) > 10 or int(raw_id) > 2147483647):
        raise service.AccountingError(f"Select the {role.lower()} from the counterparty directory")
    row = await session.scalar(select(Counterparty).where(Counterparty.id == int(raw_id))
                               .with_for_update(read=True).execution_options(populate_existing=True))
    if (row is None or not row.is_active or row.merged_into_id is not None
            or dimensions.get("counterparty") != (row.legal_name or row.name)
            or dimensions.get("counterparty_unp") != (row.unp or "")
            or dimensions.get("counterparty_revision") != str(row.revision)):
        raise service.AccountingError(f"{role} directory record changed; select it again")
    return row
