"""Organization and counterparty scoped contract identities for ledger analytics."""

import re

from sqlalchemy import or_, select

from modules.accounting import service
from modules.procurement.models import Supplier
from modules.procurement.supplier_contracts import SupplierContract
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding
from modules.sales.models import DealDocument

CONTRACT_KEYS = {
    "contract", "contract_source", "contract_id", "contract_title", "contract_version",
}


def _positive_id(value, message):
    if (not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value)
            or len(value) > 10 or int(value) > 2147483647):
        raise service.AccountingError(message)
    return int(value)


def supplier_result(row):
    return {"source": "procurement", "id": row.id, "number": row.number,
            "title": row.title, "version": 1}


def sales_result(row):
    return {"source": "sales", "id": row.id, "number": row.number,
            "title": "Договор продажи", "version": row.version}


async def options(session, org_id: int, counterparty_id: int, term: str):
    """Return current contract directory rows from procurement and sales."""
    filters = [SupplierContract.number.icontains(term, autoescape=True),
               SupplierContract.title.icontains(term, autoescape=True)]
    sales_filters = [DealDocument.number.icontains(term, autoescape=True)]
    if term.isascii() and term.isdecimal() and int(term) <= 2147483647:
        filters.append(SupplierContract.id == int(term))
        sales_filters.append(DealDocument.id == int(term))
    supplier_rows = (await session.scalars(select(SupplierContract).join(
        Supplier, Supplier.id == SupplierContract.supplier_id).where(
            SupplierContract.organization_id == org_id,
            Supplier.counterparty_id == counterparty_id,
            SupplierContract.is_active.is_(True), or_(*filters),
        ).order_by(SupplierContract.number, SupplierContract.id).limit(51))).all()
    sales_rows = (await session.scalars(select(DealDocument).join(
        DealOwnership, DealOwnership.deal_id == DealDocument.deal_id).join(
        DealClientBinding, DealClientBinding.deal_id == DealDocument.deal_id).where(
            DealOwnership.organization_id == org_id,
            DealClientBinding.organization_id == org_id,
            DealClientBinding.counterparty_id == counterparty_id,
            DealDocument.kind == "contract", DealDocument.superseded_by_id.is_(None),
            DealDocument.issued_at.is_not(None), DealDocument.content_sha256.is_not(None),
            DealDocument.status.in_(("issued", "posted", "paid")), or_(*sales_filters),
        ).order_by(DealDocument.number, DealDocument.id).limit(51))).all()
    items = sorted([*(supplier_result(row) for row in supplier_rows),
                    *(sales_result(row) for row in sales_rows)],
                   key=lambda item: (item["number"], item["source"], item["id"]))
    return items[:50], len(items) > 50 or len(supplier_rows) > 50 or len(sales_rows) > 50


async def verified_contract_snapshot(session, org_id: int, dimensions: dict[str, str]):
    """Lock and verify the exact current contract selected for a new write."""
    counterparty_id = _positive_id(
        dimensions.get("counterparty_id", ""), "Select the counterparty before the contract")
    contract_id = _positive_id(
        dimensions.get("contract_id", ""), "Select the contract from the contract directory")
    source = dimensions.get("contract_source")
    if source == "procurement":
        row = await session.scalar(select(SupplierContract).join(
            Supplier, Supplier.id == SupplierContract.supplier_id).where(
                SupplierContract.id == contract_id,
                SupplierContract.organization_id == org_id,
                Supplier.counterparty_id == counterparty_id,
            ).with_for_update(read=True).execution_options(populate_existing=True))
        current = supplier_result(row) if row is not None and row.is_active else None
    elif source == "sales":
        row = await session.scalar(select(DealDocument).join(
            DealOwnership, DealOwnership.deal_id == DealDocument.deal_id).join(
            DealClientBinding, DealClientBinding.deal_id == DealDocument.deal_id).where(
                DealDocument.id == contract_id,
                DealOwnership.organization_id == org_id,
                DealClientBinding.organization_id == org_id,
                DealClientBinding.counterparty_id == counterparty_id,
                DealDocument.kind == "contract",
            ).with_for_update(read=True).execution_options(populate_existing=True))
        current = (sales_result(row) if row is not None and row.superseded_by_id is None
                   and row.issued_at is not None and row.content_sha256
                   and row.status in {"issued", "posted", "paid"} else None)
    else:
        raise service.AccountingError("Select the contract from the contract directory")
    expected = {"contract": current["number"] if current else None,
                "contract_source": current["source"] if current else None,
                "contract_id": str(current["id"]) if current else None,
                "contract_title": current["title"] if current else None,
                "contract_version": str(current["version"]) if current else None}
    if current is None or any(dimensions.get(key) != value for key, value in expected.items()):
        raise service.AccountingError("Contract directory record changed; select it again")
    return row
