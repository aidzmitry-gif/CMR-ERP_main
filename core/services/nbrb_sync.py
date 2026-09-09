"""Hourly retry of daily NBRB refresh; independent of financial event delivery."""
import asyncio
import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, text

from core.domain.models import OutboxEvent
from core.domain.reference import Currency, CurrencyRate
from core.services import nbrb, scd2

logger = logging.getLogger(__name__)


async def sync_currency(session, code, on):
    code = nbrb.validate(code, on)
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                              {"key": f"nbrb-reference:{code}"})
    rate = await nbrb.quote(session, code, on)
    display_rate = Decimal(rate["rate"]).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    current = await scd2.current_version(session, CurrencyRate, "currency_code", code)
    if current is None or current.start_date < on:
        await scd2.add_version(session, CurrencyRate, "currency_code", code, on, rate=display_rate)
        session.add(OutboxEvent(event_type="reference.ref_currency_rate.changed", payload={
            "action": "version", "ref_key": "core.currency_rates",
            "entity_ref": f"ref_currency_rate:{code}", "value_hint": f"NBRB {on}",
            "actor": "nbrb",
        }))
    elif current.start_date == on and current.rate != display_rate:
        raise nbrb.RateUnavailable(f"Ручной курс {code} на {on} отличается от НБРБ")
    return rate


async def run(services):
    while True:
        try:
            async with services.db.session_factory() as session:
                codes = set((await session.execute(
                    select(Currency.code).where(Currency.is_active.is_(True))
                )).scalars()) | {"BYN", "USD", "EUR", "RUB", "CNY", "PLN"}
            for code in sorted(codes):
                try:
                    async with services.db.session_factory() as session:
                        await sync_currency(session, code, nbrb.today())
                        await session.commit()
                except Exception:
                    logger.exception("NBRB refresh failed for %s", code)
        except Exception:
            logger.exception("NBRB refresh failed")
        await asyncio.sleep(3600)
