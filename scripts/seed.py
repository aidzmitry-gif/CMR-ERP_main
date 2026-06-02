"""Заполнение БД тестовым набором данных.

Запуск (после применения миграций):  ``python scripts/seed.py``
Идемпотентно: если данные уже есть — пропускает.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from core.domain.models import Contact, Counterparty, Sku, User
from core.services import build_services
from modules.sales.models import Deal


async def main() -> None:
    services = build_services()
    services.db.init_engine()
    assert services.db.session_factory is not None

    async with services.db.session_factory() as s:
        exists = (await s.execute(select(Counterparty))).scalars().first()
        if exists:
            print("seed: данные уже есть — пропускаю")
            return

        cp = Counterparty(name="ООО Аккумулятор", unp="191234567")
        s.add(cp)
        s.add(Sku(code="AKB-60", title="Аккумулятор 60 А·ч", unit="шт"))
        s.add(User(username="manager", full_name="Иван Менеджеров"))
        await s.flush()

        s.add(Contact(counterparty_id=cp.id, full_name="Пётр Петров", phone="+375291234567"))
        s.add(
            Deal(
                number="CRM-2026-0001",
                title="Поставка аккумуляторов",
                counterparty=cp.name,
                amount=Decimal("1750000"),
                priority="Высокий",
            )
        )
        await s.commit()
        print("seed: готово")

    await services.db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
