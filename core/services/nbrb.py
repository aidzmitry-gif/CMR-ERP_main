"""Official dated NBRB exchange-rate evidence for ERP calculations.

The accounting layer must receive a dated quote with its official scale and
source.  This service is deliberately separate from the legacy management
finance helper in ``modules.finance.fx``: it has no demo table and no
commercial buffer. A fetched quote is cached in the audit log; this service
never overwrites it. Database-level immutability is not guaranteed here.
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
    """No verified official rate is available for the requested date."""


class RateRequestInvalid(RateUnavailable):
    """The requested currency, date or amount is invalid."""


def today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


def validate(code: str, on: date) -> str:
    if not isinstance(code, str):
        raise RateRequestInvalid("Нужен трёхбуквенный код валюты ISO")
    normalized = code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", normalized):
        raise RateRequestInvalid("Нужен трёхбуквенный код валюты ISO")
    if on < date(2016, 7, 1) or on > today():
        raise RateRequestInvalid("Нужна дата от 01.07.2016 до сегодняшней даты")
    return normalized


def parse_quote(data: dict, code: str, on: date) -> dict:
    """Validate and normalize one official NBRB response.

    NBRB publishes a rate for ``Cur_Scale`` units.  Both the original official
    rate and the normalized one are retained; downstream accounting uses the
    exact official rate/scale pair rather than a rounded display value.
    """
    try:
        if data["Cur_Abbreviation"] != code or date.fromisoformat(data["Date"][:10]) != on:
            raise ValueError("currency/date mismatch")
        official_rate = Decimal(str(data["Cur_OfficialRate"]))
        scale = Decimal(str(data["Cur_Scale"]))
        if not official_rate.is_finite() or not scale.is_finite() or official_rate <= 0 or scale <= 0:
            raise ValueError("invalid rate/scale")
        if scale != scale.to_integral_value():
            raise ValueError("fractional scale")
        return {
            "currency": code,
            "date": on.isoformat(),
            "official_rate": str(official_rate),
            "scale": int(scale),
            "rate": str(official_rate / scale),
            "source": "NBRB",
        }
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise RateUnavailable(f"Некорректный ответ НБРБ для {code} на {on}") from exc


async def quote(session, code: str, on: date, *, client=None) -> dict:
    """Return a cached or freshly verified quote; caller owns the commit."""
    code = validate(code, on)
    if code == "BYN":
        return {
            "currency": code, "date": on.isoformat(), "official_rate": "1",
            "scale": 1, "rate": "1", "source": "BYN",
        }
    key = f"nbrb:{code}:{on.isoformat()}"
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
    cached = (await session.execute(select(AuditLog).where(
        AuditLog.action == ACTION, AuditLog.entity_ref == key,
    ).order_by(AuditLog.id).limit(1))).scalar_one_or_none()
    if cached is not None:
        detail = cached.detail
        if not isinstance(detail, dict):
            raise RateUnavailable("Сохранённое доказательство курса повреждено")
        verified = parse_quote({
            "Cur_Abbreviation": detail.get("currency"),
            "Date": detail.get("date"),
            "Cur_OfficialRate": detail.get("official_rate"),
            "Cur_Scale": detail.get("scale"),
        }, code, on)
        if detail != verified:
            raise RateUnavailable("Сохранённое доказательство курса повреждено")
        return verified
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
                response = await http.get(f"{URL}/{code}", params={"parammode": 2, "ondate": on.isoformat()})
        else:
            response = await client.get(f"{URL}/{code}", params={"parammode": 2, "ondate": on.isoformat()})
        response.raise_for_status()
        # Preserve decimal digits from the provider instead of a float round trip.
        data = json.loads(response.text, parse_float=Decimal)
        if not isinstance(data, dict):
            raise ValueError("missing rate")
        result = parse_quote(data, code, on)
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RateUnavailable(f"Курс НБРБ {code} на {on} недоступен") from exc
    session.add(AuditLog(actor="nbrb", action=ACTION, entity_ref=key, detail=result))
    await session.flush()
    return result


async def convert(session, amount, code: str, on: date) -> tuple[Decimal, dict]:
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RateRequestInvalid("Сумма должна быть конечным числом") from exc
    if not amount.is_finite():
        raise RateRequestInvalid("Сумма должна быть конечным числом")
    result = await quote(session, code, on)
    value = amount * Decimal(result["official_rate"]) / Decimal(result["scale"])
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), result
