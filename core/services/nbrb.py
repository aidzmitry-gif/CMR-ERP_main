"""Official BYN quotes, dated immutable evidence and automatic loading on demand.

AuditLog stores the original NBRB response: existing six-decimal reference rates
cannot preserve every scale exactly. Transactions belong to the caller.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text

from core.domain.models import AuditLog

URL = "https://api.nbrb.by/exrates/rates"
ACTION = "currency.nbrb.quote"


class RateUnavailable(ValueError):
    """No verified official rate for the requested currency and date."""


def today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


def validate(code: str, on: date) -> str:
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise RateUnavailable("Нужен трёхбуквенный код валюты ISO")
    if on < date(2016, 7, 1) or on > today():
        raise RateUnavailable("Нужна дата от 01.07.2016 до сегодняшней даты")
    return code


def parse_quote(data: dict, code: str, on: date) -> dict:
    try:
        if data["Cur_Abbreviation"] != code or date.fromisoformat(data["Date"][:10]) != on:
            raise ValueError("currency/date mismatch")
        rate = Decimal(str(data["Cur_OfficialRate"]))
        scale = Decimal(str(data["Cur_Scale"]))
        if not rate.is_finite() or not scale.is_finite() or rate <= 0 or scale <= 0:
            raise ValueError("invalid rate/scale")
        if scale != scale.to_integral_value():
            raise ValueError("fractional scale")
        return {"currency": code, "date": on.isoformat(), "official_rate": str(rate),
                "scale": int(scale), "rate": str(rate / scale), "source": "NBRB"}
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise RateUnavailable(f"Некорректный ответ НБРБ для {code} на {on}") from exc


async def quote(session, code: str, on: date, *, client=None) -> dict:
    code = validate(code, on)
    if code == "BYN":
        return {"currency": code, "date": on.isoformat(), "official_rate": "1",
                "scale": 1, "rate": "1", "source": "BYN"}
    key = f"nbrb:{code}:{on.isoformat()}"
    # Serialize cache insertion across PostgreSQL workers without a new schema.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
    cached = (await session.execute(select(AuditLog).where(
        AuditLog.action == ACTION, AuditLog.entity_ref == key
    ).order_by(AuditLog.id).limit(1))).scalar_one_or_none()
    if cached is not None:
        return cached.detail
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
                response = await http.get(f"{URL}/{code}", params={"parammode": 2, "ondate": on.isoformat()})
        else:
            response = await client.get(f"{URL}/{code}", params={"parammode": 2, "ondate": on.isoformat()})
        response.raise_for_status()
        data = json.loads(response.text, parse_float=Decimal)
        if not isinstance(data, dict):
            raise ValueError("missing rate")
        result = parse_quote(data, code, on)
    except (httpx.HTTPError, ValueError) as exc:
        raise RateUnavailable(f"Курс НБРБ {code} на {on} недоступен") from exc
    session.add(AuditLog(actor="nbrb", action=ACTION, entity_ref=key, detail=result))
    await session.flush()
    return result


async def convert(session, amount, code: str, on: date) -> tuple[Decimal, dict]:
    amount = Decimal(str(amount))
    if not amount.is_finite():
        raise RateUnavailable("Сумма должна быть конечным числом")
    result = await quote(session, code, on)
    value = amount * Decimal(result["official_rate"]) / Decimal(result["scale"])
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), result
