"""Заполнение БД тестовым набором данных (как на макете доски).

Запуск (после применения миграций / на SQLite — после старта приложения):
    python scripts/seed.py
Идемпотентно: если данные уже есть — пропускает.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from core.domain.models import Contact, Counterparty, Sku, User
from core.services import build_services
from modules.sales.models import Activity, Deal, DealItem, KpiTarget, Message

KPI_DATE = date(2026, 6, 2)

SKU_DEFS = [
    ("AKB-60", "Аккумулятор 60 А·ч", "шт"),
    ("ROLL-5", "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015", "т"),
    ("REBAR-12", "Арматура А500С Ø12 мм ГОСТ 34028-2016", "т"),
]


def _demo_deals() -> list[Deal]:
    D = Decimal
    return [
        Deal(number="CRM-2024-0150", title="Поставка металлопроката", counterparty="ООО МеталлПром", amount=D("850000"), priority="Высокий", stage="new", owner="Иванов И.И.", next_step="Звонок", deal_date="12.05.2024", starred=True),
        Deal(number="CRM-2024-0157", title="Комплектующие для оборудования", counterparty="АО СтройКомплект", amount=D("1250000"), priority="Средний", stage="new", owner="Петров П.П.", next_step="Встреча", deal_date="12.05.2024"),
        Deal(number="CRM-2024-0158", title="Сервисное обслуживание", counterparty="ООО ТехноСервис", amount=D("320000"), priority="Низкий", stage="new", owner="Сидоров С.С.", next_step="КП", deal_date="11.05.2024"),
        Deal(number="CRM-2024-0132", title="Поставка оборудования", counterparty="ООО Завод Прогресс", amount=D("2500000"), priority="Высокий", stage="qual", owner="Иванов И.И.", next_step="КП", deal_date="12.05.2024", starred=True),
        Deal(number="CRM-2024-0133", title="Модернизация линии", counterparty="ПАО Энергия", amount=D("3200000"), priority="Средний", stage="qual", owner="Петров П.П.", next_step="Встреча", deal_date="11.05.2024"),
        Deal(number="CRM-2024-0134", title="Расходные материалы", counterparty="ООО КомплектСнаб", amount=D("480000"), priority="Низкий", stage="qual", owner="Иванов И.И.", next_step="КП", deal_date="11.05.2024"),
        Deal(number="CRM-2024-0156", title="Поставка металлопроката", counterparty="ООО АльфаМеталл", amount=D("1750000"), priority="Высокий", stage="prop", owner="Иванов П.П.", next_step="Получить подписанный договор", deal_date="12.05.2024", starred=True),
        Deal(number="CRM-2024-0135", title="Изготовление деталей", counterparty="АО Машиностроитель", amount=D("2900000"), priority="Средний", stage="prop", owner="Иванов И.И.", next_step="Согласование", deal_date="11.05.2024"),
        Deal(number="CRM-2024-0121", title="Комплексная поставка", counterparty="ПАО ХимПром", amount=D("4200000"), priority="Высокий", stage="appr", owner="Сидоров С.С.", next_step="Договор", deal_date="12.05.2024", starred=True),
        Deal(number="CRM-2024-0122", title="Строительные материалы", counterparty="ООО СтройИнвест", amount=D("1850000"), priority="Средний", stage="appr", owner="Иванов И.И.", next_step="Согласование", deal_date="11.05.2024"),
        Deal(number="CRM-2024-0101", title="Поставка металла", counterparty="ООО РегионСталь", amount=D("2100000"), priority="Высокий", stage="won", owner="Петров П.П.", closed_date="12.05.2024", starred=True),
        Deal(number="CRM-2024-0102", title="Оборудование", counterparty="АО БетаТех", amount=D("3750000"), priority="Средний", stage="won", owner="Иванов И.И.", closed_date="11.05.2024"),
        Deal(number="CRM-2024-0103", title="Комплектующие", counterparty="ООО Стандарт", amount=D("680000"), priority="Низкий", stage="won", owner="Сидоров С.С.", closed_date="10.05.2024"),
    ]


def _kpi_targets() -> list[KpiTarget]:
    D = Decimal
    return [
        KpiTarget(key="calls_key", title="Звонки ключевым клиентам", target=D("40"), unit="count", icon="phone-key", tone="blue", sort_order=1),
        KpiTarget(key="calls_all", title="Всего звонков", target=D("100"), unit="count", icon="phone", tone="indigo", sort_order=2),
        KpiTarget(key="ship_plan", title="План по сумме отгрузки", target=D("8000000"), unit="money", icon="ruble", tone="green", sort_order=3),
        KpiTarget(key="calls_cold", title="Холодные звонки", target=D("60"), unit="count", icon="snow", tone="cyan", sort_order=4),
        KpiTarget(key="requests", title="Обработка заявок", target=D("30"), unit="count", icon="doc", tone="slate", sort_order=5),
    ]


def _activities() -> list[Activity]:
    acts: list[Activity] = []
    for key, n in (("calls_key", 24), ("calls_all", 58), ("calls_cold", 32), ("requests", 18)):
        acts += [Activity(kpi_key=key, owner="Иван Петров", value=Decimal("1"), date=KPI_DATE) for _ in range(n)]
    for value in (2_500_000, 1_700_000, 1_000_000):
        acts.append(Activity(kpi_key="ship_plan", owner="Иван Петров", value=Decimal(value), date=KPI_DATE))
    return acts


async def main() -> None:
    services = build_services()
    services.db.init_engine()
    if services.db.is_sqlite:
        await services.db.connect()  # создаст таблицы в dev-режиме
    assert services.db.session_factory is not None

    async with services.db.session_factory() as s:
        # Общее ядро: контрагент, пользователь, контакт
        if (await s.execute(select(Counterparty))).scalars().first() is None:
            cp = Counterparty(name="ООО Аккумулятор", unp="191234567")
            s.add(cp)
            s.add(User(username="manager", full_name="Иван Менеджеров"))
            await s.flush()
            s.add(Contact(counterparty_id=cp.id, full_name="Пётр Петров", phone="+375291234567"))

        # Номенклатура (по коду, идемпотентно)
        existing_codes = set((await s.execute(select(Sku.code))).scalars().all())
        for code, title, unit in SKU_DEFS:
            if code not in existing_codes:
                s.add(Sku(code=code, title=title, unit=unit))
        await s.flush()

        # Сделки
        if (await s.execute(select(Deal))).scalars().first() is None:
            s.add_all(_demo_deals())
            await s.flush()

        # Позиции номенклатуры для сделки «АльфаМеталл»
        if (await s.execute(select(DealItem))).scalars().first() is None:
            alfa = (
                await s.execute(select(Deal).where(Deal.number == "CRM-2024-0156"))
            ).scalars().first()
            by_code = {sk.code: sk for sk in (await s.execute(select(Sku))).scalars().all()}
            if alfa and "ROLL-5" in by_code and "REBAR-12" in by_code:
                s.add(DealItem(deal_id=alfa.id, sku_id=by_code["ROLL-5"].id, qty=Decimal("12")))
                s.add(DealItem(deal_id=alfa.id, sku_id=by_code["REBAR-12"].id, qty=Decimal("8")))

        # Омниканальная переписка по сделке «АльфаМеталл» (ч.10)
        if (await s.execute(select(Message))).scalars().first() is None:
            alfa = (
                await s.execute(select(Deal).where(Deal.number == "CRM-2024-0156"))
            ).scalars().first()
            if alfa:
                s.add_all([
                    Message(deal_id=alfa.id, channel="whatsapp", direction="in", author="Клиент", text="Добрый день! Уточните сроки поставки листа 5 мм и возможность доставки на следующей неделе."),
                    Message(deal_id=alfa.id, channel="whatsapp", direction="out", author="Иванов П.П.", text="Здравствуйте! Лист 5 мм есть на складе, отгрузка в течение 2 дней, доставку организуем."),
                    Message(deal_id=alfa.id, channel="email", direction="out", author="Иванов П.П.", text="Направил коммерческое предложение на почту, спецификация во вложении."),
                ])

        # Цели KPI + активности (План/Факт)
        if (await s.execute(select(KpiTarget))).scalars().first() is None:
            s.add_all(_kpi_targets())
            s.add_all(_activities())

        await s.commit()
        print("seed: готово")

    await services.db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
