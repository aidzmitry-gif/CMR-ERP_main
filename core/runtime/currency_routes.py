"""Shared official exchange-rate API for all ERP modules."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config.access import allowed_slugs, is_super
from core.runtime.deps import get_session
from core.services import nbrb
from core.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/system/fx", tags=["currency"])


def currency_user(user: CurrentUser = Depends(get_current_user)):
    if not is_super(user.roles) and not allowed_slugs(user.roles):
        raise HTTPException(status_code=403, detail="Нужен доступ к ERP")
    return user


@router.get("/{currency}")
async def get_quote(currency: str, on: date, session=Depends(get_session),
                    user: CurrentUser = Depends(currency_user)):
    try:
        result = await nbrb.quote(session, currency, on)
    except nbrb.RateUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await session.commit()
    return result


class Conversion(BaseModel):
    amount: Decimal = Field(allow_inf_nan=False, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    on: date


@router.post("/convert")
async def convert(payload: Conversion, session=Depends(get_session),
                  user: CurrentUser = Depends(currency_user)):
    try:
        amount, rate = await nbrb.convert(session, payload.amount, payload.currency, payload.on)
    except nbrb.RateUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await session.commit()
    return {"amount_byn": str(amount), "quote": rate}
