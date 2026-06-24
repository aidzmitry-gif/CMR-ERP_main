"""Заполнение БД тестовым набором данных (как на макете доски).

Запуск (после применения миграций / на SQLite — после старта приложения):
    python scripts/seed.py
Идемпотентно: если данные уже есть — пропускает.
"""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from modules.procurement.models import PurchaseRequest
from modules.production.models import ProductionOrder
from modules.wms.models import WarehouseOp
from sqlalchemy import select

from core.domain.models import Contact, Counterparty, Sku, User
from core.domain.reference import (
    Bank,
    Country,
    Currency,
    CurrencyRate,
    NomenclatureCategory,
    Unit,
    VatRate,
)
from core.services import build_services
from modules.hr.models import Candidate
from modules.knowledge.models import Course
from modules.leads.models import Lead
from modules.legal.models import LegalCase
from modules.office.models import OfficeDoc
from modules.sales.models import (
    Activity,
    ContractTemplate,
    Deal,
    DealItem,
    KpiTarget,
    Message,
    PriceQuote,
)

KPI_DATE = date(2026, 6, 2)

SKU_DEFS = [
    # code, title, unit, category_code (группа номенклатуры из ref_nomenclature_category)
    ("AKB-60", "Аккумулятор 60 А·ч", "шт", "CAT-0101"),
    ("ROLL-5", "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015", "т", "CAT-0201"),
    ("REBAR-12", "Арматура А500С Ø12 мм ГОСТ 34028-2016", "т", "CAT-0202"),
]

