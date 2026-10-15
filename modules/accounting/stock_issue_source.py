"""Accounting-owned discovery of immutable invoices for document stock issue."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from core.runtime.deps import get_core, get_session
from core.services.auth import get_current_user
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.models import DealDocument
from modules.wms.invoice_reservations import InvoiceReservation

router = APIRouter()


@router.get("/organizations/{org}/stock-issue-invoices")
async def stock_issue_invoices(org: int, after_id: int = Query(0, ge=0),
                               session=Depends(get_session), core=Depends(get_core),
                               user=Depends(get_current_user)):
    try:
        await core.services.accounting.document_shipment_member(session, org, user)
        rows = (await session.scalars(select(DealDocument).join(
            DealOwnership, DealOwnership.deal_id == DealDocument.deal_id).join(
            InvoiceReservation, InvoiceReservation.document_id == DealDocument.id).where(
                DealOwnership.organization_id == org,
                InvoiceReservation.organization_id == org,
                DealDocument.kind == "invoice", DealDocument.id > after_id,
            ).order_by(DealDocument.id).limit(51))).all()
        return {"organization_id": org, "items": [
            {"document_id": row.id, "deal_id": row.deal_id, "number": row.number,
             "status": row.status} for row in rows[:50]],
            "next_after_id": rows[49].id if len(rows) > 50 else None}
    finally:
        await session.rollback()


@router.get("/organizations/{org}/deals/{deal}/stock-issue-invoices/{document}")
async def stock_issue_identity(org: int, deal: int, document: int,
                               session=Depends(get_session), core=Depends(get_core),
                               user=Depends(get_current_user)):
    try:
        await core.services.accounting.document_shipment_member(session, org, user)
        source = core.services.sales_source
        try:
            if await source.invoice_organization(session, document) != org:
                raise ValueError("Foreign source")
            facts = await source.invoice_reservation(session, document)
        except ValueError as exc:
            raise HTTPException(404, "Invoice source unavailable in this organization") from exc
        if facts["organization_id"] != org or facts["deal_id"] != deal:
            raise HTTPException(404, "Invoice source unavailable in this deal")
        return {"organization_id": org, "document_id": document,
                "deal_id": deal, "document_version": facts["version"],
                "content_sha256": facts["content_sha256"]}
    finally:
        await session.rollback()
