"""Verified historical closing receipts, separate from current period state."""
from sqlalchemy import select

from modules.accounting import closing_commands
from modules.accounting.models import (
    FinancialCloseReceipt,
    FinancialReopenItem,
    FinancialReopenReceipt,
    Period,
)


async def history(session, org_id, month):
    await closing_commands.authenticated_entries(session, org_id)
    period = await session.scalar(select(Period).where(
        Period.organization_id == org_id, Period.month == month,
    ))
    rows = (await session.execute(select(FinancialCloseReceipt, FinancialReopenItem, FinancialReopenReceipt)
        .outerjoin(FinancialReopenItem, FinancialReopenItem.close_receipt_id == FinancialCloseReceipt.id)
        .outerjoin(FinancialReopenReceipt, FinancialReopenReceipt.id == FinancialReopenItem.reopen_receipt_id)
        .where(FinancialCloseReceipt.organization_id == org_id, FinancialCloseReceipt.month == month)
        .order_by(FinancialCloseReceipt.id))).all()
    return {"organization_id": org_id, "month": month, "period_closed": bool(period and period.closed),
        "receipts": [{"id": row.id, "actor": row.actor, "created_at": row.created_at,
            "monthly_entry_id": row.monthly_entry_id, "annual_entry_id": row.annual_entry_id,
            "evidence": row.command["evidence"], "policy_id": row.snapshot["preview"]["policy_id"],
            "reopening": {"id": reopened.id, "actor": reopened.actor, "created_at": reopened.created_at,
                "reason": reopened.command["reason"], "monthly_entry_id": item.monthly_entry_id,
                "annual_entry_id": item.annual_entry_id} if reopened else None}
            for row, item, reopened in rows]}
