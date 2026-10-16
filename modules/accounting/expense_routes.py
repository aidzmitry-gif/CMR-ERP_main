"""Scoped expense catalog, budget draft and approval endpoints."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select

from core.services.auth import (
    EffectiveIdentityLookupError,
    get_current_user,
    resolve_effective_oidc_user,
)
from modules.accounting import expenses
from modules.accounting.expense_models import ExpenseCommandReceipt
from modules.accounting.expense_schemas import (
    BudgetApprovalCommand,
    BudgetCommand,
    CatalogCommand,
    ExpenseAttributionCommand,
    ExpenseAttributionPreview,
)
from modules.accounting.routes import chief, organization_role, subject, transaction

router = APIRouter(prefix="/organizations/{org_id}", tags=["expense-control"])


async def expense_member(request: Request, session=Depends(transaction, scope="function"), user=Depends(get_current_user)):
    try:
        current = await resolve_effective_oidc_user(user, session)
        if current.local_status not in (None, "active"):
            raise HTTPException(403, "An active user is required")
        actor = subject(current)
        org_id = int(request.path_params["org_id"])
        await organization_role(session, org_id, actor)
        current = await resolve_effective_oidc_user(user, session)
        if current.local_status not in (None, "active"):
            raise HTTPException(403, "An active user is required")
        if subject(current) != actor:
            raise HTTPException(403, "Accounting identity changed while waiting")
        role = await organization_role(session, org_id, actor)
    except EffectiveIdentityLookupError as exc:
        raise HTTPException(503, "Current identity cannot be verified") from exc
    if request.method != "GET" and role == "reader":
        raise HTTPException(403, "Read-only accounting access")
    return session, actor, role


@router.get("/expense-catalog")
async def get_catalog(org_id: int, ctx=Depends(expense_member)):
    return expenses.envelope(
        org_id,
        ctx[1],
        {
            "catalog": await expenses.catalog(ctx[0], org_id),
            "role": ctx[2],
            "approval_enabled": True,
            "approval_blocker": None,
            "template": expenses.TEMPLATE,
        },
    )


@router.get("/expense-budgets")
async def get_budgets(
    org_id: int,
    year: int = Query(ge=2000, le=2100),
    currency: Literal["BYN"] = Query(),
    basis: Literal["cash", "accrual"] = Query(),
    ctx=Depends(expense_member),
):
    return expenses.envelope(
        org_id,
        ctx[1],
        {
            "year": year,
            "currency": currency,
            "basis": basis,
            "versions": await expenses.budgets(ctx[0], org_id, year, currency, basis),
            "approved_plan": await expenses.approved_budget(ctx[0], org_id, year, currency, basis),
            "actuals": {
                name: {
                    "amount": None,
                    "coverage": "unknown",
                    "reason": "Адаптер подтверждённых данных ещё не подключён",
                }
                for name in ("accrued", "paid", "commitments")
            },
            "approval_enabled": True,
            "approval_blocker": None,
        },
    )


@router.get("/expense-actuals")
async def get_actuals(
    org_id: int,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    currency: Literal["BYN"] = Query(),
    basis: Literal["cash", "accrual"] = Query(),
    ctx=Depends(expense_member),
):
    return expenses.envelope(
        org_id,
        ctx[1],
        {
            "year": year,
            "month": month,
            "currency": currency,
            "basis": basis,
            "actuals": await expenses.actuals(ctx[0], org_id, year, month, basis),
        },
    )


@router.get("/expense-actuals/unmatched")
async def get_unmatched_actuals(
    org_id: int, year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12),
    currency: Literal["BYN"] = Query(), basis: Literal["cash", "accrual"] = Query(),
    after_line_id: int | None = Query(default=None, ge=1), limit: int = Query(default=50, ge=1, le=100),
    ctx=Depends(expense_member),
):
    return expenses.envelope(org_id, ctx[1], await expenses.unmatched_actuals(ctx[0], org_id, year, month, basis, after_line_id, limit))


@router.get("/expense-commands/{request_key}")
async def get_receipt(org_id: int, request_key: UUID, ctx=Depends(expense_member)):
    row = await ctx[0].scalar(
        select(ExpenseCommandReceipt).where(
            ExpenseCommandReceipt.organization_id == org_id,
            ExpenseCommandReceipt.request_key == str(request_key),
        )
    )
    if row is None or row.actor != ctx[1]:
        raise HTTPException(404, "Квитанция исходной команды не найдена для текущего пользователя")
    try:
        return expenses.verified_receipt(row)
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/expense-attributions/preview")
async def preview_attribution(
    org_id: int,
    data: ExpenseAttributionPreview,
    expected: str = Header(alias="X-Expected-Principal"),
    ctx=Depends(expense_member),
):
    if expected != ctx[1]:
        raise HTTPException(409, "Пользователь изменился. Обновите сведения")
    try:
        return expenses.envelope(
            org_id, ctx[1], {"preview": await expenses.preview_attribution(ctx[0], org_id, data)}
        )
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/expense-attributions")
async def confirm_attribution(
    org_id: int,
    data: ExpenseAttributionCommand,
    expected: str = Header(alias="X-Expected-Principal"),
    ctx=Depends(expense_member),
):
    if expected != ctx[1]:
        raise HTTPException(409, "Пользователь изменился. Обновите сведения")
    try:
        return await expenses.confirm_attribution(ctx[0], org_id, ctx[1], data)
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/expense-attributions/{request_key}")
async def get_attribution_receipt(org_id: int, request_key: UUID, ctx=Depends(expense_member)):
    try:
        receipt = await expenses.attribution_receipt(ctx[0], org_id, ctx[1], request_key)
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if receipt is None:
        raise HTTPException(404, "Квитанция атрибуции не найдена для текущего пользователя")
    return receipt


async def command(org_id, data, kind, expected, ctx):
    if expected != ctx[1]:
        raise HTTPException(409, "Пользователь изменился. Обновите сведения")
    if kind == "catalog":
        chief(ctx)
    try:
        return await expenses.execute(ctx[0], org_id, ctx[1], kind, data)
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/expense-catalog/commands")
async def catalog_command(
    org_id: int,
    data: CatalogCommand,
    expected: str = Header(alias="X-Expected-Principal"),
    ctx=Depends(expense_member),
):
    return await command(org_id, data, "catalog", expected, ctx)


@router.post("/expense-budgets/drafts")
async def budget_command(
    org_id: int,
    data: BudgetCommand,
    expected: str = Header(alias="X-Expected-Principal"),
    ctx=Depends(expense_member),
):
    return await command(org_id, data, "budget", expected, ctx)


@router.post("/expense-budgets/approve")
async def approve_budget(
    org_id: int,
    data: BudgetApprovalCommand,
    expected: str = Header(alias="X-Expected-Principal"),
    ctx=Depends(expense_member),
):
    if expected != ctx[1]:
        raise HTTPException(409, "Пользователь изменился. Обновите сведения")
    chief(ctx)
    try:
        return await expenses.approve(ctx[0], org_id, ctx[1], data)
    except expenses.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
