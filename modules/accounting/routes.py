"""Organization-scoped APIs; application super-roles do not bypass book membership."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse

from core.runtime.deps import get_core, get_session
from core.services.auth import (
    EffectiveIdentityLookupError,
    get_current_user,
    resolve_effective_dev_user,
    resolve_effective_oidc_user,
)
from core.services.config import get_settings
from core.services.procurement import ReceiptAccountingConfirmation, ReceiptAccountingOptions
from modules.accounting import (
    bank_import,
    bank_statement,
    closing_controls,
    fixed_assets,
    foreign_trade_register,
    fx_revaluation,
    input_vat,
    input_vat_register,
    inventory_cost,
    inventory_issues,
    opening_import,
    output_vat_register,
    reconciliation,
    repair_accounting,
    reports,
    sales,
    seller_profiles,
    service,
    settlement_offsets,
    shipment_drafts,
)
from modules.accounting.documents import BankDocument, preview_bank
from modules.accounting.fixed_assets import (
    FixedAssetDepreciationConfirmInput,
    FixedAssetDepreciationInput,
    FixedAssetRegisterConfirmInput,
    FixedAssetRegisterInput,
)
from modules.accounting.foreign_trade_register import (
    ForeignTradeRegisterConfirmInput,
    ForeignTradeRegisterInput,
)
from modules.accounting.input_vat_register import (
    InputVatRegisterConfirmInput,
    InputVatRegisterInput,
)
from modules.accounting.late_cost_commands import LateCostConfirmation
from modules.accounting.late_cost_receipts import LateCostCommand
from modules.accounting.models import (
    AccessGrant,
    Account,
    Entry,
    Inbox,
    InventoryIssueReceipt,
    Line,
    Organization,
    Period,
    Policy,
    SourceBinding,
    SourceControl,
)
from modules.accounting.output_vat_register import (
    OutputVatRegisterConfirmInput,
    OutputVatRegisterInput,
)
from modules.accounting.payroll_import import (
    PayrollAccrualConfirmInput,
    PayrollAccrualInput,
)
from modules.accounting.payroll_statutory import (
    PayrollStatutoryConfirmInput,
    PayrollStatutoryInput,
)
from modules.accounting.production_cost_correction import (
    ProductionOverheadCorrectionConfirm,
    ProductionOverheadCorrectionPreview,
    ProductionOverheadCorrectionWithdraw,
)
from modules.accounting.production_cost_posting import (
    ProductionOverheadConfirm,
    ProductionOverheadWithdraw,
)
from modules.accounting.production_cost_review import ProductionCostReviewInput
from modules.accounting.production_labor_cost import (
    ProductionLaborConfirmInput,
    ProductionLaborInput,
)
from modules.accounting.production_material_cost import (
    ProductionMaterialIssuePostingConfirmInput,
    ProductionMaterialIssuePostingInput,
    ProductionMaterialIssuePreviewInput,
)
from modules.accounting.production_output_transfer import (
    ProductionOutputTransferConfirmInput,
    ProductionOutputTransferInput,
)
from modules.accounting.purchases import PurchaseDocument, preview_purchase
from modules.accounting.repair_accounting import (
    RepairAccountingConfirmInput,
    RepairAccountingInput,
)
from modules.accounting.schemas import (
    AccountInput,
    CloseInput,
    FinancialCloseInput,
    FinancialReopenConfirmInput,
    FxRevaluationConfirmInput,
    FxRevaluationInput,
    GrantInput,
    ImportInput,
    InventoryIssueConfirm,
    InventoryIssueDocument,
    InventoryIssuePreviewInput,
    InventoryLotQuery,
    LateCostPreviewInput,
    OrganizationInput,
    PolicyInput,
    PostingInput,
    ReconciliationConfirmInput,
    ReconciliationInput,
    ReopenInput,
    SellerProfileInput,
    SourceBindingInput,
)
from modules.accounting.settlement_offsets import (
    SettlementOffsetConfirmInput,
    SettlementOffsetInput,
)
from modules.accounting.shipment_document_draft import build as build_shipment_document_draft
from modules.accounting.shipment_preview import ShipmentConfirmInput, ShipmentPlanInput

router = APIRouter(tags=["Бухгалтерия"])


@router.get("/catalog")
async def get_catalog(user=Depends(get_current_user)):
    from modules.accounting.catalog import catalogue

    subject(user)
    return catalogue()


@router.get("/catalog/accounts")
async def catalog_accounts(user=Depends(get_current_user)):
    data = await get_catalog(user)
    return [{**row, "edition_status": "Через 2022 год; требует проверки на 2026 год"}
            for row in data["accounts"]]


def serialize(row):
    return {c.key: str(value) if isinstance(value := getattr(row, c.key), Decimal) else value
            for c in inspect(row).mapper.column_attrs}


def subject(user):
    if not user.roles or any(r in user.roles for r in ("Гость", "onboarding")):
        raise HTTPException(403, "Accounting access denied")
    value = user.keycloak_user_id or user.username
    if not value or value == "anonymous":
        raise HTTPException(403, "An identified user is required")
    return value


async def transaction(session=Depends(get_session)):
    try:
        yield session
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Conflicting accounting record") from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


async def organization_role(session, org_id, actor):
    """Authorize again after the org lock; membership changes use that lock too."""
    query = select(AccessGrant.role).where(
        AccessGrant.organization_id == org_id, AccessGrant.subject == actor,
    )
    # Reject an unrelated organization without acquiring its transaction lock.
    if await session.scalar(query) not in {"reader", "accountant", "chief"}:
        raise HTTPException(403, "No access to this organization's books")
    await service.lock_organization(session, org_id)
    role = await session.scalar(query)
    if role not in {"reader", "accountant", "chief"}:
        raise HTTPException(403, "No access to this organization's books")
    return role


async def member(request: Request, session=Depends(transaction, scope="function"), user=Depends(get_current_user)):
    actor = subject(user)
    org_id = int(request.path_params["org_id"])
    role = await organization_role(session, org_id, actor)
    # Middleware identity predates a possible wait on the organization lock.
    # Reuse the same local-status/claim policy against current persisted data.
    from config.access import is_package_allowed

    try:
        if user.keycloak_user_id:
            fresh = await resolve_effective_oidc_user(user, session)
        elif get_settings().auth_mode == "dev":
            fresh = await resolve_effective_dev_user(user, session)
        else:
            fresh = user
    except EffectiveIdentityLookupError as exc:
        raise HTTPException(403, "Current accounting access could not be verified") from exc
    if (subject(fresh) != actor or fresh.local_status not in {None, "active"}
            or fresh.crm_restricted or not is_package_allowed("accounting", fresh.roles)):
        raise HTTPException(403, "Accounting access denied")
    if request.method != "GET" and role == "reader":
        raise HTTPException(403, "Read-only accounting access")
    return session, actor, role


def chief(ctx):
    if ctx[2] != "chief":
        raise HTTPException(403, "Chief accountant access required")


def valid_month(month):
    try:
        parsed = date.fromisoformat(month + "-01")
        if parsed.strftime("%Y-%m") != month:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422, "Month must be YYYY-MM") from exc


@router.get("/organizations")
async def organizations(session=Depends(transaction, scope="function"), user=Depends(get_current_user)):
    actor = subject(user)
    rows = (await session.scalars(select(Organization).join(
        AccessGrant, AccessGrant.organization_id == Organization.id
    ).where(AccessGrant.subject == actor))).all()
    return [serialize(row) for row in rows]


@router.post("/organizations", status_code=201)
async def create_organization(data: OrganizationInput, session=Depends(transaction, scope="function"),
                              user=Depends(get_current_user)):
    actor = subject(user)
    if not set(user.roles) & {"director", "admin", "Админ", "Директор"}:
        raise HTTPException(403, "Organization creation requires director/admin")
    row = Organization(**data.model_dump())
    session.add(row)
    await session.flush()
    session.add(AccessGrant(organization_id=row.id, subject=actor, role="chief"))
    service.audit(session, row.id, actor, "organization_created", {"unp": row.unp})
    return serialize(row)


@router.put("/organizations/{org_id}/members")
async def grant(org_id: int, data: GrantInput, ctx=Depends(member)):
    chief(ctx)
    session, actor, _ = ctx
    await service.lock_organization(session, org_id)
    if data.subject == actor:
        raise HTTPException(422, "Use another chief to change your own membership")
    row = await session.scalar(select(AccessGrant).where(
        AccessGrant.organization_id == org_id, AccessGrant.subject == data.subject,
    ))
    if row is None:
        row = AccessGrant(organization_id=org_id, **data.model_dump())
        session.add(row)
    else:
        row.role = data.role
    service.audit(session, org_id, actor, "membership_changed", data.model_dump())
    await session.flush()
    return serialize(row)


@router.get("/organizations/{org_id}/accounts")
async def accounts(org_id: int, on: date, ctx=Depends(member)):
    return [serialize(row) for row in (await service.accounts_on(ctx[0], org_id, on)).values()]


@router.get("/organizations/{org_id}/seller-profiles")
async def seller_profile_versions(org_id: int, ctx=Depends(member)):
    from modules.accounting.models import SellerProfile
    rows = (await ctx[0].scalars(select(SellerProfile).where(
        SellerProfile.organization_id == org_id,
    ).order_by(SellerProfile.revision.desc()).limit(100))).all()
    return [seller_profiles.result(row) for row in rows]


@router.get("/organizations/{org_id}/seller-profile")
async def seller_profile_on(org_id: int, on: date, currency: str, ctx=Depends(member)):
    return await seller_profiles.current(ctx[0], org_id, on, currency)


@router.post("/organizations/{org_id}/seller-profiles", status_code=201)
async def create_seller_profile(org_id: int, data: SellerProfileInput, ctx=Depends(member)):
    chief(ctx)
    result = await seller_profiles.create(ctx[0], org_id, data, ctx[1])
    return result


async def ensure_future_version(session, org_id, effective):
    await service.lock_organization(session, org_id)
    latest = await session.scalar(select(Entry.posting_date).where(
        Entry.organization_id == org_id
    ).order_by(Entry.posting_date.desc()).limit(1))
    if latest and effective <= latest:
        raise service.AccountingError("New configuration must take effect after posted history")


@router.post("/organizations/{org_id}/accounts", status_code=201)
async def create_account(org_id: int, data: AccountInput, ctx=Depends(member)):
    chief(ctx)
    await ensure_future_version(ctx[0], org_id, data.valid_from)
    row = Account(organization_id=org_id, **data.model_dump())
    ctx[0].add(row)
    service.audit(ctx[0], org_id, ctx[1], "account_version_created", data.model_dump(mode="json"))
    await ctx[0].flush()
    return serialize(row)


@router.get("/organizations/{org_id}/policies")
async def policies(org_id: int, ctx=Depends(member)):
    rows = (await ctx[0].scalars(select(Policy).where(Policy.organization_id == org_id))).all()
    return [serialize(row) for row in rows]


@router.post("/organizations/{org_id}/policies", status_code=201)
async def create_policy(org_id: int, data: PolicyInput, ctx=Depends(member)):
    chief(ctx)
    await ensure_future_version(ctx[0], org_id, data.effective_from)
    if data.financial_closing is not None:
        from modules.accounting.closing_policy import validate_accounts
        await validate_accounts(ctx[0], org_id, data.effective_from, data.financial_closing)
    if data.production_costing is not None:
        from modules.accounting.production_cost_policy import (
            validate_accounts as validate_production_accounts,
        )
        await validate_production_accounts(ctx[0], org_id, data.effective_from, data.production_costing)
    if data.currency_revaluation is not None:
        await fx_revaluation.validate_policy(ctx[0], org_id, data.effective_from, data.currency_revaluation)
    row = Policy(organization_id=org_id, approved_by=ctx[1], **data.model_dump(exclude_none=True))
    ctx[0].add(row)
    service.audit(ctx[0], org_id, ctx[1], "policy_approved", data.model_dump(mode="json"))
    await ctx[0].flush()
    return serialize(row)


@router.get("/organizations/{org_id}/source-bindings")
async def source_bindings(org_id: int, ctx=Depends(member)):
    return [serialize(row) for row in (await ctx[0].scalars(select(SourceBinding).where(
        SourceBinding.organization_id == org_id,
    ).order_by(SourceBinding.id))).all()]


@router.post("/organizations/{org_id}/source-bindings", status_code=201)
async def bind_source(org_id: int, data: SourceBindingInput, ctx=Depends(member)):
    chief(ctx)
    await service.lock_organization(ctx[0], org_id)
    if data.source_type == "logistics_import":
        # ImportShipment has no inferred legal owner. A chief must bind the
        # exact existing logistics source before accounting may use it.
        from modules.logistics.models import ImportShipment

        if await ctx[0].get(ImportShipment, data.source_id) is None:
            raise HTTPException(404, "Logistics import source was not found; no implicit company assignment is allowed")
    if data.source_type == "finance_bank_transaction":
        # Bank polling has no legal-entity default.  A chief must bind the
        # exact imported row before accounting can use it for this company.
        from modules.finance.models import BankTransaction

        if data.ownership != "own":
            raise HTTPException(422, "A bank transaction can only be bound as an own-company source")
        bank_source = await ctx[0].scalar(select(BankTransaction).where(
            BankTransaction.id == data.source_id,
        ).with_for_update().execution_options(populate_existing=True))
        if bank_source is None:
            raise HTTPException(404, "Imported bank transaction was not found; no implicit company assignment is allowed")
    previous = await ctx[0].scalar(select(SourceBinding).where(
        SourceBinding.source_type == data.source_type, SourceBinding.source_id == data.source_id,
    ))
    if previous is not None:
        if previous.organization_id == org_id and previous.ownership == data.ownership and previous.evidence == data.evidence:
            return serialize(previous)
        raise HTTPException(409, "Source ownership has already been recorded; review the existing decision")
    if data.source_type == "finance_bank_transaction":
        closed_periods = select(Period.id).where(
            Period.organization_id == org_id, Period.closed.is_(True),
        )
        if bank_source.occurred_on is not None:
            closed_periods = closed_periods.where(Period.month >= bank_source.occurred_on.strftime("%Y-%m"))
        if await ctx[0].scalar(closed_periods.limit(1)) is not None:
            raise HTTPException(409, "Bank source affects a closed period; review reopening before binding")
    row = SourceBinding(organization_id=org_id, actor=ctx[1], **data.model_dump())
    ctx[0].add(row)
    await ctx[0].flush()
    service.audit(ctx[0], org_id, ctx[1], "source_ownership_recorded", {"binding_id": row.id, **data.model_dump()})
    return serialize(row)


@router.post("/organizations/{org_id}/preview")
async def preview(org_id: int, data: PostingInput, ctx=Depends(member)):
    accounts, policy = await service.preview_posting(ctx[0], org_id, data)
    return {"digest": service.digest(data), "normative_verified": policy.normative_verified,
            "lines": [{**line.model_dump(mode="json"), "title": accounts[line.account].title}
                      for line in data.lines], "explanation": data.explanation}


@router.post("/organizations/{org_id}/entries", status_code=201)
async def create_entry(org_id: int, data: PostingInput, ctx=Depends(member), core=Depends(get_core)):
    if data.correction_of or data.opening:
        chief(ctx)
    return serialize(await service.post(ctx[0], org_id, data, ctx[1], core.services.event_bus))


@router.post("/organizations/{org_id}/bank/preview")
async def bank_preview(org_id: int, data: BankDocument, ctx=Depends(member)):
    posting, accounts, policy = await preview_bank(ctx[0], org_id, data)
    return {"posting": posting.model_dump(mode="json"), "digest": service.digest(posting),
            "normative_verified": policy.normative_verified,
            "lines": [{**line.model_dump(mode="json"), "title": accounts[line.account].title}
                      for line in posting.lines]}


@router.post("/organizations/{org_id}/bank/confirm", status_code=201)
async def bank_confirm(org_id: int, data: BankDocument, ctx=Depends(member), core=Depends(get_core)):
    await service.lock_organization(ctx[0], org_id)
    posting, _, _ = await preview_bank(ctx[0], org_id, data)
    return serialize(await service.post(ctx[0], org_id, posting, ctx[1], core.services.event_bus))


@router.post("/organizations/{org_id}/bank-statement/sources", status_code=201)
async def import_statement_source(org_id: int, data: bank_statement.StatementImportInput, ctx=Depends(member)):
    chief(ctx)
    try:
        row = await bank_statement.ingest(ctx[0], org_id, data.line, evidence=data.evidence, actor=ctx[1])
        snapshot = bank_import.source_snapshot(row)
        return {"organization_id": org_id, "source_transaction_id": row.id,
                "source_snapshot": snapshot, "source_digest": bank_import._digest(snapshot)}
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/organizations/{org_id}/bank-import/preview")
async def bank_import_preview(org_id: int, data: bank_import.BankImportInput, ctx=Depends(member)):
    try:
        return await bank_import.prepare(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/organizations/{org_id}/bank-import/confirm", status_code=201)
async def bank_import_confirm(org_id: int, data: bank_import.BankImportConfirmInput,
                              ctx=Depends(member), core=Depends(get_core)):
    try:
        row = await bank_import.confirm(ctx[0], org_id, data, ctx[1], core.services.event_bus)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize(row)


@router.get("/organizations/{org_id}/bank-import")
async def bank_import_register(org_id: int, ctx=Depends(member)):
    return [serialize(row) for row in await bank_import.list_imports(ctx[0], org_id)]


@router.get("/organizations/{org_id}/bank-import/candidates")
async def bank_import_candidates(org_id: int, ctx=Depends(member)):
    return await bank_import.list_candidates(ctx[0], org_id, include_unbound=ctx[2] == "chief")


@router.post("/organizations/{org_id}/settlement-offsets/preview")
async def settlement_offset_preview(org_id: int, data: SettlementOffsetInput,
                                    ctx=Depends(member), core=Depends(get_core),
                                    user=Depends(get_current_user)):
    try:
        return await settlement_offsets.prepare(ctx[0], org_id, user, data, core.services.accounting)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/organizations/{org_id}/settlement-offsets/confirm", status_code=201)
async def settlement_offset_confirm(org_id: int, data: SettlementOffsetConfirmInput,
                                    ctx=Depends(member), core=Depends(get_core),
                                    user=Depends(get_current_user)):
    try:
        row = await settlement_offsets.confirm(ctx[0], org_id, user, data,
                                               core.services.accounting, ctx[1],
                                               core.services.event_bus)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize(row)


@router.get("/organizations/{org_id}/settlement-offsets")
async def settlement_offset_register(org_id: int, ctx=Depends(member)):
    return [serialize(row) for row in await settlement_offsets.list_offsets(ctx[0], org_id)]


@router.post("/organizations/{org_id}/purchases/preview")
async def purchase_preview(org_id: int, data: PurchaseDocument, ctx=Depends(member)):
    if any(item.order_id is not None for item in data.items):
        raise HTTPException(422, "Order references require a saved procurement receipt")
    posting, accounts, policy = await preview_purchase(ctx[0], org_id, data)
    return {"posting": posting.model_dump(mode="json"), "digest": service.digest(posting),
            "normative_verified": policy.normative_verified, "vat_deducted": False,
            "lines": [{**line.model_dump(mode="json"), "title": accounts[line.account].title}
                      for line in posting.lines]}


@router.post("/organizations/{org_id}/purchases/confirm", status_code=201)
async def purchase_confirm(org_id: int, data: PurchaseDocument, ctx=Depends(member), core=Depends(get_core)):
    if any(item.order_id is not None for item in data.items):
        raise HTTPException(422, "Order references require a saved procurement receipt")
    await service.lock_organization(ctx[0], org_id)
    posting, _, _ = await preview_purchase(ctx[0], org_id, data)
    return serialize(await service.post(ctx[0], org_id, posting, ctx[1], core.services.event_bus))


@router.get("/organizations/{org_id}/entries")
async def entries(org_id: int, start: date, end: date, ctx=Depends(member)):
    rows = (await ctx[0].scalars(select(Entry).where(
        Entry.organization_id == org_id, Entry.posting_date >= start, Entry.posting_date <= end
    ).order_by(Entry.posting_date, Entry.id))).all()
    return [serialize(row) for row in rows]


@router.get("/organizations/{org_id}/entries/{entry_id}")
async def entry_detail(org_id: int, entry_id: int, ctx=Depends(member)):
    row = await ctx[0].scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.id == entry_id,
    ))
    if row is None:
        raise HTTPException(404, "Entry not found")
    lines = (await ctx[0].scalars(select(Line).where(Line.entry_id == row.id))).all()
    # Explicit decimal string serialization is applied at the HTTP boundary below.
    return {**serialize(row), "lines": [serialize(line) for line in lines]}


@router.get("/organizations/{org_id}/entries/{entry_id}/shipment-package")
async def shipment_package(org_id: int, entry_id: int, response: Response, ctx=Depends(member)):
    from modules.accounting.models import ShipmentAccountingReceipt
    from modules.accounting.shipment_commands import verify_saved

    entry = await ctx[0].scalar(select(Entry).where(Entry.organization_id == org_id, Entry.id == entry_id))
    if entry is None:
        raise HTTPException(404, "Shipment package not found")
    source = entry.source.partition(":part:")[0]
    receipt = await ctx[0].scalar(select(ShipmentAccountingReceipt).where(
        ShipmentAccountingReceipt.organization_id == org_id, ShipmentAccountingReceipt.source == source,
    ))
    if receipt is None:
        raise HTTPException(404, "Shipment package not found")
    try:
        await verify_saved(ctx[0], receipt)
        if entry_id not in {page["entry_id"] for page in receipt.snapshot["pages"]}:
            raise HTTPException(404, "Shipment package not found")
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "Stored shipment package could not be verified") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**serialize(receipt), "status": "recorded", "confirmation_available": False,
            "statutory_certified": False, "vat_treatment_verified": False}


@router.get("/organizations/{org_id}/reports")
async def get_report(org_id: int, start: date, end: date, ctx=Depends(member)):
    return await reports.report(ctx[0], org_id, start, end)


@router.post("/organizations/{org_id}/reconciliation")
async def compare_reports(org_id: int, data: ReconciliationInput, ctx=Depends(member)):
    try:
        return await run_in_threadpool(reconciliation.compare_uploads, org_id, data.left_base64, data.right_base64)
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/organizations/{org_id}/reconciliation/receipts")
async def reconciliation_receipts(org_id: int, ctx=Depends(member)):
    return {"organization_id": org_id, "rows": await reconciliation.list_receipts(ctx[0], org_id)}


@router.post("/organizations/{org_id}/reconciliation/confirm")
async def confirm_reconciliation(org_id: int, data: ReconciliationConfirmInput, ctx=Depends(member)):
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Only an accountant may accept an OSV reconciliation")
    try:
        return await reconciliation.confirm_uploads(
            ctx[0], org_id, data.left_base64, data.right_base64,
            data.request_key, data.evidence, ctx[1],
        )
    except (ValueError, csv.Error, service.AccountingError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/organizations/{org_id}/additional-expenses/{expense_id}/preview")
async def additional_expense_preview(org_id: int, expense_id: int, data: LateCostPreviewInput,
                                     response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.late_cost_preview import preview
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    try:
        result = await preview(ctx[0], org_id, expense_id, data, gateway)
    except (ValueError, service.AccountingError) as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/additional-expenses/{expense_id}/posting-preview")
async def additional_expense_posting_preview(org_id: int, expense_id: int, data: LateCostCommand,
        response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.late_cost_commands import prepare

    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    calculated, posting = await prepare(ctx[0], org_id, expense_id, data, gateway)
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "expense_id": expense_id, "principal": ctx[1],
            "calculation": calculated, "posting": posting.model_dump(mode="json"),
            "digest": service.digest(posting), "basis_digest": calculated["basis_digest"], "posted": False}


@router.get("/organizations/{org_id}/additional-expenses/{expense_id}/posting")
async def additional_expense_posting(org_id: int, expense_id: int, response: Response,
                                     ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.late_cost_receipts import verify_receipt
    from modules.accounting.models import LateCostReceipt

    saved = await ctx[0].scalar(select(LateCostReceipt).where(LateCostReceipt.organization_id == org_id,
        LateCostReceipt.expense_id == expense_id))
    if saved is None:
        raise HTTPException(404, "Additional expense has no posting")
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    posting = await verify_receipt(ctx[0], org_id, saved.entry_id, gateway)
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "expense_id": expense_id, "source_version": saved.source_version,
            "entry_id": saved.entry_id, "request_key": saved.request_key, "digest": saved.digest,
            "basis_digest": saved.calculation["basis_digest"], "posted": True,
            "posting": posting.model_dump(mode="json"), "calculation": saved.calculation}


@router.post("/organizations/{org_id}/additional-expenses/{expense_id}/confirm", status_code=201)
async def additional_expense_confirm(org_id: int, expense_id: int, data: LateCostConfirmation,
        response: Response, expected_principal: str = Header(alias="X-Expected-Principal"),
        ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.late_cost_commands import confirm

    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the command again")
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    command = LateCostCommand(allocation=data.allocation, accounts=data.accounts)
    try:
        saved = await confirm(ctx[0], org_id, expense_id, command, data.request_key,
            data.expected_basis_digest, data.expected_digest, ctx[1], gateway, core.services.event_bus)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "expense_id": expense_id, "source_version": saved.source_version,
            "entry_id": saved.entry_id, "request_key": saved.request_key, "digest": saved.digest,
            "basis_digest": saved.calculation["basis_digest"], "posted": True}


@router.get("/organizations/{org_id}/receipts/{receipt_id}/source")
async def accounting_receipt_source(org_id: int, receipt_id: int, response: Response,
                                    ctx=Depends(member), core=Depends(get_core)):
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    try:
        result = await gateway.receipt_source(ctx[0], org_id, receipt_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Receipt source not found in this organization")
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.get("/organizations/{org_id}/receipts/{receipt_id}/warehouse-reconciliation")
async def receipt_warehouse_reconciliation(org_id: int, receipt_id: int, response: Response,
                                           ctx=Depends(member), core=Depends(get_core)):
    source_gateway = getattr(core.services, "procurement_source", None)
    warehouse = getattr(core.services, "wms_reservations", None)
    if source_gateway is None or warehouse is None:
        raise HTTPException(503, "Receipt reconciliation services unavailable")
    try:
        source = await source_gateway.receipt_source(ctx[0], org_id, receipt_id)
        if source is None:
            raise HTTPException(404, "Receipt source not found in this organization")
        result = await warehouse.receipt_reconciliation(ctx[0], org_id, source)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/receipts/{receipt_id}/preview")
async def accounting_receipt_preview(org_id: int, receipt_id: int, data: ReceiptAccountingOptions,
                                     ctx=Depends(member), core=Depends(get_core), user=Depends(get_current_user)):
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    # Same organization-before-source lock order as the procurement command.
    await core.services.accounting.source_member(ctx[0], org_id, user)
    document = await gateway.prepare_receipt(ctx[0], org_id, receipt_id, data)
    result = await core.services.accounting.receipt_posting(ctx[0], org_id, user, document, confirm_digest=None)
    return {**result, "organization_id": org_id, "source": document["source"],
            "source_version": document["source_version"], "posted": False}


@router.post("/organizations/{org_id}/receipts/{receipt_id}/confirm", status_code=201)
async def accounting_receipt_confirm(org_id: int, receipt_id: int, data: ReceiptAccountingConfirmation,
                                     ctx=Depends(member), core=Depends(get_core), user=Depends(get_current_user)):
    gateway = getattr(core.services, "procurement_source", None)
    if gateway is None:
        raise HTTPException(503, "Procurement source service is unavailable")
    result = await gateway.confirm_receipt(ctx[0], org_id, receipt_id, data, user,
                                           core.services.accounting, core.services.event_bus)
    return {**result, "organization_id": org_id, "source": f"procurement:receipt:{receipt_id}",
            "source_version": data.expected_version}


async def verified_shipment_source(session, org_id, key, core):
    gateway = getattr(core.services, "wms_reservations", None)
    if gateway is None or not callable(getattr(gateway, "accounting_shipment_source", None)):
        raise HTTPException(503, "Shipment source service unavailable")
    try:
        result = await gateway.accounting_shipment_source(session, org_id, str(key), core.services.sales_source)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Physical shipment not found")
    return result


@router.get("/organizations/{org_id}/shipments/{key}/source")
async def accounting_shipment_source(org_id: int, key: UUID, response: Response, ctx=Depends(member), core=Depends(get_core)):
    result = await verified_shipment_source(ctx[0], org_id, key, core)
    response.headers["Cache-Control"] = "private, no-store"
    return result["receipt"]


@router.get("/organizations/{org_id}/shipments/{key}/document", response_class=HTMLResponse)
async def accounting_shipment_document(org_id: int, key: UUID, ctx=Depends(member), core=Depends(get_core)):
    result = await verified_shipment_source(ctx[0], org_id, key, core)
    return HTMLResponse(result["document_html"], headers={"Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})


@router.get("/organizations/{org_id}/shipments/{key}/tn-ttn-draft")
async def accounting_shipment_tn_ttn_draft(
    org_id: int, key: UUID, response: Response, kind: str | None = Query(default=None),
    ctx=Depends(member), core=Depends(get_core),
):
    """Prepare a source-bound TN/TTN form without issuing a statutory document."""
    if kind not in {None, "tn", "ttn"}:
        raise HTTPException(422, "kind must be tn or ttn")
    result = await verified_shipment_source(ctx[0], org_id, key, core)
    try:
        draft = build_shipment_document_draft(result["receipt"], kind)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return draft


@router.post("/organizations/{org_id}/shipments/{key}/preview")
async def accounting_shipment_preview(org_id: int, key: UUID, data: ShipmentPlanInput, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.shipment_preview import prepare

    result = await verified_shipment_source(ctx[0], org_id, key, core)
    return await prepare(ctx[0], org_id, result["receipt"], data, procurement=getattr(core.services, "procurement_source", None))


@router.post("/organizations/{org_id}/shipments/{key}/confirm", status_code=201)
async def accounting_shipment_confirm(org_id: int, key: UUID, data: ShipmentConfirmInput,
                                      response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.shipment_commands import confirm

    result = await verified_shipment_source(ctx[0], org_id, key, core)
    document = ShipmentPlanInput(**data.model_dump(exclude={"expected_basis_digest"}))
    try:
        saved = await confirm(ctx[0], org_id, result["receipt"], document,
                              data.expected_basis_digest, ctx[1], core.services.event_bus,
                              procurement=getattr(core.services, "procurement_source", None))
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    # member's function-scoped transaction commits before this response is sent.
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "source": saved.source, "receipt_id": saved.id,
            "basis_digest": saved.basis_digest, "anchor_entry_id": saved.anchor_entry_id,
            "entry_ids": [page["entry_id"] for page in saved.snapshot["pages"]],
            "posted": True, "statutory_certified": False}


@router.get("/organizations/{org_id}/shipments/{key}/draft")
async def shipment_draft(org_id: int, key: UUID, response: Response, ctx=Depends(member)):
    row = await shipment_drafts.latest(ctx[0], org_id, f"wms:physical-shipment:{org_id}:{key}")
    response.headers["Cache-Control"] = "private, no-store"
    return {"revision": row.revision if row else 0, "draft": serialize(row) if row else None}


@router.post("/organizations/{org_id}/shipments/{key}/draft")
async def save_shipment_draft(org_id: int, key: UUID, data: shipment_drafts.DraftInput, ctx=Depends(member)):
    row = await shipment_drafts.save(ctx[0], org_id, f"wms:physical-shipment:{org_id}:{key}", data, ctx[1])
    return {"revision": row.revision, "draft": serialize(row)}


@router.get("/organizations/{org_id}/inventory/lots")
async def inventory_lots(org_id: int, response: Response, data: InventoryLotQuery = Depends(), ctx=Depends(member), core=Depends(get_core)):
    response.headers["Cache-Control"] = "private, no-store"
    return await inventory_cost.available_lots(ctx[0], org_id, data, procurement=getattr(core.services, "procurement_source", None))


@router.post("/organizations/{org_id}/inventory/issues/preview")
async def preview_inventory_issue(org_id: int, data: InventoryIssuePreviewInput, ctx=Depends(member), core=Depends(get_core)):
    return await inventory_cost.preview_issue(ctx[0], org_id, data, procurement=getattr(core.services, "procurement_source", None))


@router.post("/organizations/{org_id}/sales/posting-preview")
async def preview_sale_posting(org_id: int, data: sales.SaleDocument, ctx=Depends(member), core=Depends(get_core)):
    return await sales.prepare(ctx[0], org_id, data, procurement=getattr(core.services, "procurement_source", None))


@router.post("/organizations/{org_id}/sales/confirm", status_code=201)
async def confirm_sale_posting(org_id: int, data: sales.SaleConfirm, ctx=Depends(member), core=Depends(get_core)):
    document = sales.SaleDocument(**data.model_dump(exclude={"basis_digest", "digest"}))
    row = await sales.confirm(ctx[0], org_id, document, data.basis_digest, data.digest, ctx[1], core.services.event_bus,
                              procurement=getattr(core.services, "procurement_source", None))
    return serialize(row)


@router.post("/organizations/{org_id}/inventory/issues/posting-preview")
async def preview_issue_posting(org_id: int, data: InventoryIssueDocument, ctx=Depends(member), core=Depends(get_core)):
    cost, posting = await inventory_issues.prepare(ctx[0], org_id, data, procurement=getattr(core.services, "procurement_source", None))
    return {"cost": cost, "digest": service.digest(posting), "posting": posting.model_dump(mode="json")}


@router.post("/organizations/{org_id}/inventory/issues/confirm", status_code=201)
async def confirm_issue_posting(org_id: int, data: InventoryIssueConfirm, ctx=Depends(member), core=Depends(get_core)):
    document = InventoryIssueDocument(**data.model_dump(exclude={"basis_digest", "digest"}))
    row = await inventory_issues.confirm(ctx[0], org_id, document, data.basis_digest, data.digest, ctx[1], core.services.event_bus,
                                        procurement=getattr(core.services, "procurement_source", None))
    return serialize(row)


@router.get("/organizations/{org_id}/periods")
async def periods(org_id: int, ctx=Depends(member)):
    rows = (await ctx[0].scalars(select(Period).where(
        Period.organization_id == org_id
    ).order_by(Period.month))).all()
    return [serialize(row) for row in rows]


@router.post("/organizations/{org_id}/periods/{month}/close")
async def close(org_id: int, month: str, data: CloseInput, ctx=Depends(member)):
    chief(ctx)
    valid_month(month)
    return serialize(await service.close_period(ctx[0], org_id, month, data, ctx[1]))


@router.get("/organizations/{org_id}/periods/{month}/financial-closing-preview")
async def financial_closing_preview(org_id: int, month: str, ctx=Depends(member)):
    from modules.accounting.financial_closing import preview

    chief(ctx)
    valid_month(month)
    result = await preview(ctx[0], org_id, month)
    return {**result, "confirmation_available": result["normative_verified"] is True}


@router.post("/organizations/{org_id}/periods/{month}/fx-revaluation-preview")
async def fx_revaluation_preview(org_id: int, month: str, data: FxRevaluationInput,
                                 response: Response, ctx=Depends(member)):
    valid_month(month)
    result = await fx_revaluation.preview(ctx[0], org_id, month, data)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/periods/{month}/fx-revaluation-confirm", status_code=201)
async def fx_revaluation_confirm(org_id: int, month: str, data: FxRevaluationConfirmInput,
                                 response: Response, ctx=Depends(member), core=Depends(get_core)):
    chief(ctx)
    valid_month(month)
    receipt = await fx_revaluation.confirm(ctx[0], org_id, month, data, ctx[1], core.services.event_bus)
    response.headers["Cache-Control"] = "private, no-store"
    return fx_revaluation.serialize(receipt)


@router.get("/organizations/{org_id}/periods/{month}/fx-revaluation/{request_key}")
async def fx_revaluation_status(org_id: int, month: str, request_key: str,
                                response: Response, ctx=Depends(member)):
    valid_month(month)
    row = await ctx[0].scalar(select(fx_revaluation.FxRevaluationReceipt).where(
        fx_revaluation.FxRevaluationReceipt.organization_id == org_id,
        fx_revaluation.FxRevaluationReceipt.month == month,
        fx_revaluation.FxRevaluationReceipt.request_key == request_key,
    ))
    if row is None:
        raise HTTPException(404, "FX revaluation package not found")
    response.headers["Cache-Control"] = "private, no-store"
    return fx_revaluation.serialize(row)


@router.get('/organizations/{org_id}/periods/{month}/production-cost-sources')
async def production_cost_sources(org_id: int, month: str, policy_id: int, response: Response, ctx=Depends(member)):
    from modules.accounting.production_cost_sources import cost_sources

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    return await cost_sources(ctx[0], org_id, month, policy_id)


@router.post('/organizations/{org_id}/periods/{month}/production-cost-review')
async def production_cost_review(org_id: int, month: str, data: ProductionCostReviewInput, response: Response,
                                 ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_cost_review import review_costs

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    return await review_costs(ctx[0], org_id, month, data, core.services.production_output)


@router.get('/organizations/{org_id}/periods/{month}/production-output-cost-preview')
async def production_output_cost_preview(org_id: int, month: str, policy_id: int, order_id: int,
        order_analytics: str, warehouse: str, response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_output_cost import preview_output_cost_basis

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        result = await preview_output_cost_basis(
            ctx[0], org_id, month, policy_id, order_id, order_analytics, warehouse,
            getattr(core.services, 'production_output', None),
            getattr(core.services, 'wms_reservations', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return result


@router.post('/organizations/{org_id}/periods/{month}/production-output-transfer-preview')
async def production_output_transfer_preview(org_id: int, month: str, data: ProductionOutputTransferInput,
        response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_output_transfer import prepare_output_transfer

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return await prepare_output_transfer(
            ctx[0], org_id, month, data,
            getattr(core.services, 'production_output', None),
            getattr(core.services, 'wms_reservations', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/organizations/{org_id}/periods/{month}/production-output-transfer-confirm', status_code=201)
async def production_output_transfer_confirm(org_id: int, month: str,
        data: ProductionOutputTransferConfirmInput, response: Response,
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if ctx[2] not in {'accountant', 'chief'}:
        raise HTTPException(403, 'Accounting write access required')
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.production_output_transfer import confirm_output_transfer

    try:
        entry = await confirm_output_transfer(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
            production=getattr(core.services, 'production_output', None),
            warehouse_gateway=getattr(core.services, 'wms_reservations', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'organization_id': org_id, 'order_id': data.order_id, 'basis_digest': data.basis_digest,
            'digest': data.digest, 'entry': serialize(entry), 'entry_id': entry.id,
            'posted': True, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/periods/{month}/production-output-transfer-status/{order_id}')
async def production_output_transfer_status(org_id: int, month: str, order_id: int,
        response: Response, ctx=Depends(member)):
    from modules.accounting.models import ProductionOutputTransferReceipt

    valid_month(month)
    receipt = await ctx[0].scalar(select(ProductionOutputTransferReceipt).where(
        ProductionOutputTransferReceipt.organization_id == org_id,
        ProductionOutputTransferReceipt.order_id == order_id,
        ProductionOutputTransferReceipt.month == month,
    ))
    if receipt is None:
        raise HTTPException(404, 'Production output transfer outcome not found')
    entry = await ctx[0].get(Entry, receipt.entry_id)
    if entry is None or entry.organization_id != org_id or entry.source != f'production:output-transfer:{org_id}:{order_id}' \
            or entry.operation != 'production_output_transfer' or entry.digest != receipt.digest:
        raise HTTPException(409, 'Production output transfer receipt is inconsistent')
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'month': month, 'actor': receipt.actor, 'order_id': order_id,
            'basis_digest': receipt.basis_digest, 'digest': receipt.digest, 'entry_id': entry.id,
            'entry': serialize(entry), 'posted': True, 'final_cost_certified': False}


@router.post('/organizations/{org_id}/periods/{month}/production-labor-import-preview')
async def production_labor_import_preview(org_id: int, month: str, data: ProductionLaborInput,
        response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_labor_cost import prepare_labor_import

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return await prepare_labor_import(
            ctx[0], org_id, month, data,
            getattr(core.services, 'production_output', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/organizations/{org_id}/periods/{month}/production-labor-import-confirm', status_code=201)
async def production_labor_import_confirm(org_id: int, month: str, data: ProductionLaborConfirmInput,
        response: Response, expected_principal: str = Header(alias='X-Expected-Principal'),
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    if ctx[2] not in {'accountant', 'chief'}:
        raise HTTPException(403, 'Accounting write access required')
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.production_labor_cost import confirm_labor_import

    try:
        entry = await confirm_labor_import(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
            production=getattr(core.services, 'production_output', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'organization_id': org_id, 'month': month, 'request_key': str(data.request_key),
            'source_digest': data.source_digest, 'digest': data.digest, 'entry': serialize(entry),
            'entry_id': entry.id, 'posted': True, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/production-labor-import-status/{request_key}')
async def production_labor_import_status(org_id: int, request_key: UUID,
        response: Response, ctx=Depends(member)):
    from modules.accounting.production_labor_cost import labor_import_result

    receipt = await labor_import_result(ctx[0], org_id, request_key)
    if receipt is None:
        raise HTTPException(404, 'Production labor import outcome not found')
    entry = await ctx[0].get(Entry, receipt.entry_id)
    if (entry is None or entry.organization_id != org_id
            or entry.operation != 'production_labor_import'
            or entry.digest != receipt.digest
            or entry.source != f'production:labor:{org_id}:{receipt.source_document}'
            or entry.source_version != 1):
        raise HTTPException(409, 'Production labor import receipt is inconsistent')
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'month': receipt.month, 'actor': receipt.actor,
            'request_key': receipt.request_key, 'source_document': receipt.source_document,
            'source_version': receipt.source_version, 'source_digest': receipt.source_digest,
            'digest': receipt.digest, 'entry_id': entry.id, 'entry': serialize(entry),
            'source': receipt.source, 'posting': receipt.posting, 'posted': True,
            'final_cost_certified': False}


@router.post('/organizations/{org_id}/periods/{month}/payroll-accrual-import-preview')
async def payroll_accrual_import_preview(org_id: int, month: str, data: PayrollAccrualInput,
        response: Response, ctx=Depends(member)):
    from modules.accounting.payroll_import import prepare_payroll_accrual

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return await prepare_payroll_accrual(ctx[0], org_id, month, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/organizations/{org_id}/payroll-accrual-access')
async def payroll_accrual_access(org_id: int, response: Response, ctx=Depends(member)):
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'principal': ctx[1], 'can_confirm': ctx[2] in {'accountant', 'chief'}}


@router.post('/organizations/{org_id}/periods/{month}/payroll-statutory-import-preview')
async def payroll_statutory_import_preview(org_id: int, month: str, data: PayrollStatutoryInput,
        response: Response, ctx=Depends(member)):
    from modules.accounting.payroll_statutory import prepare_payroll_statutory

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return await prepare_payroll_statutory(ctx[0], org_id, month, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/organizations/{org_id}/payroll-statutory-access')
async def payroll_statutory_access(org_id: int, response: Response, ctx=Depends(member)):
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'principal': ctx[1], 'can_confirm': ctx[2] in {'accountant', 'chief'}}


@router.post('/organizations/{org_id}/periods/{month}/payroll-statutory-import-confirm', status_code=201)
async def payroll_statutory_import_confirm(org_id: int, month: str, data: PayrollStatutoryConfirmInput,
        response: Response, expected_principal: str = Header(alias='X-Expected-Principal'),
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    if ctx[2] not in {'accountant', 'chief'}:
        raise HTTPException(403, 'Accounting write access required')
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.payroll_statutory import confirm_payroll_statutory

    try:
        entry = await confirm_payroll_statutory(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'organization_id': org_id, 'month': month, 'request_key': str(data.request_key),
            'source_digest': data.source_digest, 'digest': data.digest, 'entry': serialize(entry),
            'entry_id': entry.id, 'posted': True, 'statutory_payroll_certified': False,
            'deductions_and_contributions_available': True}


@router.get('/organizations/{org_id}/payroll-statutory-import-status/{request_key}')
async def payroll_statutory_import_status(org_id: int, request_key: UUID,
        response: Response, ctx=Depends(member)):
    from modules.accounting.payroll_statutory import payroll_statutory_result

    receipt = await payroll_statutory_result(ctx[0], org_id, request_key)
    if receipt is None:
        raise HTTPException(404, 'Payroll statutory import outcome not found')
    entry = await ctx[0].get(Entry, receipt.entry_id)
    if (entry is None or entry.organization_id != org_id
            or entry.operation != 'payroll_statutory_import'
            or entry.digest != receipt.digest
            or entry.source != f'payroll:statutory:{org_id}:{receipt.source_document}'
            or entry.source_version != receipt.source_version):
        raise HTTPException(409, 'Payroll statutory receipt is inconsistent')
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'month': receipt.month, 'actor': receipt.actor,
            'request_key': receipt.request_key, 'source_document': receipt.source_document,
            'source_version': receipt.source_version, 'source_digest': receipt.source_digest,
            'digest': receipt.digest, 'entry_id': entry.id, 'entry': serialize(entry),
            'source': receipt.source, 'posting': receipt.posting, 'posted': True,
            'statutory_payroll_certified': False, 'deductions_and_contributions_available': True}


@router.post('/organizations/{org_id}/periods/{month}/payroll-accrual-import-confirm', status_code=201)
async def payroll_accrual_import_confirm(org_id: int, month: str, data: PayrollAccrualConfirmInput,
        response: Response, expected_principal: str = Header(alias='X-Expected-Principal'),
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    if ctx[2] not in {'accountant', 'chief'}:
        raise HTTPException(403, 'Accounting write access required')
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.payroll_import import confirm_payroll_accrual

    try:
        entry = await confirm_payroll_accrual(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'organization_id': org_id, 'month': month, 'request_key': str(data.request_key),
            'source_digest': data.source_digest, 'digest': data.digest, 'entry': serialize(entry),
            'entry_id': entry.id, 'posted': True, 'statutory_payroll_certified': False,
            'deductions_and_contributions_available': False}


@router.get('/organizations/{org_id}/payroll-accrual-import-status/{request_key}')
async def payroll_accrual_import_status(org_id: int, request_key: UUID,
        response: Response, ctx=Depends(member)):
    from modules.accounting.payroll_import import payroll_accrual_result

    receipt = await payroll_accrual_result(ctx[0], org_id, request_key)
    if receipt is None:
        raise HTTPException(404, 'Payroll accrual import outcome not found')
    entry = await ctx[0].get(Entry, receipt.entry_id)
    if (entry is None or entry.organization_id != org_id
            or entry.operation != 'payroll_accrual_import'
            or entry.digest != receipt.digest
            or entry.source != f'payroll:accrual:{org_id}:{receipt.source_document}'
            or entry.source_version != receipt.source_version):
        raise HTTPException(409, 'Payroll accrual receipt is inconsistent')
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'month': receipt.month, 'actor': receipt.actor,
            'request_key': receipt.request_key, 'source_document': receipt.source_document,
            'source_version': receipt.source_version, 'source_digest': receipt.source_digest,
            'digest': receipt.digest, 'entry_id': entry.id, 'entry': serialize(entry),
            'source': receipt.source, 'posting': receipt.posting, 'posted': True,
            'statutory_payroll_certified': False, 'deductions_and_contributions_available': False}


@router.post('/organizations/{org_id}/periods/{month}/production-material-issue-preview')
async def production_material_issue_preview(org_id: int, month: str,
        data: ProductionMaterialIssuePreviewInput, response: Response,
        ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_material_cost import preview_material_issue

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return await preview_material_issue(
            ctx[0], org_id, month, data,
            getattr(core.services, 'production_output', None),
            procurement=getattr(core.services, 'procurement_source', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/organizations/{org_id}/periods/{month}/production-material-issue-posting-preview')
async def production_material_issue_posting_preview(org_id: int, month: str,
        data: ProductionMaterialIssuePostingInput, response: Response,
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.production_material_cost import prepare_material_issue_posting

    try:
        return await prepare_material_issue_posting(
            ctx[0], org_id, month, data,
            getattr(core.services, 'production_output', None),
            procurement=getattr(core.services, 'procurement_source', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/organizations/{org_id}/periods/{month}/production-material-issue-confirm', status_code=201)
async def production_material_issue_posting_confirm(org_id: int, month: str,
        data: ProductionMaterialIssuePostingConfirmInput, response: Response,
        ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if ctx[2] not in {'accountant', 'chief'}:
        raise HTTPException(403, 'Accounting write access required')
    response.headers['Cache-Control'] = 'private, no-store'
    from modules.accounting.production_material_cost import confirm_material_issue_posting

    try:
        entry = await confirm_material_issue_posting(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
            procurement=getattr(core.services, 'procurement_source', None),
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'organization_id': org_id, 'entry': serialize(entry), 'posted': True,
            'final_cost_certified': False}


@router.get('/organizations/{org_id}/periods/{month}/production-material-issue-posting-status/{movement_id}')
async def production_material_issue_posting_status(org_id: int, month: str, movement_id: int,
        response: Response, ctx=Depends(member)):
    """Independent receipt used to recover a material posting after a lost response."""
    from modules.accounting.schemas import InventoryIssueDocument
    from modules.wms.production_material_issues import ProductionMaterialIssue

    valid_month(month)
    binding = await ctx[0].scalar(select(ProductionMaterialIssue).where(
        ProductionMaterialIssue.organization_id == org_id,
        ProductionMaterialIssue.movement_id == movement_id,
    ))
    if binding is None:
        raise HTTPException(404, 'Production material source binding not found')
    source = f'production:material:{org_id}:{binding.request_key}'
    entry = await ctx[0].scalar(select(Entry).where(
        Entry.organization_id == org_id, Entry.source == source,
        Entry.source_version == 1, Entry.operation == 'inventory_issue',
    ))
    if entry is None:
        raise HTTPException(404, 'Production material posting outcome not found')
    receipt = await ctx[0].scalar(select(InventoryIssueReceipt).where(
        InventoryIssueReceipt.organization_id == org_id, InventoryIssueReceipt.entry_id == entry.id,
    ))
    if receipt is None:
        raise HTTPException(409, 'Production material posting has no immutable receipt')
    try:
        document = InventoryIssueDocument.model_validate(receipt.command)
    except ValueError as exc:
        raise HTTPException(409, 'Production material posting receipt is invalid') from exc
    basis_digest = receipt.cost.get('basis_digest') if isinstance(receipt.cost, dict) else None
    if (document.source != source or document.posting_date.strftime('%Y-%m') != month
            or entry.digest != receipt.digest or receipt.digest != entry.digest
            or not isinstance(basis_digest, str) or len(basis_digest) != 64
            or not isinstance(receipt.posting, dict)):
        raise HTTPException(409, 'Production material posting receipt is inconsistent')
    response.headers['Cache-Control'] = 'private, no-store'
    return {
        'organization_id': org_id, 'month': month, 'actor': receipt.actor,
        'order_id': binding.order_id, 'wms_movement_id': binding.movement_id,
        'policy_id': document.policy_id, 'basis_digest': basis_digest, 'digest': receipt.digest,
        'entry_id': entry.id, 'entry': serialize(entry), 'posting': receipt.posting,
        'posted': True, 'final_cost_certified': False,
    }


@router.get('/organizations/{org_id}/production-overhead-access')
async def production_overhead_access(org_id: int, response: Response, ctx=Depends(member)):
    response.headers['Cache-Control'] = 'private, no-store'
    return {'organization_id': org_id, 'principal': ctx[1], 'can_confirm': ctx[2] in {'accountant', 'chief'}}


@router.get('/organizations/{org_id}/periods/{month}/production-overhead-correction-sources')
async def production_overhead_correction_sources(org_id: int, month: str, original_entry_id: int, policy_id: int,
        response: Response, ctx=Depends(member)):
    from modules.accounting.production_cost_sources import cost_sources

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    return await cost_sources(ctx[0], org_id, month, policy_id, correction_of=original_entry_id)


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-correction-review')
async def production_overhead_correction_review(org_id: int, month: str, original_entry_id: int,
        data: ProductionCostReviewInput, response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_cost_review import review_costs

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    return await review_costs(ctx[0], org_id, month, data, core.services.production_output, correction_of=original_entry_id)


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-correction-preview')
async def production_overhead_correction_preview(org_id: int, month: str, data: ProductionOverheadCorrectionPreview,
        response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_cost_correction import preview_correction

    valid_month(month)
    response.headers['Cache-Control'] = 'private, no-store'
    return await preview_correction(ctx[0], org_id, month, data, core.services.production_output)


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-correction-confirm', status_code=201)
async def production_overhead_correction_confirm(org_id: int, month: str, data: ProductionOverheadCorrectionConfirm,
        response: Response, expected_principal: str = Header(alias='X-Expected-Principal'), ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_cost_correction import confirm_correction

    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    production = getattr(core.services, 'production_output', None)
    if production is None:
        raise HTTPException(503, 'Production order verification service is unavailable')
    try:
        saved = await confirm_correction(ctx[0], org_id, month, data, ctx[1], production)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'confirmed': True, 'posted': saved.entry_id is not None, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/production-overhead-corrections/{request_key}')
async def production_overhead_correction_readback(org_id: int, request_key: UUID, response: Response, ctx=Depends(member)):
    from modules.accounting.production_cost_correction import correction_result

    saved = await correction_result(ctx[0], org_id, request_key)
    if saved is None:
        raise HTTPException(404, 'Production correction confirmation not found')
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'confirmed': True, 'posted': saved.entry_id is not None, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/production-overhead-correction-requests/{request_key}')
async def production_correction_request_status(org_id: int, request_key: UUID, response: Response, ctx=Depends(member)):
    from modules.accounting.production_cost_correction import correction_request_result

    status, saved = await correction_request_result(ctx[0], org_id, request_key)
    if saved is None:
        raise HTTPException(404, 'Correction request outcome not found')
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'confirmed': status == 'confirmed', 'withdrawn': status == 'withdrawn',
        'posted': status == 'confirmed' and saved.entry_id is not None, 'final_cost_certified': False}


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-correction-withdraw')
async def production_correction_withdraw(org_id: int, month: str, data: ProductionOverheadCorrectionWithdraw,
        response: Response, expected_principal: str = Header(alias='X-Expected-Principal'), ctx=Depends(member)):
    from modules.accounting.production_cost_correction import withdraw_correction

    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    try:
        status, saved = await withdraw_correction(ctx[0], org_id, month, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'confirmed': status == 'confirmed', 'withdrawn': status == 'withdrawn',
        'posted': status == 'confirmed' and saved.entry_id is not None, 'final_cost_certified': False}


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-confirm', status_code=201)
async def production_overhead_confirm(org_id: int, month: str, data: ProductionOverheadConfirm, response: Response,
        expected_principal: str = Header(alias='X-Expected-Principal'), ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.production_cost_posting import confirm_overhead

    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    production = getattr(core.services, 'production_output', None)
    if production is None:
        raise HTTPException(503, 'Production order verification service is unavailable')
    try:
        saved = await confirm_overhead(ctx[0], org_id, month, data, ctx[1], production)
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'posted': True, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/production-overhead-confirmations/{request_key}')
async def production_overhead_readback(org_id: int, request_key: UUID, response: Response, ctx=Depends(member)):
    from modules.accounting.models import ProductionOverheadReceipt

    saved = await ctx[0].scalar(select(ProductionOverheadReceipt).where(
        ProductionOverheadReceipt.organization_id == org_id, ProductionOverheadReceipt.request_key == str(request_key)))
    if saved is None:
        raise HTTPException(404, 'Production overhead confirmation not found')
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(saved), 'posted': True, 'final_cost_certified': False}


@router.get('/organizations/{org_id}/production-overhead-requests/{request_key}')
async def production_overhead_request_status(org_id: int, request_key: UUID, response: Response, ctx=Depends(member)):
    from modules.accounting.production_cost_posting import request_result

    status, row = await request_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, 'Production overhead request outcome not found')
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(row), 'posted': status == 'posted', 'withdrawn': status == 'withdrawn', 'final_cost_certified': False}


@router.post('/organizations/{org_id}/periods/{month}/production-overhead-withdraw')
async def production_overhead_withdraw(org_id: int, month: str, data: ProductionOverheadWithdraw, response: Response,
        expected_principal: str = Header(alias='X-Expected-Principal'), ctx=Depends(member)):
    from modules.accounting.production_cost_posting import withdraw_overhead

    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, 'Accounting principal changed; review the command again')
    try:
        status, row = await withdraw_overhead(ctx[0], org_id, month, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers['Cache-Control'] = 'private, no-store'
    return {**serialize(row), 'posted': status == 'posted', 'withdrawn': status == 'withdrawn', 'final_cost_certified': False}


@router.get('/organizations/{org_id}/periods/{month}/production-overhead-history')
async def production_overhead_history(org_id: int, month: str, response: Response, ctx=Depends(member)):
    from modules.accounting.models import ProductionOverheadRevision
    from modules.accounting.production_cost_posting import overhead_history

    valid_month(month)
    rows = await overhead_history(ctx[0], org_id, month)
    response.headers['Cache-Control'] = 'private, no-store'
    allocations = []
    for row, state in rows:
        item = {**serialize(row), 'source_state': state, 'posted': True, 'final_cost_certified': False}
        revisions = (await ctx[0].scalars(select(ProductionOverheadRevision).where(
            ProductionOverheadRevision.original_entry_id == row.entry_id).order_by(ProductionOverheadRevision.sequence))).all()
        if revisions:
            item['corrections'] = [{'id': rev.id, 'sequence': rev.sequence, 'previous_id': rev.previous_id,
                'organization_id': org_id, 'month': month, 'original_entry_id': row.entry_id, 'entry_id': rev.entry_id,
                'actor': rev.actor, 'posting_date': rev.command['preview']['posting_date'],
                'evidence': rev.command['preview']['evidence'], 'lines': rev.preview['snapshot']['correction_lines']} for rev in revisions]
        allocations.append(item)
    return {'organization_id': org_id, 'month': month, 'allocations': allocations}


@router.get("/organizations/{org_id}/periods/{month}/financial-closing-history")
async def financial_closing_history(org_id: int, month: str, response: Response, ctx=Depends(member)):
    from modules.accounting.closing_history import history

    valid_month(month)
    result = await history(ctx[0], org_id, month)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.get("/organizations/{org_id}/periods/{month}/closing-controls")
async def closing_controls_snapshot(org_id: int, month: str, response: Response, ctx=Depends(member)):
    valid_month(month)
    try:
        result = await closing_controls.snapshot(ctx[0], org_id, month)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/periods/{month}/financial-closing-confirm", status_code=201)
async def financial_closing_confirm(org_id: int, month: str, data: FinancialCloseInput,
                                    response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.closing_commands import confirm

    chief(ctx)
    valid_month(month)
    receipt = await confirm(ctx[0], org_id, month, data, ctx[1], core.services.event_bus)
    period = await service.period_for(ctx[0], org_id, month)
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "month": month, "receipt_id": receipt.id,
            "request_key": receipt.request_key, "digest": receipt.digest,
            "monthly_entry_id": receipt.monthly_entry_id, "annual_entry_id": receipt.annual_entry_id,
            "closed": period.closed}


@router.post("/organizations/{org_id}/periods/{month}/reopen")
async def reopen(org_id: int, month: str, data: ReopenInput, ctx=Depends(member)):
    chief(ctx)
    valid_month(month)
    await service.reopen_period(ctx[0], org_id, month, data.reason, ctx[1])
    return {"reopened_from": month}


@router.post("/organizations/{org_id}/periods/{month}/financial-reopening-confirm", status_code=201)
async def financial_reopening_confirm(org_id: int, month: str, data: FinancialReopenConfirmInput,
                                      response: Response, ctx=Depends(member), core=Depends(get_core)):
    from modules.accounting.closing_commands import confirm_reopening

    chief(ctx)
    valid_month(month)
    receipt = await confirm_reopening(ctx[0], org_id, month, data, ctx[1], core.services.event_bus)
    current_periods = (await ctx[0].scalars(select(Period).where(
        Period.organization_id == org_id, Period.month >= month).order_by(Period.month))).all()
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "from_month": month, "receipt_id": receipt.id,
            "request_key": receipt.request_key, "digest": receipt.digest,
            "periods": receipt.snapshot["periods_after"], "items": receipt.snapshot["items"],
            "current_periods": [{"month": row.month, "closed": row.closed} for row in current_periods]}


@router.get("/organizations/{org_id}/periods/{month}/financial-reopening-preview")
async def financial_reopening_preview(org_id: int, month: str, response: Response, ctx=Depends(member)):
    from modules.accounting.closing_commands import preview_reopening

    chief(ctx)
    valid_month(month)
    result = await preview_reopening(ctx[0], org_id, month)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.get("/organizations/{org_id}/inbox")
async def inbox(org_id: int, ctx=Depends(member)):
    rows = (await ctx[0].scalars(select(Inbox).where(
        Inbox.organization_id == org_id, Inbox.entry_id.is_(None)
    ))).all()
    return [serialize(row) for row in rows]


@router.get("/organizations/{org_id}/source-controls")
async def source_controls(org_id: int, ctx=Depends(member)):
    rows = (await ctx[0].scalars(select(SourceControl).where(
        SourceControl.organization_id == org_id, SourceControl.entry_id.is_(None),
    ).order_by(SourceControl.month, SourceControl.id))).all()
    return [serialize(row) for row in rows]


@router.post("/organizations/{org_id}/inbox/{inbox_id}/confirm")
async def confirm(org_id: int, inbox_id: int, ctx=Depends(member), core=Depends(get_core)):
    chief(ctx)
    return serialize(await service.confirm_inbox(
        ctx[0], org_id, inbox_id, ctx[1], core.services.event_bus,
    ))


@router.post("/organizations/{org_id}/imports/preview")
async def import_preview(org_id: int, data: ImportInput, ctx=Depends(member)):
    chief(ctx)
    return await opening_import.preview(ctx[0], org_id, data)


@router.post("/organizations/{org_id}/imports/confirm")
async def import_confirm(org_id: int, data: ImportInput, ctx=Depends(member), core=Depends(get_core)):
    chief(ctx)
    return await opening_import.confirm(ctx[0], org_id, data, ctx[1], core.services.event_bus)


@router.get("/organizations/{org_id}/imports")
async def opening_imports(org_id: int, ctx=Depends(member)):
    return await opening_import.list_receipts(ctx[0], org_id)


@router.get("/organizations/{org_id}/input-vat-lines")
async def input_vat_lines(org_id: int, start: date, end: date, ctx=Depends(member)):
    return await input_vat.worksheet(ctx[0], org_id, start, end)


@router.get("/organizations/{org_id}/fixed-assets")
async def fixed_asset_rows(org_id: int, response: Response, ctx=Depends(member)):
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "rows": await fixed_assets.assets(ctx[0], org_id),
            "statutory_certified": False}


@router.post("/organizations/{org_id}/fixed-assets/preview")
async def fixed_asset_preview(org_id: int, data: FixedAssetRegisterInput,
                              response: Response, ctx=Depends(member)):
    try:
        result = await fixed_assets.prepare_register(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/fixed-assets/confirm", status_code=201)
async def fixed_asset_confirm(org_id: int, data: FixedAssetRegisterConfirmInput,
                              response: Response,
                              expected_principal: str = Header(alias="X-Expected-Principal"),
                              ctx=Depends(member)):
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the fixed asset again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        row = await fixed_assets.confirm_register(ctx[0], org_id, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**fixed_assets.serialize_asset(row), "status": "registered", "register_available": False,
            "statutory_certified": False}


@router.get("/organizations/{org_id}/fixed-assets/depreciation")
async def fixed_asset_depreciation_rows(org_id: int, response: Response,
                                        month: str | None = None, ctx=Depends(member)):
    try:
        rows = await fixed_assets.depreciation_rows(ctx[0], org_id, month)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "month": month, "rows": rows,
            "statutory_certified": False, "final_cost_certified": False}


@router.post("/organizations/{org_id}/fixed-assets/depreciation-preview")
async def fixed_asset_depreciation_preview(org_id: int, data: FixedAssetDepreciationInput,
                                           response: Response, ctx=Depends(member)):
    try:
        result = await fixed_assets.prepare_depreciation(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/fixed-assets/depreciation-confirm", status_code=201)
async def fixed_asset_depreciation_confirm(org_id: int, data: FixedAssetDepreciationConfirmInput,
                                           response: Response,
                                           expected_principal: str = Header(alias="X-Expected-Principal"),
                                           ctx=Depends(member), core=Depends(get_core)):
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the depreciation again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        row = await fixed_assets.confirm_depreciation(
            ctx[0], org_id, data, ctx[1], core.services.event_bus,
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**fixed_assets.serialize_depreciation(row), "status": "posted"}


@router.get("/organizations/{org_id}/fixed-assets/depreciation-status/{request_key}")
async def fixed_asset_depreciation_status(org_id: int, request_key: UUID,
                                          response: Response, ctx=Depends(member)):
    row = await fixed_assets.depreciation_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, "Fixed-asset depreciation outcome not found")
    response.headers["Cache-Control"] = "private, no-store"
    return {**fixed_assets.serialize_depreciation(row), "status": "posted"}


@router.get("/organizations/{org_id}/fixed-assets/{asset_id}")
async def fixed_asset_status(org_id: int, asset_id: int,
                             response: Response, ctx=Depends(member)):
    row = await fixed_assets.asset_result(ctx[0], org_id, asset_id)
    if row is None:
        raise HTTPException(404, "Fixed asset not found")
    response.headers["Cache-Control"] = "private, no-store"
    return {**fixed_assets.serialize_asset(row), "status": "registered"}


@router.get("/organizations/{org_id}/repairs")
async def repair_rows(org_id: int, response: Response, month: str | None = None,
                      ctx=Depends(member)):
    if month is not None:
        valid_month(month)
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "month": month,
            "rows": await repair_accounting.repair_rows(ctx[0], org_id, month),
            "final_cost_certified": False}


@router.post("/organizations/{org_id}/periods/{month}/repair-preview")
async def repair_preview(org_id: int, month: str, data: RepairAccountingInput,
                         response: Response, ctx=Depends(member)):
    valid_month(month)
    try:
        result = await repair_accounting.prepare_repair(ctx[0], org_id, month, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/periods/{month}/repair-confirm", status_code=201)
async def repair_confirm(org_id: int, month: str, data: RepairAccountingConfirmInput,
                         response: Response,
                         expected_principal: str = Header(alias="X-Expected-Principal"),
                         ctx=Depends(member), core=Depends(get_core)):
    valid_month(month)
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the repair again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        entry = await repair_accounting.confirm_repair(
            ctx[0], org_id, month, data, ctx[1], core.services.event_bus,
        )
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {"organization_id": org_id, "service_request_id": data.service_request_id,
            "request_key": str(data.request_key), "source_digest": data.source_digest,
            "digest": data.digest, "entry": serialize(entry), "entry_id": entry.id,
            "posted": True, "final_cost_certified": False}


@router.get("/organizations/{org_id}/repairs/{request_key}")
async def repair_status(org_id: int, request_key: UUID,
                        response: Response, ctx=Depends(member)):
    row = await repair_accounting.repair_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, "Repair accounting outcome not found")
    entry = await ctx[0].get(Entry, row.entry_id)
    if (entry is None or entry.organization_id != org_id
            or entry.operation != "repair_service"
            or entry.digest != row.digest
            or entry.source != f"service:repair:{org_id}:{row.service_request_id}"
            or entry.source_version != row.source_version):
        raise HTTPException(409, "Repair accounting receipt is inconsistent")
    response.headers["Cache-Control"] = "private, no-store"
    return {**repair_accounting.serialize_receipt(row), "posted": True,
            "final_cost_certified": False}


@router.get("/organizations/{org_id}/output-vat-lines")
async def output_vat_lines(org_id: int, start: date, end: date, ctx=Depends(member)):
    try:
        return await output_vat_register.worksheet(ctx[0], org_id, start, end)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/organizations/{org_id}/input-vat-register")
async def input_vat_register_rows(org_id: int, start: date, end: date,
                                  response: Response, ctx=Depends(member)):
    try:
        result = await input_vat_register.register_rows(ctx[0], org_id, start, end)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/input-vat-register/preview")
async def input_vat_register_preview(org_id: int, data: InputVatRegisterInput,
                                     response: Response, ctx=Depends(member)):
    try:
        result = await input_vat_register.prepare_register(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/input-vat-register/confirm", status_code=201)
async def input_vat_register_confirm(org_id: int, data: InputVatRegisterConfirmInput,
                                     response: Response,
                                     expected_principal: str = Header(alias="X-Expected-Principal"),
                                     ctx=Depends(member)):
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the register again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        row = await input_vat_register.confirm_register(ctx[0], org_id, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**input_vat_register.serialize_row(row), "status": "registered", "posted": False,
            "deduction_assessed": False}


@router.get("/organizations/{org_id}/input-vat-register/{request_key}")
async def input_vat_register_status(org_id: int, request_key: UUID,
                                    response: Response, ctx=Depends(member)):
    row = await input_vat_register.register_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, "Input-VAT register outcome not found")
    response.headers["Cache-Control"] = "private, no-store"
    return {**input_vat_register.serialize_row(row), "status": "registered", "posted": False,
            "deduction_assessed": False}


@router.get("/organizations/{org_id}/output-vat-register")
async def output_vat_register_rows(org_id: int, start: date, end: date,
                                   response: Response, ctx=Depends(member)):
    try:
        result = await output_vat_register.register_rows(ctx[0], org_id, start, end)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/output-vat-register/preview")
async def output_vat_register_preview(org_id: int, data: OutputVatRegisterInput,
                                      response: Response, ctx=Depends(member)):
    try:
        result = await output_vat_register.prepare_register(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/output-vat-register/confirm", status_code=201)
async def output_vat_register_confirm(org_id: int, data: OutputVatRegisterConfirmInput,
                                      response: Response,
                                      expected_principal: str = Header(alias="X-Expected-Principal"),
                                      ctx=Depends(member)):
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the register again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        row = await output_vat_register.confirm_register(ctx[0], org_id, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**output_vat_register.serialize_row(row), "status": "registered", "posted": False,
            "vat_treatment_verified": False}


@router.get("/organizations/{org_id}/output-vat-register/{request_key}")
async def output_vat_register_status(org_id: int, request_key: UUID,
                                     response: Response, ctx=Depends(member)):
    row = await output_vat_register.register_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, "Output-VAT register outcome not found")
    response.headers["Cache-Control"] = "private, no-store"
    return {**output_vat_register.serialize_row(row), "status": "registered", "posted": False,
            "vat_treatment_verified": False}


@router.get("/organizations/{org_id}/foreign-trade-lines")
async def foreign_trade_lines(org_id: int, start: date, end: date, ctx=Depends(member)):
    try:
        return await foreign_trade_register.worksheet(ctx[0], org_id, start, end)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/organizations/{org_id}/foreign-trade-register")
async def foreign_trade_register_rows(org_id: int, start: date, end: date,
                                      response: Response, ctx=Depends(member)):
    try:
        result = await foreign_trade_register.register_rows(ctx[0], org_id, start, end)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/foreign-trade-register/preview")
async def foreign_trade_register_preview(org_id: int, data: ForeignTradeRegisterInput,
                                         response: Response, ctx=Depends(member)):
    try:
        result = await foreign_trade_register.prepare_register(ctx[0], org_id, data)
    except service.AccountingError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/organizations/{org_id}/foreign-trade-register/confirm", status_code=201)
async def foreign_trade_register_confirm(org_id: int, data: ForeignTradeRegisterConfirmInput,
                                         response: Response,
                                         expected_principal: str = Header(alias="X-Expected-Principal"),
                                         ctx=Depends(member)):
    if expected_principal != ctx[1]:
        raise HTTPException(409, "Accounting principal changed; review the trade register again")
    if ctx[2] not in {"accountant", "chief"}:
        raise HTTPException(403, "Accounting write access required")
    try:
        row = await foreign_trade_register.confirm_register(ctx[0], org_id, data, ctx[1])
    except service.AccountingError as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {**foreign_trade_register.serialize_row(row), "status": "registered", "posted": False}


@router.get("/organizations/{org_id}/foreign-trade-register/{request_key}")
async def foreign_trade_register_status(org_id: int, request_key: UUID,
                                        response: Response, ctx=Depends(member)):
    row = await foreign_trade_register.register_result(ctx[0], org_id, request_key)
    if row is None:
        raise HTTPException(404, "Foreign-trade register outcome not found")
    response.headers["Cache-Control"] = "private, no-store"
    return {**foreign_trade_register.serialize_row(row), "status": "registered", "posted": False}
