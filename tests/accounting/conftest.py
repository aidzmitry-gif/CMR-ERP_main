from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base
from core.domain.models import Counterparty, IdentityInvitationRequest, Sku, User
from core.domain.reference import Currency
from core.runtime.deps import get_session
from core.services.auth import CurrentUser, get_current_user
from modules.accounting import models, routes
from modules.accounting.gateway import AccountingService
from modules.finance.models import BankAccount, BankTransaction, Payment, PaymentAllocation
from modules.hr.models import Employee
from modules.logistics import models as logistics_models
from modules.procurement import deal_demands, expected_reservations, ownership, receipt_documents
from modules.procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseRequest
from modules.sales.accounting_ownership import DealOwnership
from modules.sales.client_document_register import DealClientBinding
from modules.sales.deal_loss import DealLossRequest
from modules.sales.invoice_cancellation import InvoiceCancellationReceipt, SalesFulfillmentReview
from modules.sales.invoice_issuance import InvoiceIssuanceReceipt
from modules.sales.invoice_reconciliation import InvoiceMoneyReconciliation
from modules.sales.invoice_settlements import InvoiceSettlement
from modules.sales.models import Deal, DealDocument, DealItem, Stage

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", execution_options={
        "schema_translate_map": {"accounting": None, "procurement": None, "sales": None, "logistics": None, "finance": None, "hr": None},
    })
    tables = [Currency.__table__, Employee.__table__,
              *[t for t in Base.metadata.sorted_tables if t.schema == "accounting"]]
    tables += [receipt_documents.ReceiptDocument.__table__, receipt_documents.ReceiptRevision.__table__]
    tables += [receipt_documents.ReceiptPosting.__table__]
    tables += [PurchaseOrder.__table__, PurchaseRequest.__table__, ownership.PurchaseOwnership.__table__, ownership.OrderRequestLink.__table__]
    tables += [PurchaseOrderLine.__table__]
    tables += [expected_reservations.ExpectedReservation.__table__, expected_reservations.ExpectedReservationEvent.__table__, expected_reservations.PhysicalReceiptAcceptance.__table__, expected_reservations.ExpectedConversionRequest.__table__]
    tables += [Stage.__table__, Deal.__table__, DealItem.__table__, DealDocument.__table__, DealOwnership.__table__]
    tables += [DealLossRequest.__table__]
    tables += [InvoiceSettlement.__table__]
    tables += [InvoiceIssuanceReceipt.__table__]
    tables += [InvoiceMoneyReconciliation.__table__]
    tables += [SalesFulfillmentReview.__table__, InvoiceCancellationReceipt.__table__]
    tables += [Counterparty.__table__, DealClientBinding.__table__]
    tables += [Sku.__table__]
    tables += [User.__table__, IdentityInvitationRequest.__table__]
    tables += [BankAccount.__table__, Payment.__table__, PaymentAllocation.__table__, BankTransaction.__table__]
    tables += [logistics_models.ImportShipment.__table__]
    tables += [deal_demands.DealProcurementDemand.__table__, deal_demands.DealProcurementAllocation.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all([Currency(code="USD", title="Test USD"), Currency(code="RUB", title="Test RUB")])
        await session.commit()
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def book(db):
    from datetime import date

    org = models.Organization(name="Synthetic test company", unp="999999999")
    db.add(org)
    await db.flush()
    db.add(models.AccessGrant(organization_id=org.id, subject="tester", role="chief"))
    policy = models.Policy(organization_id=org.id, effective_from=date(2026, 1, 1),
                           reference="TEST ONLY", inventory_method="specific",
                           allocation_basis="direct_cost", depreciation_method="straight_line",
                           normative_reference="synthetic control fixture",
                           normative_verified=True, approved_by="tester")
    db.add(policy)
    for code, title, category, cash in [
        ("41", "Товары", "asset", False), ("51", "Расчетный счет", "asset", True),
        ("60", "Поставщики", "liability", False), ("62", "Покупатели", "asset", False),
        ("80", "Капитал", "equity", False), ("90.1", "Доход", "income", False),
        ("90.4", "Себестоимость", "expense", False),
        ("003", "Имущество клиента", "off_balance", False),
    ]:
        db.add(models.Account(organization_id=org.id, code=code, title=title, category=category,
                              valid_from=date(2026, 1, 1), required_dimensions=[],
                              currency_tracking=True, quantity_tracking=False, cash=cash,
                              normative_ref="synthetic"))
    await db.commit()
    return org.id, policy.id


@pytest_asyncio.fixture
async def client(db, book):
    app = FastAPI()
    app.include_router(routes.router, prefix="/accounting")
    app.include_router(receipt_documents.router, prefix="/procurement")
    app.include_router(deal_demands.router, prefix="/procurement")
    app.include_router(ownership.router, prefix="/procurement")
    app.include_router(expected_reservations.router, prefix="/procurement")
    app.state.core = SimpleNamespace(services=SimpleNamespace(event_bus=None, accounting=AccountingService()))

    async def session():
        yield db

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("tester", ["director"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.test_app = app
        yield c


@pytest.fixture
def posting(book):
    def build(source="doc-1", debit="41", credit="60", amount="100.00", **changes):
        from modules.accounting.schemas import PostingInput

        data = dict(source=source, source_version=1, operation="manual",
                    document_date="2026-09-01", operation_date="2026-09-01",
                    posting_date="2026-09-01", policy_id=book[1], rule_version="manual-v1",
                    explanation="Synthetic approved control transaction", lines=[
                        dict(account=debit, side="debit", amount=amount,
                             **({"cash_activity": "operating"} if debit == "51" else {})),
                        dict(account=credit, side="credit", amount=amount,
                             **({"cash_activity": "operating"} if credit == "51" else {})),
                    ])
        data.update(changes)
        return PostingInput.model_validate(data)
    return build


@pytest.fixture
def opening_package():
    def build(entries, *, batch="opening-test", source_system="1c-export", evidence="Synthetic opening-balance reconciliation"):
        debit = sum((line.amount for entry in entries for line in entry.lines if line.side == "debit"), Decimal("0"))
        credit = sum((line.amount for entry in entries for line in entry.lines if line.side == "credit"), Decimal("0"))
        return {
            "batch": batch,
            "request_key": str(uuid4()),
            "protocol_version": "opening-balance-v1",
            "source_system": source_system,
            "source_digest": "a" * 64,
            "cutover_date": entries[0].posting_date.isoformat(),
            "evidence": evidence,
            "expected_entry_count": len(entries),
            "expected_line_count": sum(len(entry.lines) for entry in entries),
            "expected_debit_byn": format(debit, "f"),
            "expected_credit_byn": format(credit, "f"),
            "entries": [entry.model_dump(mode="json") for entry in entries],
        }
    return build