# Демо-дерево групп номенклатуры (adjacency list: parent_code → код предка).
# Корни — parent_code=None; обход рекурсивным CTE на стороне reference.query.
CATEGORY_DEFS = [
    # code, name, parent_code
    ("CAT-0100", "Аккумуляторы", None),
    ("CAT-0101", "Грузовые 6СТ", "CAT-0100"),
    ("CAT-0102", "Тяговые LiFePO4", "CAT-0100"),
    ("CAT-0200", "Металлопрокат", None),
    ("CAT-0201", "Листовой прокат", "CAT-0200"),
    ("CAT-0202", "Арматура", "CAT-0200"),
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


def _demo_leads() -> list[Lead]:
    """Демо-лиды для приёма (front-of-funnel): разные каналы, регионы, полнота данных."""
    return [
        Lead(source="site", name="Сергей Кравцов", company="ООО ТеплоСеть", phone="+375291002030",
             email="s.kravtsov@teploset.by", region="Минск", product="лист горячекатаный 5 мм",
             message="Нужен лист 5 мм, объём ~15 т, просьба прислать цену и сроки отгрузки."),
        Lead(source="tender", name="", company="РУП Гомельэнерго", region="Гомель",
             product="оборудование для подстанции",
             message="Тендерная заявка на поставку оборудования, бюджет уточняется."),
        Lead(source="whatsapp", name="Алексей", phone="+375447778899", region="",
             product="арматура", message="Почём арматура 12?"),
        Lead(source="email", name="Отдел снабжения", company="ОАО Машзавод", email="snab@mashzavod.by",
             region="Могилёв", product="комплектующие",
             message="Запрос на регулярные поставки комплектующих, рассматриваем долгосрочный договор."),
        Lead(source="phone", name="Без имени", region="", product="",
             message="Звонок: интересовались наличием."),
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


def _demo_purchases() -> list[PurchaseRequest]:
    """Демо-закупки во всех стадиях sourcing-цикла (для наполнения воронки)."""
    D = Decimal
    rows = [
        ("ЗАК-2026-0341", "Shenzhen SunPower Co.", "🇨🇳", "AGM аккумулятор 200Ah", 500, "1850000", "Высокий", "Иванов И.И.", "need", "08.06", "Спрос +34% за 30 дней — рекомендую партию 500 шт, окно цены закрывается"),
        ("ЗАК-2026-0342", "ООО МеталлСнаб", "🇧🇾", "Корпус АКБ стальной", 1000, "920000", "Средний", "Петров П.П.", "sourcing", "10.06", "Найдено 12 поставщиков на 1688 — Supplier Agent сравнивает цены и MOQ"),
        ("PO-2026-0288", "Hangzhou Hybrid", "🇨🇳", "Hybrid Inverter 5kW", 200, "2400000", "Высокий", "Иванов И.И.", "nego", "12.06", "AI торгуется: −8% от прайса согласовано, уточняем Incoterms (FOB → CIF)"),
        ("ЗАК-2026-0343", "Guangzhou Cells", "🇨🇳", "Ячейки LiFePO4 3.2V", 2000, "3100000", "Высокий", "Сидоров С.С.", "analysis", "14.06", "Supplier Score 8.7 — лучшая цена FOB, риск поставки низкий"),
        ("ЗАК-2026-0344", "ООО ПромКомплект", "🇧🇾", "BMS 16S 48V", 300, "780000", "Средний", "Петров П.П.", "approval", "09.06", "Прогноз маржи 28%, ROI 31% — рекомендую к одобрению"),
        ("PO-2026-0289", "Shenzhen SunPower Co.", "🇨🇳", "MPPT контроллер 60A", 400, "1320000", "Средний", "Иванов И.И.", "po", "20.06", "Цена на 1688 ниже на 4% — выгодное окно для PO"),
        ("PO-2026-0290", "Ningbo Power", "🇨🇳", "Клеммы и шины", 5000, "450000", "Низкий", "Сидоров С.С.", "supply", "25.06", "Консолидировать в один контейнер с PO-0289 (FCL)"),
        ("ЗАК-2026-0345", "ООО ТехноИмпорт", "🇧🇾", "Зарядные устройства", 150, "670000", "Средний", "Петров П.П.", "qc", "06.06", "QC по фото: партия соответствует, брак 0%"),
        ("ЗАК-2026-0320", "Guangzhou Cells", "🇨🇳", "Ячейки LiFePO4 (партия 12)", 2000, "3050000", "Высокий", "Иванов И.И.", "done", "01.06", "Закрыто: экономия 180 000 ₽ против бюджета"),
    ]
    return [
        PurchaseRequest(number=n, supplier=sup, flag=fl, item=it, qty=q, amount=D(a), priority=pr, owner=o, stage=st, due_date=dd, insight=ins)
        for n, sup, fl, it, q, a, pr, o, st, dd, ins in rows
    ]


def _demo_production() -> list[ProductionOrder]:
    """Демо-наряды на всех этапах канбана цеха."""
    rows = [
        ("ПЗ-2026-0192", "Инвертор Hybrid 5kW", 60, 0, "Высокий", "Мастер Орлов", "queue", "06.06", "Заказ клиента CRM-0156 — старт сегодня, успеваем к отгрузке 12.06"),
        ("ПЗ-2026-0190", "АКБ LiFePO4 48V 100Ah", 200, 15, "Средний", "Мастер Орлов", "picking", "07.06", "AI зарезервировал 100/100 ячеек, BMS придёт 04.06"),
        ("ПЗ-2026-0188", "Контроллер MPPT 60A", 80, 55, "Средний", "Мастер Гром", "assembly", "06.06", "Ход работ в графике, узких мест нет"),
        ("ПЗ-2026-0184", "АКБ LiFePO4 48V 100Ah", 120, 80, "Высокий", "Контролёр Волк", "qc", "06.06", "Дефицит BMS — риск простоя 1 день, взять 36 шт из резерва 0190"),
        ("ПЗ-2026-0181", "Зарядная станция 7кВт", 30, 92, "Низкий", "Мастер Орлов", "packing", "05.06", "Готово к упаковке, маркировка сформирована"),
        ("ПЗ-2026-0176", "Инвертор Hybrid 3kW", 100, 100, "Средний", "Мастер Гром", "done", "04.06", "Сдано на склад, ОТК пройден"),
    ]
    return [
        ProductionOrder(number=n, product=p, qty=q, progress=pg, priority=pr, owner=o, stage=st, due_date=dd, insight=ins)
        for n, p, q, pg, pr, o, st, dd, ins in rows
    ]


def _demo_warehouse_ops() -> list[WarehouseOp]:
    """Демо-операции склада на всех стадиях логистического цикла."""
    D = Decimal
    rows = [
        ("ПС-2026-0156", "ООО МеталлПром", "Металлопрокат", 12, "850000", "", "Высокий", "Иванов И.И.", "inbound", "12.05"),
        ("ПР-2026-0132", "ООО СтройКомплект", "Комплектующие", 24, "1250000", "", "Средний", "Сидоров С.С.", "receiving", "12.05"),
        ("КК-2026-0121", "ПАО ХимПром", "Химия техническая", 8, "420000", "", "Средний", "ОТК Волкова", "qc", "11.05"),
        ("РЗ-2026-0140", "ООО МеталлПром", "Размещение проката", 12, "0", "Зона A · Стеллаж 3", "Низкий", "Сидоров С.С.", "putaway", "12.05"),
        ("ПД-2026-0150", "ООО АльфаМеталл", "Сборка заказа", 12, "1750000", "Зона B", "Высокий", "Иванов И.И.", "picking", "12.05"),
        ("ОТ-2026-0160", "ООО РегионСталь", "Готов к отгрузке", 20, "2100000", "", "Высокий", "Петров П.П.", "ready", "12.05"),
        ("ОТ-2026-0101", "АО БетаТех", "Отгружено клиенту", 15, "1500000", "", "Средний", "Петров П.П.", "shipped", "11.05"),
    ]
    return [
        WarehouseOp(number=n, counterparty=cp, title=t, items_count=ic, amount=D(a), zone=z, priority=pr, owner=o, stage=st, op_date=od)
        for n, cp, t, ic, a, z, pr, o, st, od in rows
    ]


def _demo_candidates() -> list[Candidate]:
    """Демо-кандидаты на всех этапах воронки подбора."""
    D = Decimal
    rows = [
        # Новая вакансия (5)
        ("CAND-2026-1245", "Сергей Кравцов", "Менеджер по продажам", "90000", "Орлова М.", "Средний", "new", "Связаться по телефону"),
        ("CAND-2026-1250", "Игорь Сафонов", "Менеджер по продажам", "95000", "Орлова М.", "Средний", "new", "Первичный контакт"),
        ("CAND-2026-1251", "Марина Власова", "Маркетолог", "85000", "Орлова М.", "Низкий", "new", "Изучить резюме"),
        ("CAND-2026-1252", "Павел Гусев", "Логист", "78000", "Сидоров С.", "Низкий", "new", "Связаться с кандидатом"),
        ("CAND-2026-1246", "Анна Иванова", "Бухгалтер", "110000", "Орлова М.", "Высокий", "new", "Назначить интервью"),
        # Приглашение к интервью (3)
        ("CAND-2026-1247", "Дмитрий Лебедев", "Инженер-технолог", "140000", "Сидоров С.", "Высокий", "invite", "Согласовать время интервью"),
        ("CAND-2026-1253", "Ольга Никитина", "Бухгалтер", "105000", "Орлова М.", "Средний", "invite", "Отправить приглашение"),
        ("CAND-2026-1254", "Артём Фролов", "Логист", "85000", "Сидоров С.", "Низкий", "invite", "Пригласить на скрининг"),
        # Техническое интервью (2)
        ("CAND-2026-1255", "Анна Смирнова", "Менеджер по продажам", "155000", "Орлова М.", "Высокий", "tech", "Тех. собеседование 15:00"),
        ("CAND-2026-1256", "Виктор Зайцев", "Инженер-технолог", "135000", "Сидоров С.", "Средний", "tech", "Тех. интервью"),
        # Оффер (2)
        ("CAND-2026-1248", "Ольга Новикова", "HR-специалист", "95000", "Орлова М.", "Средний", "offer", "Согласовать оффер"),
        ("CAND-2026-1257", "Роман Ковалёв", "Менеджер по продажам", "160000", "Орлова М.", "Высокий", "offer", "Отправить оффер"),
        # Нанят (1)
        ("CAND-2026-1240", "Игорь Соколов", "Кладовщик", "70000", "Сидоров С.", "Низкий", "hired", "Оформление документов"),
    ]
    return [
        Candidate(number=n, name=nm, position=p, salary=D(s), recruiter=r, priority=pr, stage=st, next_step=ns)
        for n, nm, p, s, r, pr, st, ns in rows
    ]


def _demo_office_docs() -> list[OfficeDoc]:
    """Демо-документы по сделкам на всех стадиях офис-менеджера."""
    D = Decimal
    rows = [
        ("CRM-2026-0156", "ООО МеталлПром", "Поставка металлопроката", "850000", "Со склада · в наличии", "Документы готовы (4/4)", "Высокий", "Иванов И.И.", "ready", "Запланировать отгрузку", "12.05"),
        ("CRM-2026-0157", "АО СтройКомплект", "Комплектующие для оборудования", "1250000", "Курьер · в пути", "Не хватает: УПД, ТТН", "Средний", "Петров П.П.", "shipped", "Получить документы", "12.05"),
        ("CRM-2026-0158", "ООО ТехноСервис", "Сервисное обслуживание", "320000", "Самовывоз", "Сбор документов 2/4", "Низкий", "Сидоров С.С.", "docs", "Запросить акты", "11.05"),
        ("CRM-2026-0121", "ПАО ХимПром", "Комплексная поставка", "4200000", "Со склада · произведено", "Ожидает оплаты", "Высокий", "Иванов И.И.", "await_pay", "Контроль оплаты", "12.05"),
        ("CRM-2026-0101", "ООО РегионСталь", "Поставка металла", "2100000", "Доставлено", "Оплачено", "Высокий", "Петров П.П.", "paid", "Сделка закрыта", "11.05"),
    ]
    return [
        OfficeDoc(number=n, company=c, title=t, amount=D(a), delivery=d, docs_status=ds, priority=pr, owner=o, stage=st, next_step=ns, op_date=od)
        for n, c, t, a, d, ds, pr, o, st, ns, od in rows
    ]


def _demo_legal_cases() -> list[LegalCase]:
    """Демо-дела юр-отдела на всех стадиях контроля и взыскания."""
    D = Decimal
    rows = [
        ("ДОГ-2026-0156", "ООО МеталлПром", "Договор поставки металлопроката", "850000", "Контроль", "inbox", "Проверить условия и риски", "08.06"),
        ("ДОГ-2026-0158", "АО СтройКомплект", "Рамочный договор поставки", "0", "Обычный", "contract", "Согласовать редакцию", "10.06"),
        ("ПР-2026-0044", "ООО Должник", "Претензия по просроченной оплате", "1200000", "Срочно", "claim", "Направить досудебную претензию", "06.06"),
        ("ИН-2026-0012", "ИП Сидоров", "Исполнительная надпись нотариуса", "340000", "Контроль", "writ", "Подать документы нотариусу", "12.06"),
        ("СД-2026-0009", "ООО Неплательщик", "Судебное взыскание задолженности", "2100000", "Срочно", "court", "Судебное заседание", "15.06"),
        ("ДЕЛО-2026-0001", "ООО Партнёр", "Взыскано в досудебном порядке", "780000", "Обычный", "done", "Закрыто", "01.06"),
    ]
    return [
        LegalCase(number=n, company=c, title=t, amount=D(a), urgency=u, stage=st, next_step=ns, due_date=dd, owner="Юрист Зайцев")
        for n, c, t, a, u, st, ns, dd in rows
    ]


def _demo_courses() -> list[Course]:
    """Демо-курсы программы обучения по всем разделам."""
    rows = [
        ("КУРС-001", "Знакомство с продуктом", "Линейка аккумуляторов и инверторов", "Видео", 40, 100, "Кандидаты", "trial"),
        ("КУРС-014", "Охрана труда (ТБ)", "Обязательный вводный инструктаж", "Обязательно", 30, 0, "Адаптация новичков", "intro"),
        ("КУРС-021", "CRM: ведение сделок", "Работа с воронкой и карточкой сделки", "Практика", 60, 45, "Первые 3 месяца", "probation"),
        ("КУРС-030", "Промпт-инжиниринг", "Основы работы с AI-ассистентом", "Тест", 50, 20, "Для всех сотрудников", "ai"),
        ("КУРС-042", "Переговоры с поставщиками", "Тактики закупок в Китае", "Документ", 90, 10, "Текущие сотрудники", "growth"),
    ]
    return [
        Course(number=n, title=t, description=d, kind=k, duration=dur, progress=pg, audience=a, stage=st)
        for n, t, d, k, dur, pg, a, st in rows
    ]


async def main() -> None:
    services = build_services()
    services.db.init_engine()
    if services.db.is_sqlite:
        await services.db.connect()  # создаст таблицы в dev-режиме
    assert services.db.session_factory is not None

    async with services.db.session_factory() as s:
        # Системные справочники ядра (reference data): единицы, валюты+курсы, страны, банки, НДС.
        # Историчные (курс/НДС) — версии SCD2: текущая = end_date None.
        if (await s.execute(select(Unit))).scalars().first() is None:
            s.add_all([
                Unit(code="шт", title="Штука"),
                Unit(code="кг", title="Килограмм"),
                Unit(code="м", title="Метр"),
                Unit(code="т", title="Тонна"),
            ])
        if (await s.execute(select(Currency))).scalars().first() is None:
            s.add_all([
                Currency(code="BYN", title="Белорусский рубль"),
                Currency(code="USD", title="Доллар США"),
                Currency(code="EUR", title="Евро"),
            ])
        if (await s.execute(select(CurrencyRate))).scalars().first() is None:
            s.add_all([
                CurrencyRate(currency_code="USD", rate=Decimal("3.18"),
                             start_date=date(2026, 1, 1), end_date=date(2026, 5, 1)),
                CurrencyRate(currency_code="USD", rate=Decimal("3.25"),
                             start_date=date(2026, 5, 1), end_date=date(2026, 6, 10)),
                CurrencyRate(currency_code="USD", rate=Decimal("3.21"),
                             start_date=date(2026, 6, 10), end_date=None),
                CurrencyRate(currency_code="EUR", rate=Decimal("3.46"),
                             start_date=date(2026, 1, 1), end_date=None),
            ])
        if (await s.execute(select(Country))).scalars().first() is None:
            s.add_all([
                Country(code="BY", title="Беларусь"),
                Country(code="RU", title="Россия"),
                Country(code="CN", title="Китай"),
            ])
        if (await s.execute(select(Bank))).scalars().first() is None:
            s.add_all([
                Bank(code="153001749", title="ОАО «Приорбанк»", swift="PJCBBY2X"),
                Bank(code="153001270", title="ОАО «АСБ Беларусбанк»", swift="AKBBBY2X"),
            ])
        if (await s.execute(select(VatRate))).scalars().first() is None:
            s.add_all([
                VatRate(code="НДС20", title="НДС 20%", rate=Decimal("20.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="НДС10", title="НДС 10%", rate=Decimal("10.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="НДС0", title="Без НДС (0%)", rate=Decimal("0.00"),
                        start_date=date(2024, 1, 1), end_date=None),
            ])
        await s.flush()

        # Общее ядро: контрагент, пользователь, контакт
        if (await s.execute(select(Counterparty))).scalars().first() is None:
            cp = Counterparty(name="ООО Аккумулятор", unp="191234567")
            s.add(cp)
            s.add(User(username="manager", full_name="Иван Менеджеров"))
            await s.flush()
            s.add(Contact(counterparty_id=cp.id, full_name="Пётр Петров", phone="+375291234567"))

        # Группы (категории) номенклатуры — иерархия (parent_id строится по коду предка).
        if (await s.execute(select(NomenclatureCategory))).scalars().first() is None:
            s.add_all([NomenclatureCategory(code=c, name=n) for c, n, _ in CATEGORY_DEFS])
            await s.flush()  # получить id, чтобы связать parent_id
        cat_by_code = {
            c.code: c for c in (await s.execute(select(NomenclatureCategory))).scalars().all()
        }
        for code, _name, parent_code in CATEGORY_DEFS:
            cat, parent = cat_by_code.get(code), cat_by_code.get(parent_code)
            if cat and parent and cat.parent_id is None:
                cat.parent_id = parent.id

        # Номенклатура (по коду, идемпотентно) — с привязкой к группе.
        existing_codes = set((await s.execute(select(Sku.code))).scalars().all())
        for code, title, unit, cat_code in SKU_DEFS:
            if code not in existing_codes:
                cat = cat_by_code.get(cat_code)
                s.add(Sku(code=code, title=title, unit=unit,
                          category_id=cat.id if cat else None))
        await s.flush()

        # Сделки
        if (await s.execute(select(Deal))).scalars().first() is None:
            s.add_all(_demo_deals())
            await s.flush()

        # Шаблон договора по умолчанию (SALES-53) — «Поставка товара» с плейсхолдерами {{...}}.
        if (await s.execute(select(ContractTemplate))).scalars().first() is None:
            s.add(ContractTemplate(
                code="supply",
                name="Договор поставки товара",
                body=(
                    "ДОГОВОР ПОСТАВКИ {{number}}\n\n"
                    "Продавец: {{seller.name}}, УНП {{seller.unp}}, {{seller.address}}.\n"
                    "Покупатель: {{buyer.name}}, УНП {{buyer.unp}}, {{buyer.address}}.\n\n"
                    "Предмет: {{items}}. Сумма: {{total}}.\n"
                    "Условия оплаты: {{payment_terms}}.\n"
                    "Условия поставки: {{delivery_terms}}.\n"
                    "Счёт действителен до: {{valid_until}}.\n"
                ),
            ))

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

        # Контакты контрагента «АльфаМеталл» (sales-13)
        if (await s.execute(select(Contact).where(Contact.is_primary))).scalars().first() is None:
            alfa_cp = (
                await s.execute(select(Counterparty).where(Counterparty.name == "ООО АльфаМеталл"))
            ).scalars().first()
            if alfa_cp is None:
                alfa_cp = Counterparty(name="ООО АльфаМеталл", unp="190445566")
                s.add(alfa_cp)
                await s.flush()
            s.add_all([
                Contact(counterparty_id=alfa_cp.id, full_name="Иван Петров", phone="+375291112233", email="ivanov@alfametall.by", is_primary=True),
                Contact(counterparty_id=alfa_cp.id, full_name="Светлана Орлова", phone="+375293334455", email="orlova@alfametall.by"),
            ])

        # История цен (Price Engine) по позициям сделки «АльфаМеталл» (ч.10)
        if (await s.execute(select(PriceQuote))).scalars().first() is None:
            for code, prices in (("ROLL-5", [1500, 1450, 1470]), ("REBAR-12", [1250, 1200])):
                for p in prices:
                    s.add(PriceQuote(sku_code=code, counterparty="ООО АльфаМеталл", price=Decimal(str(p))))

        # Лиды на приёме (вход воронки: приём → квалификация → распределение)
        if (await s.execute(select(Lead))).scalars().first() is None:
            s.add_all(_demo_leads())

        # Цели KPI + активности (План/Факт)
        if (await s.execute(select(KpiTarget))).scalars().first() is None:
            s.add_all(_kpi_targets())
            s.add_all(_activities())

        # Воронки ERP-модулей (закупки, производство, склад, HR, офис, юр, обучение)
        for model, demo in (
            (PurchaseRequest, _demo_purchases),
            (ProductionOrder, _demo_production),
            (WarehouseOp, _demo_warehouse_ops),
            (Candidate, _demo_candidates),
            (OfficeDoc, _demo_office_docs),
            (LegalCase, _demo_legal_cases),
            (Course, _demo_courses),
        ):
            if (await s.execute(select(model))).scalars().first() is None:
                s.add_all(demo())

        await s.commit()
        print("seed: готово")

    await services.db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
