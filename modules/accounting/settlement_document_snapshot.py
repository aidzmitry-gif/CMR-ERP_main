"""Directory identity for sales invoices and procurement receipt revisions."""

import re

from sqlalchemy import or_, select

from modules.accounting import service
from modules.procurement.models import Supplier
from modules.procurement.receipt_documents import ReceiptDocument, ReceiptRevision
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding
from modules.sales.models import DealDocument, DocumentPackage

SETTLEMENT_DOCUMENT_KEYS = {
    "settlement_document", "settlement_document_source", "settlement_document_id",
    "settlement_document_number", "settlement_document_version",
}


def _positive_id(value, message):
    if (not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value)
            or len(value) > 10 or int(value) > 2147483647):
        raise service.AccountingError(message)
    return int(value)


def procurement_result(row, revision):
    number = revision.document.get("invoice_reference") if isinstance(revision.document, dict) else None
    if not isinstance(number, str) or not number:
        return None
    return {"source": "procurement", "id": row.id, "number": number,
            "version": revision.version,
            "reference": f"procurement:receipt:{row.id}:{revision.version}"}


def sales_result(row):
    return {"source": "sales", "id": row.id, "number": row.number,
            "version": row.version, "reference": f"sales:document:{row.id}"}


async def options(session, org_id: int, counterparty_id: int, term: str):
    receipt_filters = [
        ReceiptRevision.document["invoice_reference"].as_string().icontains(
            term, autoescape=True),
    ]
    if term.isascii() and term.isdecimal() and int(term) <= 2147483647:
        receipt_filters.append(ReceiptDocument.id == int(term))
    receipt_pairs = (await session.execute(select(ReceiptDocument, ReceiptRevision).join(
        ReceiptRevision, (ReceiptRevision.receipt_id == ReceiptDocument.id)
        & (ReceiptRevision.version == ReceiptDocument.current_version)).join(
        Supplier, Supplier.id == ReceiptRevision.document["supplier_id"].as_integer()).where(
            ReceiptDocument.organization_id == org_id,
            Supplier.counterparty_id == counterparty_id,
            or_(*receipt_filters),
        ).order_by(ReceiptDocument.id.desc()).limit(51))).all()
    sales_filters = [DealDocument.number.icontains(term, autoescape=True)]
    if term.isascii() and term.isdecimal() and int(term) <= 2147483647:
        sales_filters.append(DealDocument.id == int(term))
    sales_rows = (await session.scalars(select(DealDocument).join(
        DealOwnership, DealOwnership.deal_id == DealDocument.deal_id).join(
        DealClientBinding, DealClientBinding.deal_id == DealDocument.deal_id).where(
            DealOwnership.organization_id == org_id,
            DealClientBinding.organization_id == org_id,
            DealClientBinding.counterparty_id == counterparty_id,
            DealDocument.kind == "invoice", DealDocument.superseded_by_id.is_(None),
            DealDocument.issued_at.is_not(None), DealDocument.content_sha256.is_not(None),
            DealDocument.status.in_(("issued", "posted", "paid")), or_(*sales_filters),
        ).order_by(DealDocument.number, DealDocument.id).limit(51))).all()
    items = [item for row, revision in receipt_pairs
             if (item := procurement_result(row, revision)) is not None]
    items.extend(sales_result(row) for row in sales_rows)
    items.sort(key=lambda item: (item["number"], item["source"], item["id"]))
    return items[:50], len(items) > 50 or len(receipt_pairs) > 50 or len(sales_rows) > 50


def _expected(current):
    return {"settlement_document": current["reference"] if current else None,
            "settlement_document_source": current["source"] if current else None,
            "settlement_document_id": str(current["id"]) if current else None,
            "settlement_document_number": current["number"] if current else None,
            "settlement_document_version": str(current["version"]) if current else None}


async def verified_settlement_document_snapshot(session, org_id: int,
                                                dimensions: dict[str, str]):
    counterparty_id = _positive_id(
        dimensions.get("counterparty_id", ""),
        "Select the counterparty before the settlement document")
    document_id = _positive_id(
        dimensions.get("settlement_document_id", ""),
        "Select the settlement document from the document register")
    source = dimensions.get("settlement_document_source")
    if source == "procurement":
        pair = (await session.execute(select(ReceiptDocument, ReceiptRevision).join(
            ReceiptRevision, (ReceiptRevision.receipt_id == ReceiptDocument.id)
            & (ReceiptRevision.version == ReceiptDocument.current_version)).join(
            Supplier, Supplier.id == ReceiptRevision.document["supplier_id"].as_integer()).where(
                ReceiptDocument.id == document_id,
                ReceiptDocument.organization_id == org_id,
                Supplier.counterparty_id == counterparty_id,
            ).with_for_update(read=True).execution_options(populate_existing=True))).first()
        row, revision = pair if pair is not None else (None, None)
        current = procurement_result(row, revision) if row is not None else None
        receipt_contract = (revision.document.get("contract_id")
                            if revision is not None and isinstance(revision.document, dict) else None)
        if dimensions.get("contract_source") == "procurement" and (
                dimensions.get("contract_id") != str(receipt_contract)):
            current = None
    elif source == "sales":
        row = await session.scalar(select(DealDocument).join(
            DealOwnership, DealOwnership.deal_id == DealDocument.deal_id).join(
            DealClientBinding, DealClientBinding.deal_id == DealDocument.deal_id).where(
                DealDocument.id == document_id,
                DealOwnership.organization_id == org_id,
                DealClientBinding.organization_id == org_id,
                DealClientBinding.counterparty_id == counterparty_id,
                DealDocument.kind == "invoice",
            ).with_for_update(read=True).execution_options(populate_existing=True))
        current = (sales_result(row) if row is not None and row.superseded_by_id is None
                   and row.issued_at is not None and row.content_sha256
                   and row.status in {"issued", "posted", "paid"} else None)
        if current is not None and dimensions.get("contract_source") == "sales":
            contract_id = _positive_id(
                dimensions.get("contract_id", ""), "Select the sales contract again")
            linked = await session.scalar(select(DocumentPackage.id).where(
                DocumentPackage.invoice_id == row.id,
                DocumentPackage.contract_id == contract_id,
                DocumentPackage.deal_id == row.deal_id))
            if linked is None:
                current = None
    else:
        raise service.AccountingError(
            "Select the settlement document from the document register")
    if current is None or any(
            dimensions.get(key) != value for key, value in _expected(current).items()):
        raise service.AccountingError(
            "Settlement document register record changed; select it again")
    return row
