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

from core.domain.models import Contact, Counterparty, Sku, SurvivorshipRule, User
from core.domain.reference import (
    Account,
    Bank,
    Country,
    Currency,
    CurrencyRate,
    NomenclatureCategory,
    Region,
    TnvedCode,
    Unit,
    VatRate,
)
from core.services import build_services
from modules.hr.models import Candidate
from modules.integrations.models import Batch, StockItem
from modules.knowledge.models import Course
from modules.leads.models import Lead
from modules.legal.models import LegalCase
from modules.logistics import seeds as logistics_seeds
from modules.logistics.models import (
    Carrier,
    CarrierBid,
    CarrierCargoCapability,
    CarrierRfq,
    CarrierRfqInvite,
    CarrierScorecard,
    CarrierTariff,
    CarrierVehicle,
    FreightAuditLog,
    ImportShipment,
    Shipment,
    Zone,
)
from modules.logistics.schemas import CARRIERS_RB
from modules.office.models import OfficeDoc
from modules.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    Rfq,
    RfqBid,
    Supplier,
    SupplierClaim,
)
from modules.production.models import ProductionOrder
from modules.sales.models import (
    Activity,
    ContractTemplate,
    Deal,
    DealItem,
    KpiTarget,
    LossReason,
    Message,
    PriceQuote,
)
from modules.wms.models import (
    CycleCountPlan,
    InventoryCount,
    InventoryLine,
    Location,
    Receipt,
    ReceiptLine,
    StockMovement,
    StockThreshold,
    Task,
    WarehouseOp,
)

KPI_DATE = date(2026, 6, 2)

SKU_DEFS = [
    # code, title, unit, category_code (вид номенклатуры из ref_nomenclature_category — коды 1С)
    # Демо-товары привязаны к реальным видам из 1С (батарейки → 01/02, прочее → профильные группы).
    # — Щелочные батарейки (вид 01) —
    ("AKB-60", "Щелочная батарейка AAA LR03 (демо)", "шт", "1.1"),
    ("AKB-100", "Щелочная батарейка AA LR6 (демо)", "шт", "1.2"),
    ("AKB-132", "Щелочная батарейка C LR14 (демо)", "шт", "1.3"),
    ("AKB-190", "Щелочная батарейка D LR20 (демо)", "шт", "1.4"),
    ("AKB-225", "Щелочная 9V 6LR61 (демо)", "шт", "1.5"),
    # — Солевые батарейки (вид 02) —
    ("LFP-12-100", "Солевая батарейка AAA R03 (демо)", "шт", "2.1"),
    ("LFP-24-200", "Солевая батарейка AA R6 (демо)", "шт", "2.2"),
    # — Зарядные устройства / станции —
    ("ZU-15A", "Зарядное устройство ЗУ-15А (демо)", "шт", "30"),
    ("ZU-30A", "Зарядное устройство ЗУ-30А (демо)", "шт", "30"),
    ("TESTER-D", "Тестер АКБ цифровой (демо)", "шт", "31"),
    # — Измерительные приборы / ИБП —
    ("ROLL-3", "Мультиметр цифровой (демо)", "шт", "33"),
    ("ROLL-5", "Дисплей индикации заряда (демо)", "шт", "34"),
    ("ROLL-8", "Преобразователь 12→220В (демо)", "шт", "32"),
    ("INOX-2", "ИБП 1000ВА (демо)", "шт", "37"),
    # — Power bank / прочее —
    ("REBAR-10", "Power bank 10000 мА·ч (демо)", "шт", "39"),
    ("REBAR-12", "Power bank 20000 мА·ч (демо)", "шт", "39"),
    ("REBAR-16", "Литиевая батарейка CR2032 (демо)", "шт", "4.1"),
    ("REBAR-20", "Двигатель тяговый (демо)", "шт", "36"),
    # — Тестовые позиции по разным группам (пометка «(тест)») — для проверки дерева/карточки —
    ("TEST-AAA", "Тестовая щелочная AAA (тест)", "шт", "1.1"),
    ("TEST-AA", "Тестовая солевая AA (тест)", "шт", "2.1"),
    ("TEST-ZU", "Тестовое зарядное (тест)", "шт", "30"),
    ("TEST-PB", "Тестовый power bank (тест)", "шт", "39"),
    ("TEST-CR", "Тестовая литиевая CR (тест)", "шт", "4.1"),
]

# Демо-наполнение горячих полей + характеристик (JSONB) — чтобы карточка номенклатуры
# показывала живые блоки «Производитель», «Тех. характеристики», вес/срок, а не сплошь «нет данных».
# Это ДЕМО (товары помечены «(демо)»), не золотая запись из 1С. code → {вес, срок, attributes}.
SKU_DETAILS = {
    "AKB-60": {"weight_kg": 0.024, "shelf_life_days": 3650, "tnved_code": "8506108000", "attributes": {
        "Производитель": "GP Batteries", "Марка": "GP Ultra", "Страна происхождения": "Китай",
        "Типоразмер": "AAA / LR03", "Напряжение": "1,5 В", "Химия": "Щелочная (alkaline)",
        "Упаковка": "блистер 4 шт", "Штрихкод (EAN-13)": "4891199000041"}},
    "AKB-100": {"weight_kg": 0.023, "shelf_life_days": 3650, "tnved_code": "8506108000", "attributes": {
        "Производитель": "GP Batteries", "Марка": "GP Ultra", "Страна происхождения": "Китай",
        "Типоразмер": "AA / LR6", "Напряжение": "1,5 В", "Химия": "Щелочная (alkaline)"}},
    "TESTER-D": {"weight_kg": 0.32, "attributes": {
        "Производитель": "ООО Аккумуляторные решения", "Тип": "Цифровой тестер АКБ",
        "Диапазон напряжения": "0–30 В", "Питание": "9 В крона", "Дисплей": "ЖК"}},
    "LFP-12-100": {"weight_kg": 0.019, "shelf_life_days": 3650, "tnved_code": "8506108000", "attributes": {
        "Производитель": "Космос", "Типоразмер": "AAA / R03", "Напряжение": "1,5 В",
        "Химия": "Солевая (zinc-carbon)"}},
    "REBAR-10": {"weight_kg": 0.21, "attributes": {
        "Производитель": "Hoco", "Ёмкость": "10000 мА·ч", "Выход": "USB-A ×2, USB-C",
        "Быстрая зарядка": "PD 20 Вт", "Корпус": "алюминий"}},
    "REBAR-16": {"weight_kg": 0.003, "shelf_life_days": 3650, "tnved_code": "8506500000", "attributes": {
        "Производитель": "Panasonic", "Типоразмер": "CR2032", "Напряжение": "3 В",
        "Химия": "Литиевая (Li/MnO2)", "Ёмкость": "220 мА·ч"}},
}

# Демо-дерево групп номенклатуры (adjacency list: parent_code → код предка).
# Виды номенклатуры из боевой 1С заказчика (Аккумуляторные) — то, что видно на скринах.
# code = номер из 1С (natural key), name = наименование без номера; иерархия 2 уровня (parent_code).
# Подвиды заведены для 01/02 (раскрыты на скринах); прочие группы — папки-корни без подвидов
# (доберём подвиды списком из 1С: «Ещё → Вывести список»). Корни — parent_code=None.
CATEGORY_DEFS = [
    # code, name, parent_code
    ("01", "Щёлоч, литиев, ni-zn цилиндр и призм LR, FR", None),
    ("1.1", "Щелочные Батарейки AAA LR03", "01"),
    ("1.2", "Щелочные Батарейки AA LR6", "01"),
    ("1.3", "Щелочные Батарейки C LR14", "01"),
    ("1.4", "Щелочные Батарейки D LR20", "01"),
    ("1.5", "Щелочные 9V 6LR61, 4,5V 3LR12", "01"),
    ("1.6", "Щелочные 12V, LR1", "01"),
    ("1.7", "Сборки Щелочные", "01"),
    ("1.8", "Сборка2(про) Щелочные", "01"),
    ("1.9", "FR литиевые батарейки", "01"),
    ("1.91", "Ni-Zn AA, AAA", "01"),
    ("1.92", "Щёлоч, 4LR25", "01"),
    ("02", "Солевые батарейки цилиндрические и призматические", None),
    ("2.1", "Солевые Батарейки AAA R03", "02"),
    ("2.2", "Солевые Батарейки AA R6", "02"),
    ("2.3", "Солевые Батарейки C R14", "02"),
    ("2.4", "Солевые Батарейки D R20", "02"),
    ("2.5", "Солевые крона 9V 6F22, 4,5V", "02"),
    # Группы-папки без подвидов (на скринах закрыты) — подвиды доберём из 1С.
    ("4.1", "Литиевые батарейки специального назначения", None),
    ("26", "Для животных", None),
    ("27", "Услуги", None),
    ("28", "Корпуса для батарей, Холдер", None),
    ("30", "Зарядные устройства, блоки питания", None),
    ("31", "Зарядные станции, тестовое оборудование", None),
    ("32", "Преобразователи", None),
    ("33", "Измерительные приборы", None),
    ("34", "Дисплей", None),
    ("35", "Маркетплейс", None),
    ("36", "Двигатели, насосы", None),
    ("37", "ИБП", None),
    ("38", "Варисторы", None),
    ("39", "Power bank Внешний аккумулятор", None),
    ("40", "Тяговая техника", None),
    ("41", "Запчасти погрузчики", None),
    ("42", "Работы по тяговой технике", None),
    ("43", "Материалы ООО Аккумуляторные решения", None),
    ("44", "Квадрокоптеры", None),
]

# План счетов РБ (постановление Минфина №50) — выборка ходовых счетов: синтетика + субсчета.
# code, title, kind, parent_code
ACCOUNT_DEFS = [
    ("10", "Материалы", "актив", None),
    ("10.1", "Сырьё и материалы", "актив", "10"),
    ("41", "Товары", "актив", None),
    ("41.1", "Товары на складах", "актив", "41"),
    ("43", "Готовая продукция", "актив", None),
    ("50", "Касса", "актив", None),
    ("51", "Расчётные счета", "актив", None),
    ("52", "Валютные счета", "актив", None),
    ("60", "Расчёты с поставщиками и подрядчиками", "пассив", None),
    ("60.1", "Расчёты с поставщиками (BYN)", "пассив", "60"),
    ("60.2", "Расчёты с поставщиками (валюта)", "пассив", "60"),
    ("62", "Расчёты с покупателями и заказчиками", "активно-пассивный", None),
    ("62.1", "Расчёты с покупателями (BYN)", "активно-пассивный", "62"),
    ("68", "Расчёты по налогам и сборам", "пассив", None),
    ("68.2", "НДС", "пассив", "68"),
    ("90", "Доходы и расходы по текущей деятельности", "активно-пассивный", None),
    ("90.1", "Выручка от реализации", "пассив", "90"),
]

# Коды ТН ВЭД ЕАЭС (ЕТТ) — демо под номенклатуру (аккумуляторы/металл/провода/зарядные).
# code, name, duty_rate %, vat_code (→ ref_vat_rate), excise, unit
TNVED_DEFS = [
    ("8507100000", "Аккумуляторы свинцовые для запуска поршневых двигателей", "5.0", "НДС20", None, "шт"),
    ("8507200000", "Аккумуляторы свинцовые прочие", "5.0", "НДС20", None, "шт"),
    ("8507600000", "Аккумуляторы литий-ионные", "0.0", "НДС20", None, "шт"),
    ("8506108000", "Элементы первичные марганцево-диоксидные (щелочные/солевые)", "0.0", "НДС20", None, "шт"),
    ("8506500000", "Элементы первичные литиевые (CR2032 и т.п.)", "0.0", "НДС20", None, "шт"),
    ("8504401900", "Зарядные устройства (выпрямители) прочие", "5.0", "НДС20", None, "шт"),
    ("8504408200", "Зарядные устройства аккумуляторов", "0.0", "НДС20", None, "шт"),
    ("9030339000", "Приборы для измерения напряжения/тока (тестеры)", "0.0", "НДС20", None, "шт"),
    ("8544429009", "Провода и кабели изолированные с разъёмами прочие", "0.0", "НДС20", None, "кг"),
    ("7208519800", "Прокат плоский г/к нелегированный, толщ. >10 мм", "0.0", "НДС20", None, "кг"),
    ("7208529900", "Прокат плоский г/к нелегированный, толщ. 4.75–10 мм", "0.0", "НДС20", None, "кг"),
    ("7214200000", "Прутки/арматура для бетона, с деформациями", "0.0", "НДС20", None, "кг"),
    ("7222110000", "Прутки нержавеющие круглого сечения, г/к", "0.0", "НДС20", None, "кг"),
    ("7314310000", "Сетка сварная оцинкованная", "0.0", "НДС20", None, "кг"),
]

# Правила слияния (survivorship, M2) — чем синк из 1С НЕ имеет права затереть.
# entity_type, field, strategy, source_priority
SURVIVORSHIP_DEFS = [
    ("counterparty", "name", "source_priority", ["egr", "erp", "manual", "1c", "bitrix"]),
    ("counterparty", "unp", "source_priority", ["egr", "erp", "1c"]),
    ("counterparty", "phone", "most_recent", []),
    ("counterparty", "email", "non_empty_wins", []),
    ("sku", "title", "source_priority", ["erp", "manual", "1c"]),
    ("sku", "weight_kg", "manual_only", []),
    ("sku", "tnved_code", "manual_only", []),
]

# Регионы РБ — области + областные центры (область→город, иерархия по коду).
# code, title, kind, parent_code
REGION_DEFS = [
    ("BY-BR", "Брестская область", "область", None),
    ("BY-BR-BREST", "Брест", "город", "BY-BR"),
    ("BY-VI", "Витебская область", "область", None),
    ("BY-VI-VITEBSK", "Витебск", "город", "BY-VI"),
    ("BY-HO", "Гомельская область", "область", None),
    ("BY-HO-GOMEL", "Гомель", "город", "BY-HO"),
    ("BY-HR", "Гродненская область", "область", None),
    ("BY-HR-GRODNO", "Гродно", "город", "BY-HR"),
    ("BY-MI", "Минская область", "область", None),
    ("BY-MI-MINSK", "Минск", "город", "BY-MI"),
    ("BY-MA", "Могилёвская область", "область", None),
    ("BY-MA-MOGILEV", "Могилёв", "город", "BY-MA"),
]

# Остатки/цены по складам (StockItem — demo-зеркало 1С; владелец остатков — integrations).
# code -> (price_byn, [(warehouse, qty_available, qty_reserved, qty_forecast), ...])
STOCK_DEFS = {
    "AKB-60": (320, [("Минск (центр.)", 41, 13, 0), ("Гомель", 18, 0, 0)]),
    "AKB-100": (480, [("Минск (центр.)", 26, 6, 0), ("Брест", 9, 0, 20)]),
    "AKB-132": (560, [("Минск (центр.)", 12, 4, 0), ("Гомель", 0, 0, 30)]),
    "AKB-190": (1100, [("Минск (центр.)", 41, 13, 0), ("Гомель", 22, 5, 0)]),
    "AKB-225": (1280, [("Минск (центр.)", 8, 2, 0), ("Брест", 0, 0, 15)]),
    "LFP-12-100": (1850, [("Минск (центр.)", 14, 0, 0)]),
    "LFP-24-200": (4200, [("Минск (центр.)", 3, 1, 0), ("Гомель", 0, 0, 6)]),
    "ZU-15A": (420, [("Минск (центр.)", 30, 0, 0), ("Гомель", 12, 0, 0)]),
    "ZU-30A": (760, [("Минск (центр.)", 8, 0, 10)]),
    "TESTER-D": (180, [("Минск (центр.)", 45, 0, 0)]),
    "ROLL-3": (2150, [("Минск (центр.)", 60, 12, 0), ("Брест", 25, 0, 0)]),
    "ROLL-5": (2100, [("Минск (центр.)", 80, 20, 0), ("Гомель", 30, 0, 40)]),
    "ROLL-8": (2080, [("Минск (центр.)", 35, 5, 0)]),
    "INOX-2": (9800, [("Минск (центр.)", 6, 1, 0), ("Брест", 0, 0, 8)]),
    "REBAR-10": (1950, [("Минск (центр.)", 120, 30, 0), ("Гомель", 50, 0, 0)]),
    "REBAR-12": (1920, [("Минск (центр.)", 100, 25, 0), ("Гомель", 40, 0, 60)]),
    "REBAR-16": (1900, [("Минск (центр.)", 70, 10, 0), ("Брест", 30, 0, 0)]),
    "REBAR-20": (1890, [("Минск (центр.)", 0, 0, 50)]),
}


# Партии закупки по SKU (Batch — demo-зеркало 1С/закупок; FEFO по «годен до»).
# code -> [(lot_no, supplier, warehouse, qty, mfg_date, expiry_date, unit_landed_cost, ext_ref), ...]
# Даты подобраны под разные состояния FEFO относительно 2026-06: ok (>1 года), warn (<1 года),
# expired (в прошлом), none (без срока). Батарейки годны ~10 лет — даём близкий срок для алерта.
BATCH_DEFS = {
    "AKB-60": [
        ("LOT-CN-2401", "GP Batteries (CN)", "Минск (центр.)", 30, "2024-02-10", "2027-02-10", 231.50, "ГТД 0042/240315"),
        ("LOT-CN-2308", "GP Batteries (CN)", "Минск (центр.)", 11, "2023-08-05", "2026-08-05", 228.00, "ГТД 0117/230920"),
        ("LOT-CN-2212", "GP Batteries (CN)", "Гомель", 18, "2022-12-01", "2026-03-01", 224.40, "ГТД 0231/230110"),
    ],
    "AKB-100": [
        ("LOT-CN-2405", "GP Batteries (CN)", "Минск (центр.)", 26, "2024-05-20", "2027-05-20", 352.00, "ГТД 0061/240610"),
        ("LOT-CN-2310", "GP Batteries (CN)", "Брест", 9, "2023-10-12", "2026-10-12", 349.10, "ГТД 0150/231101"),
    ],
    "REBAR-16": [  # CR2032 — литий, годен 10 лет; партия со средним сроком
        ("LOT-PA-2403", "Panasonic (JP)", "Минск (центр.)", 70, "2024-03-01", "2034-03-01", None, "ГТД 0055/240401"),
    ],
    "TESTER-D": [  # прибор без срока годности
        ("LOT-AS-01", "ООО Аккумуляторные решения", "Минск (центр.)", 45, None, None, 168.00, None),
    ],
}


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
    # ~15 дневных показателей менеджера/РОП (регламент заказчика, [[sales-deals-real-spec]]).
    # icon/tone — из ограниченных фронт-юнионов (KpiIcon/KpiTone), чтобы mapKpi и полоса KPI
    # не падали; деньги (unit="money") форматируются в BYN на скорборде.
    D = Decimal
    return [
        KpiTarget(key="calls_key", title="Звонки ключевым клиентам", target=D("40"), unit="count", icon="phone-key", tone="blue", sort_order=1),
        KpiTarget(key="calls_all", title="Всего звонков", target=D("100"), unit="count", icon="phone", tone="indigo", sort_order=2),
        KpiTarget(key="calls_cold", title="Холодные звонки", target=D("60"), unit="count", icon="snow", tone="cyan", sort_order=3),
        KpiTarget(key="requests", title="Обработка заявок", target=D("30"), unit="count", icon="doc", tone="slate", sort_order=4),
        KpiTarget(key="new_leads", title="Новых лидов принято", target=D("25"), unit="count", icon="phone", tone="cyan", sort_order=5),
        KpiTarget(key="qualified", title="Квалифицировано лидов", target=D("15"), unit="count", icon="doc", tone="indigo", sort_order=6),
        KpiTarget(key="quotes", title="Подготовлено цен/КП", target=D("20"), unit="count", icon="doc", tone="blue", sort_order=7),
        KpiTarget(key="meetings", title="Встреч проведено", target=D("5"), unit="count", icon="doc", tone="slate", sort_order=8),
        KpiTarget(key="invoices_sent", title="Счетов отправлено", target=D("12"), unit="count", icon="doc", tone="blue", sort_order=9),
        KpiTarget(key="contracts", title="Договоров заключено", target=D("3"), unit="count", icon="doc", tone="green", sort_order=10),
        KpiTarget(key="won_count", title="Сделок выиграно", target=D("4"), unit="count", icon="doc", tone="green", sort_order=11),
        KpiTarget(key="tasks_done", title="Задач закрыто", target=D("18"), unit="count", icon="doc", tone="slate", sort_order=12),
        KpiTarget(key="ship_plan", title="План по сумме отгрузки", target=D("8000000"), unit="money", icon="ruble", tone="green", sort_order=13),
        KpiTarget(key="invoices_sum", title="Сумма выставленных счетов", target=D("3000000"), unit="money", icon="ruble", tone="green", sort_order=14),
        KpiTarget(key="won_sum", title="Сумма выигранных сделок", target=D("2000000"), unit="money", icon="ruble", tone="green", sort_order=15),
    ]


def _activities() -> list[Activity]:
    acts: list[Activity] = []
    counts = (
        ("calls_key", 24), ("calls_all", 58), ("calls_cold", 32), ("requests", 18),
        ("new_leads", 16), ("qualified", 9), ("quotes", 13), ("meetings", 3),
        ("invoices_sent", 7), ("contracts", 2), ("won_count", 3), ("tasks_done", 11),
    )
    for key, n in counts:
        acts += [Activity(kpi_key=key, owner="Иван Петров", value=Decimal("1"), date=KPI_DATE) for _ in range(n)]
    money = (
        ("ship_plan", (2_500_000, 1_700_000, 1_000_000)),
        ("invoices_sum", (1_200_000, 900_000)),
        ("won_sum", (1_100_000, 500_000)),
    )
    for key, values in money:
        acts += [Activity(kpi_key=key, owner="Иван Петров", value=Decimal(v), date=KPI_DATE) for v in values]
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


def _demo_suppliers() -> list[Supplier]:
    """Демо-поставщики: китайские, европейский и белорусские — для scorecard и RFQ."""
    return [
        Supplier(
            name="Shenzhen SunPower Co.", country="Китай", flag="🇨🇳",
            contact_person="Mr. Li Wei", phone="+86 755 8800 1234", email="sales@sz-sunpower.cn",
            payment_terms="30% предоплата / 70% по факту отгрузки", lead_time_days=45,
            incoterms="FOB", status="active",
            notes="Основной поставщик аккумуляторных ячеек. Работаем с 2022 г.",
        ),
        Supplier(
            name="Guangzhou Cells Ltd.", country="Китай", flag="🇨🇳",
            contact_person="Ms. Chen Fang", phone="+86 20 3300 5678", email="export@gz-cells.com",
            payment_terms="100% предоплата", lead_time_days=35,
            incoterms="EXW", status="active",
            notes="LiFePO4 ячейки 3.2V, хорошая цена при объёме от 1000 шт.",
        ),
        Supplier(
            name="Baltic Components GmbH", country="Германия", flag="🇩🇪",
            contact_person="Hans Müller", phone="+49 30 1234 5678", email="info@baltic-comp.de",
            payment_terms="Net 30", lead_time_days=14,
            incoterms="DAP", status="active",
            notes="Европейские компоненты для промышленных применений. Высокое качество.",
        ),
        Supplier(
            name="ООО БелтехСнаб", country="Беларусь", flag="🇧🇾",
            contact_person="Сергей Ковалёв", phone="+375 17 290-11-22", email="snab@beltechsnab.by",
            payment_terms="Оплата по выставленному счёту в течение 5 дней", lead_time_days=7,
            incoterms="EXW", status="active",
            notes="Местный поставщик расходных материалов и мелкой комплектации.",
        ),
        Supplier(
            name="ООО ТехноИмпорт", country="Беларусь", flag="🇧🇾",
            contact_person="Анна Петрова", phone="+375 29 777-88-99", email="a.petrova@technoimport.by",
            payment_terms="50% предоплата / 50% при получении", lead_time_days=21,
            incoterms="CIF", status="active",
            notes="Импортёр зарядных устройств и аксессуаров из Китая. Таможенное оформление включено.",
        ),
    ]


def _demo_rfq_and_bids(supplier_ids: dict[str, int]) -> tuple[list[Rfq], list[RfqBid]]:
    """Демо-RFQ (тендеры) с предложениями поставщиков."""
    D = Decimal
    rfqs = [
        Rfq(
            item="Ячейки LiFePO4 3.2V 100Ah",
            sku_code="LFP-24-200",
            qty=D("2000"),
            status="awarded",
            due_date=date(2026, 6, 20),
        ),
        Rfq(
            item="Зарядные устройства ЗУ-30А",
            sku_code="ZU-30A",
            qty=D("150"),
            status="open",
            due_date=date(2026, 7, 10),
        ),
        Rfq(
            item="Power bank 10000 мА·ч",
            sku_code="REBAR-10",
            qty=D("300"),
            status="cancelled",
            due_date=date(2026, 5, 30),
        ),
    ]
    # Биды добавляем позже, когда будут rfq.id
    return rfqs, []


def _demo_po_and_lines(supplier_ids: dict[str, int]) -> tuple[list[PurchaseOrder], list[PurchaseOrderLine]]:
    """Демо-заказы поставщикам с позициями: один едет (shipped), один подтверждён (ordered)."""
    D = Decimal
    po_shipped = PurchaseOrder(
        number="PO-2026-0301",
        supplier="Shenzhen SunPower Co.",
        supplier_id=supplier_ids.get("Shenzhen SunPower Co."),
        status="shipped",
        eta_date=date(2026, 7, 25),
        freight_byn=D("18500"),
        transport_method_code="container",
    )
    po_ordered = PurchaseOrder(
        number="PO-2026-0305",
        supplier="ООО ТехноИмпорт",
        supplier_id=supplier_ids.get("ООО ТехноИмпорт"),
        status="ordered",
        eta_date=date(2026, 8, 10),
        freight_byn=D("4200"),
        transport_method_code="truck",
    )
    return [po_shipped, po_ordered], []


def _demo_claims(supplier_ids: dict[str, int]) -> list[SupplierClaim]:
    """Демо-претензии: одна открытая (авто от брака), одна урегулированная (ручная)."""
    D = Decimal
    return [
        SupplierClaim(
            supplier="Shenzhen SunPower Co.",
            supplier_id=supplier_ids.get("Shenzhen SunPower Co."),
            item="Ячейки LiFePO4 3.2V",
            reason="Брак при входном контроле — вздутие корпуса у 12 шт из партии LOT-CN-2401",
            order_code="PO-2026-0288",
            claim_type="брак",
            qty_affected=12,
            amount_byn=D("43200"),
            status="open",
            source="production",
            entity_ref="production:ПЗ-2026-0184",
        ),
        SupplierClaim(
            supplier="ООО ТехноИмпорт",
            supplier_id=supplier_ids.get("ООО ТехноИмпорт"),
            item="Зарядные устройства ЗУ-30А",
            reason="Недопоставка: по накладной 150 шт, фактически получено 138 шт",
            order_code="PO-2026-0290",
            claim_type="недопоставка",
            qty_affected=12,
            amount_byn=D("9120"),
            resolution="Поставщик согласился довезти 12 шт в следующей партии или компенсировать",
            status="resolved",
            source="manual",
            entity_ref="",
        ),
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


def _wms_locations() -> list[Location]:
    """Зоны и ячейки основного склада (адресное хранение, demo)."""
    rows = [
        # warehouse, zone, code, title
        ("Минск (центр.)", "A", "A-01-01", "Стеллаж A, ряд 01, ячейка 01"),
        ("Минск (центр.)", "A", "A-01-02", "Стеллаж A, ряд 01, ячейка 02"),
        ("Минск (центр.)", "A", "A-02-01", "Стеллаж A, ряд 02, ячейка 01"),
        ("Минск (центр.)", "B", "B-01-01", "Стеллаж B, ряд 01, ячейка 01"),
        ("Минск (центр.)", "B", "B-02-01", "Стеллаж B, ряд 02, ячейка 01"),
        ("Минск (центр.)", "QC", "QC-IN", "Зона входного контроля качества"),
        ("Минск (центр.)", "RECV", "RECV-01", "Приёмная зона (буфер)"),
        ("Гомель", "A", "A-01-01", "Стеллаж A, ряд 01, ячейка 01"),
        ("Гомель", "B", "B-01-01", "Стеллаж B, ряд 01, ячейка 01"),
    ]
    return [Location(warehouse=wh, zone=zo, code=co, title=ti) for wh, zo, co, ti in rows]


def _wms_movements() -> list[StockMovement]:
    """Журнал движений WMS: приход/расход/перемещение (demo, теневой учёт)."""
    D = Decimal
    rows = [
        # sku_code, warehouse, kind, qty, reason, batch_ref, doc_ref, note
        ("AKB-60", "Минск (центр.)", "in", D("30"), "receipt", "LOT-CN-2401", "РЦ-2026-0041", "Приёмка партии из Шэньчжэня"),
        ("AKB-100", "Минск (центр.)", "in", D("26"), "receipt", "LOT-CN-2405", "РЦ-2026-0041", "Приёмка партии из Шэньчжэня"),
        ("AKB-60", "Минск (центр.)", "out", D("5"), "shipment", "", "ОТ-2026-0101", "Отгрузка АО БетаТех"),
        ("REBAR-10", "Минск (центр.)", "out", D("12"), "reserve", "", "CRM-2024-0156", "Резерв под сделку АльфаМеталл"),
        ("REBAR-10", "Минск (центр.)", "in", D("3"), "release", "", "CRM-2024-0158", "Снятие резерва ТехноСервис"),
        ("TESTER-D", "Минск (центр.)", "in", D("45"), "receipt", "LOT-AS-01", "РЦ-2026-0042", "Приход от ООО Аккумуляторные решения"),
        ("ZU-30A", "Минск (центр.)", "out", D("8"), "shipment", "", "ОТ-2026-0160", "Отгрузка ООО РегионСталь"),
    ]
    return [
        StockMovement(sku_code=sk, warehouse=wh, kind=ki, qty=q, reason=re, batch_ref=br, doc_ref=dr, note=no)
        for sk, wh, ki, q, re, br, dr, no in rows
    ]


def _wms_receipts_and_lines() -> tuple[list[Receipt], list[tuple[Receipt, list[tuple]]]]:
    """Документы приёмки с QC-строками (demo)."""
    D = Decimal
    rcpt_done = Receipt(
        number="РЦ-2026-0041",
        source="procurement",
        entity_ref="procurement:PO-2026-0301",
        warehouse="Минск (центр.)",
        status="putaway_done",
        counterparty="Shenzhen SunPower Co.",
        decided_by="Кладовщик Соколов",
    )
    lines_done = [
        # sku_code, sku_title, expected_qty, accepted_qty, rejected_qty, reject_reason, batch_ref
        ("AKB-60", "Щелочная батарейка AAA LR03 (демо)", D("30"), D("30"), D("0"), "", "LOT-CN-2401"),
        ("AKB-100", "Щелочная батарейка AA LR6 (демо)", D("26"), D("26"), D("0"), "", "LOT-CN-2405"),
        ("LFP-12-100", "Солевая батарейка AAA R03 (демо)", D("200"), D("198"), D("2"), "Повреждена упаковка", "LOT-CN-2401"),
    ]
    rcpt_qc = Receipt(
        number="РЦ-2026-0042",
        source="procurement",
        entity_ref="procurement:PO-2026-0305",
        warehouse="Минск (центр.)",
        status="pending_qc",
        counterparty="ООО ТехноИмпорт",
    )
    lines_qc = [
        ("ZU-30A", "Зарядное устройство ЗУ-30А (демо)", D("50"), None, None, "", ""),
        ("ZU-15A", "Зарядное устройство ЗУ-15А (демо)", D("80"), None, None, "", ""),
    ]
    return (
        [rcpt_done, rcpt_qc],
        [(rcpt_done, lines_done), (rcpt_qc, lines_qc)],
    )


def _wms_thresholds() -> list[StockThreshold]:
    """Пороги дефицита по ходовым SKU (demo): min_qty и рекомендуемый дозаказ."""
    D = Decimal
    rows = [
        # sku_code, warehouse, min_qty, reorder_qty
        ("AKB-60", "Минск (центр.)", D("10"), D("100")),
        ("AKB-100", "Минск (центр.)", D("10"), D("100")),
        ("REBAR-10", "Минск (центр.)", D("20"), D("200")),
        ("REBAR-12", "Минск (центр.)", D("20"), D("200")),
        ("ZU-30A", "Минск (центр.)", D("5"), D("50")),
        ("TESTER-D", "Минск (центр.)", D("5"), D("30")),
    ]
    return [StockThreshold(sku_code=sk, warehouse=wh, min_qty=mn, reorder_qty=ro) for sk, wh, mn, ro in rows]


def _wms_tasks() -> list[Task]:
    """Задачи кладовщику: put-away (размещение) и pick (подбор), demo."""
    D = Decimal
    return [
        Task(kind="putaway", status="done", sku_code="AKB-60", qty=D("30"),
             warehouse="Минск (центр.)", doc_ref="РЦ-2026-0041",
             assignee="Кладовщик Соколов", priority="high",
             note="Разместить в A-01-01 (батарейки AAA)"),
        Task(kind="putaway", status="open", sku_code="ZU-30A", qty=D("50"),
             warehouse="Минск (центр.)", doc_ref="РЦ-2026-0042",
             assignee="Кладовщик Соколов", priority="normal",
             note="Ожидает прохождения QC"),
        Task(kind="pick", status="open", sku_code="REBAR-10", qty=D("12"),
             warehouse="Минск (центр.)", doc_ref="CRM-2024-0156",
             assignee="Кладовщик Игнатов", priority="high",
             note="Подбор под сделку АльфаМеталл"),
        Task(kind="pick", status="done", sku_code="AKB-60", qty=D("5"),
             warehouse="Минск (центр.)", doc_ref="ОТ-2026-0101",
             assignee="Кладовщик Соколов", priority="normal",
             note="Отгрузка АО БетаТех — выполнено"),
    ]


def _wms_cycle_plan() -> CycleCountPlan:
    """План циклического пересчёта основного склада (ежемесячно)."""
    return CycleCountPlan(
        warehouse="Минск (центр.)",
        zone=None,
        cadence_days=30,
        next_due_date=date(2026, 7, 15),
        active=True,
        abc_class="A",
    )


def _wms_inventory_count_and_lines() -> tuple[InventoryCount, list[InventoryLine]]:
    """Демо-документ инвентаризации (проведён) с расхождениями по 3 позициям."""
    D = Decimal
    count = InventoryCount(
        number="ИНВ-2026-0003",
        warehouse="Минск (центр.)",
        status="done",
        note="Плановая инвентаризация зоны A, июнь 2026",
    )
    lines_data = [
        # sku_code, sku_title, unit, expected_qty, counted_qty, unit_cost
        ("AKB-60", "Щелочная батарейка AAA LR03 (демо)", "шт", D("41"), D("39"), D("228")),
        ("AKB-100", "Щелочная батарейка AA LR6 (демо)", "шт", D("26"), D("26"), D("349")),
        ("TESTER-D", "Тестер АКБ цифровой (демо)", "шт", D("45"), D("43"), D("168")),
    ]
    lines = [
        InventoryLine(sku_code=sk, sku_title=ti, unit=u, expected_qty=ex, counted_qty=co, unit_cost=uc)
        for sk, ti, u, ex, co, uc in lines_data
    ]
    return count, lines


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
                Unit(code="л", title="Литр"),
                Unit(code="м²", title="Квадратный метр"),
                Unit(code="м³", title="Кубический метр"),
                Unit(code="упак", title="Упаковка"),
                Unit(code="компл", title="Комплект"),
                Unit(code="пара", title="Пара"),
                Unit(code="рул", title="Рулон"),
                Unit(code="час", title="Час"),
            ])
        if (await s.execute(select(Currency))).scalars().first() is None:
            s.add_all([
                Currency(code="BYN", title="Белорусский рубль"),
                Currency(code="USD", title="Доллар США"),
                Currency(code="EUR", title="Евро"),
                Currency(code="RUB", title="Российский рубль"),
                Currency(code="CNY", title="Китайский юань"),
                Currency(code="PLN", title="Польский злотый"),
                Currency(code="UAH", title="Украинская гривна"),
                Currency(code="KZT", title="Казахстанский тенге"),
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
                CurrencyRate(currency_code="RUB", rate=Decimal("0.034"),
                             start_date=date(2026, 1, 1), end_date=None),
                CurrencyRate(currency_code="CNY", rate=Decimal("0.45"),
                             start_date=date(2026, 1, 1), end_date=None),
                CurrencyRate(currency_code="PLN", rate=Decimal("0.80"),
                             start_date=date(2026, 1, 1), end_date=None),
            ])
        if (await s.execute(select(Country))).scalars().first() is None:
            s.add_all([
                Country(code="BY", title="Беларусь"),
                Country(code="RU", title="Россия"),
                Country(code="CN", title="Китай"),
                Country(code="PL", title="Польша"),
                Country(code="UA", title="Украина"),
                Country(code="KZ", title="Казахстан"),
                Country(code="DE", title="Германия"),
                Country(code="LT", title="Литва"),
                Country(code="TR", title="Турция"),
            ])
        if (await s.execute(select(Bank))).scalars().first() is None:
            s.add_all([
                Bank(code="153001749", title="ОАО «Приорбанк»", swift="PJCBBY2X"),
                Bank(code="153001270", title="ОАО «АСБ Беларусбанк»", swift="AKBBBY2X"),
                Bank(code="153001288", title="ОАО «Белинвестбанк»", swift="BLBBBY2X"),
                Bank(code="153001601", title="ОАО «БПС-Сбербанк»", swift="BPSBBY2X"),
                Bank(code="153001895", title="ОАО «Белагропромбанк»", swift="BAPBBY2X"),
                Bank(code="153001963", title="ЗАО «Альфа-Банк»", swift="ALFABY2X"),
                Bank(code="153001361", title="ОАО «Банк БелВЭБ»", swift="BELBBY2X"),
            ])
        if (await s.execute(select(VatRate))).scalars().first() is None:
            s.add_all([
                VatRate(code="НДС20", title="НДС 20%", rate=Decimal("20.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="НДС10", title="НДС 10%", rate=Decimal("10.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="НДС0", title="Без НДС (0%)", rate=Decimal("0.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="НДС25", title="НДС 25% (услуги связи)", rate=Decimal("25.00"),
                        start_date=date(2024, 1, 1), end_date=None),
                VatRate(code="БезНДС", title="Без НДС (освобождение)", rate=Decimal("0.00"),
                        start_date=date(2024, 1, 1), end_date=None),
            ])

        # Причины отказа (классификатор sales, SALES-40) — справочник стадии «Отказ».
        if (await s.execute(select(LossReason))).scalars().first() is None:
            s.add_all([
                LossReason(code=c, title=t, sort_order=i, active=True)
                for i, (c, t) in enumerate((
                    ("price", "Дорого / не прошли по цене"),
                    ("competitor", "Ушёл к конкуренту"),
                    ("no_need", "Отпала потребность"),
                    ("no_budget", "Нет бюджета у клиента"),
                    ("no_stock", "Нет товара в наличии / сроки"),
                    ("no_response", "Клиент перестал выходить на связь"),
                    ("specs", "Не подошли характеристики / ассортимент"),
                    ("terms", "Не устроили условия оплаты/доставки"),
                    ("duplicate", "Дубль обращения"),
                    ("test", "Тестовая причина (тест)"),
                ), start=1)
            ])

        # План счетов РБ (постановление Минфина №50) — синтетика + субсчета (иерархия по коду).
        if (await s.execute(select(Account))).scalars().first() is None:
            s.add_all([Account(code=c, title=t, kind=k) for c, t, k, _p in ACCOUNT_DEFS])
            await s.flush()
        acc_by_code = {a.code: a for a in (await s.execute(select(Account))).scalars().all()}
        for code, _t, _k, parent_code in ACCOUNT_DEFS:
            acc, parent = acc_by_code.get(code), acc_by_code.get(parent_code)
            if acc and parent and acc.parent_id is None:
                acc.parent_id = parent.id

        # Регионы РБ (область→город, иерархия по коду).
        if (await s.execute(select(Region))).scalars().first() is None:
            s.add_all([Region(code=c, title=t, kind=k) for c, t, k, _p in REGION_DEFS])
            await s.flush()
        reg_by_code = {r.code: r for r in (await s.execute(select(Region))).scalars().all()}
        for code, _t, _k, parent_code in REGION_DEFS:
            reg, parent = reg_by_code.get(code), reg_by_code.get(parent_code)
            if reg and parent and reg.parent_id is None:
                reg.parent_id = parent.id

        # Коды ТН ВЭД ЕАЭС — версионные (SCD2): одна открытая версия с 2024-01-01 (демо).
        if (await s.execute(select(TnvedCode))).scalars().first() is None:
            s.add_all([
                TnvedCode(
                    code=c, name=n, duty_rate=Decimal(d), vat_code=v, excise=ex, unit=u,
                    start_date=date(2024, 1, 1), end_date=None,
                )
                for c, n, d, v, ex, u in TNVED_DEFS
            ])

        # Правила слияния (survivorship, M2) — по полю «кто побеждает» при конфликте источников.
        if (await s.execute(select(SurvivorshipRule))).scalars().first() is None:
            s.add_all([
                SurvivorshipRule(entity_type=e, field=f, strategy=st, source_priority=sp)
                for e, f, st, sp in SURVIVORSHIP_DEFS
            ])

        await s.flush()

        # Общее ядро: контрагент, пользователь, контакт
        if (await s.execute(select(Counterparty))).scalars().first() is None:
            cp = Counterparty(name="ООО Аккумулятор", unp="191234567")
            s.add(cp)
            s.add(User(username="manager", full_name="Иван Менеджеров"))
            await s.flush()
            s.add(Contact(counterparty_id=cp.id, full_name="Пётр Петров", phone="+375291234567"))

            # Тестовые контрагенты + их филиалы (пометка «(тест)»). Филиал в РБ — обособленное
            # подразделение под УНП головной организации, поэтому делим тот же УНП; связь видна
            # по имени. Контактные лица с телефонами привязаны к контрагенту/филиалу (Contact).
            # head: (name, unp, [контакты]); branches: [(имя филиала, контакты)]
            # Контакты разных отделов компании (отдел — в имени, т.к. в модели Contact его нет).
            for head_name, head_unp, head_contacts, branches in (
                ("ООО ТестТорг (тест)", "191000111",
                 [("Андрей Тестов — директор", "+375291110011"),
                  ("Марина Пробная — отдел продаж", "+375292220022"),
                  ("Анна Закупова — отдел закупок", "+375291110012"),
                  ("Виктор Счётов — бухгалтерия", "+375291110013"),
                  ("Павел Возилов — логистика", "+375291110014")],
                 [("ООО ТестТорг — филиал Гомель (тест)",
                   [("Олег Гомельский — руководитель филиала", "+375293330033"),
                    ("Нина Складская — склад", "+375293330034")]),
                  ("ООО ТестТорг — филиал Брест (тест)",
                   [("Игорь Брестский — руководитель филиала", "+375294440044")])]),
                ("ЗАО ПробаСнаб (тест)", "192000222",
                 [("Елена Снабова — отдел снабжения", "+375295550055"),
                  ("Роман Финансов — финансовый отдел", "+375295550056"),
                  ("Татьяна Кадрова — отдел кадров", "+375295550057")],
                 [("ЗАО ПробаСнаб — филиал Витебск (тест)",
                   [("Дмитрий Витебский — руководитель филиала", "+375296660066")])]),
                ("ИП Демонов (тест)", "193000333",
                 [("Сергей Демонов — владелец", "+375297770077"),
                  ("Ольга Демонова — бухгалтерия", "+375297770078")],
                 []),
            ):
                head = Counterparty(name=head_name, unp=head_unp)
                s.add(head)
                await s.flush()
                for fio, tel in head_contacts:
                    s.add(Contact(counterparty_id=head.id, full_name=fio, phone=tel,
                                  is_primary=(fio == head_contacts[0][0])))
                for br_name, br_contacts in branches:
                    br = Counterparty(name=br_name, unp=head_unp)  # филиал под УНП головной
                    s.add(br)
                    await s.flush()
                    for fio, tel in br_contacts:
                        s.add(Contact(counterparty_id=br.id, full_name=fio, phone=tel,
                                      is_primary=True))

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
        # ТН ВЭД по умолчанию на группах → товары внутри наследуют (демо M4).
        # 01 Щёлоч/литий → 8507600000 (литий-ионные); 02 Солевые → 8506 (первичные элементы).
        for code, tnved in (("01", "8507600000"), ("02", "8506108000")):
            cat = cat_by_code.get(code)
            if cat and cat.tnved_code is None:
                cat.tnved_code = tnved
        # «Общие данные группы» — свободные атрибуты (Производитель/Импортёр, упаковка, габариты)
        # по умолчанию на группе → товар без своего ключа наследует вверх по дереву (демо).
        # Тестовые SKU (TEST-AAA/2.1) пусты по этим полям → в карточке покажутся «↑ из группы».
        GROUP_ATTR_DEFAULTS = {
            "01": {"Производитель": "GP Batteries", "Импортёр": "ООО Аккумуляторные решения",
                   "Кол-во в коробке": "10 шт", "Габариты": "10,5 × 44,5 мм"},
            "02": {"Производитель": "Космос", "Импортёр": "ООО Аккумуляторные решения",
                   "Кол-во в коробке": "10 шт"},
            "39": {"Импортёр": "ООО Аккумуляторные решения", "Кол-во в коробке": "20 шт"},
        }
        for code, attrs in GROUP_ATTR_DEFAULTS.items():
            cat = cat_by_code.get(code)
            if cat and not cat.attributes:
                cat.attributes = attrs

        # Номенклатура (по коду, идемпотентно) — с привязкой к группе + демо-характеристики.
        existing_codes = set((await s.execute(select(Sku.code))).scalars().all())
        for code, title, unit, cat_code in SKU_DEFS:
            if code not in existing_codes:
                cat = cat_by_code.get(cat_code)
                d = SKU_DETAILS.get(code, {})
                s.add(Sku(
                    code=code, title=title, unit=unit,
                    category_id=cat.id if cat else None,
                    weight_kg=d.get("weight_kg"),
                    shelf_life_days=d.get("shelf_life_days"),
                    tnved_code=d.get("tnved_code"),  # свой код → переопределяет групповой
                    attributes=d.get("attributes", {}),
                ))
        await s.flush()

        # Остатки/цены по складам (StockItem — demo-зеркало 1С) для подбора товара в окне звонка.
        if (await s.execute(select(StockItem))).scalars().first() is None:
            for code, (price, whs) in STOCK_DEFS.items():
                # Себестоимость из 1С (demo): варьируемая доля цены, детерминированно по коду
                # (маржа «в наличии» = (цена − себес)/цена; см. pricing-calculation-todo).
                ratio = 0.72 + (sum(ord(c) for c in code) % 11) / 100
                cost = Decimal(str(round(price * ratio, 2)))
                for wh, av, res, fc in whs:
                    s.add(StockItem(
                        sku_code=code, warehouse=wh,
                        qty_available=Decimal(av), qty_reserved=Decimal(res),
                        qty_forecast=Decimal(fc), price=Decimal(price), cost=cost,
                    ))
            await s.flush()

        # Партии закупки (Batch — demo-зеркало 1С/закупок) для вкладки «Закупка и партии» + FEFO.
        if (await s.execute(select(Batch))).scalars().first() is None:
            for code, lots in BATCH_DEFS.items():
                for lot_no, supplier, wh, qty, mfg, exp, lc, ext in lots:
                    s.add(Batch(
                        sku_code=code, lot_no=lot_no, supplier=supplier, warehouse=wh,
                        qty=Decimal(qty),
                        mfg_date=date.fromisoformat(mfg) if mfg else None,
                        expiry_date=date.fromisoformat(exp) if exp else None,
                        unit_landed_cost=Decimal(str(lc)) if lc is not None else None,
                        external_ref=ext,
                    ))
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

        # Лиды на приёме (вход воронки: приём → квалификация → распределение).
        # Прогоняем скоринг, как на реальном интейке (events.on_intake_lead) — иначе
        # балл=0, и на доске не видно ни «целевой», ни экспресс-передачи, ни ключевых.
        if (await s.execute(select(Lead))).scalars().first() is None:
            from modules.leads.leads import apply_initial_score

            demo_leads = _demo_leads()
            s.add_all(demo_leads)
            await s.flush()
            for _lead in demo_leads:
                await apply_initial_score(_lead, s)

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

        # Поставщики procurement (идемпотентно по имени)
        existing_suppliers = {
            r.name: r.id
            for r in (await s.execute(select(Supplier))).scalars().all()
        }
        if not existing_suppliers:
            for sup in _demo_suppliers():
                s.add(sup)
            await s.flush()
            existing_suppliers = {
                r.name: r.id
                for r in (await s.execute(select(Supplier))).scalars().all()
            }
            print(f"seed: поставщики — {len(existing_suppliers)} записей")

        # RFQ (тендеры) — идемпотентно (только если таблица пуста)
        if (await s.execute(select(Rfq))).scalars().first() is None:
            rfqs, _ = _demo_rfq_and_bids(existing_suppliers)
            s.add_all(rfqs)
            await s.flush()
            # Биды на первый (awarded) и второй (open) RFQ
            all_rfqs = (await s.execute(select(Rfq))).scalars().all()
            rfq_by_sku = {r.sku_code: r for r in all_rfqs}
            D = Decimal
            awarded_rfq = rfq_by_sku.get("LFP-24-200")
            open_rfq = rfq_by_sku.get("ZU-30A")
            if awarded_rfq:
                bid_gz = RfqBid(
                    rfq_id=awarded_rfq.id,
                    supplier_id=existing_suppliers.get("Guangzhou Cells Ltd."),
                    price_byn=D("1550"),
                    lead_time_days=35,
                    incoterms="EXW",
                    note="Лучшая цена при объёме 2000+ шт. Отгрузка со склада Гуанчжоу.",
                    is_winner=True,
                )
                bid_sz = RfqBid(
                    rfq_id=awarded_rfq.id,
                    supplier_id=existing_suppliers.get("Shenzhen SunPower Co."),
                    price_byn=D("1680"),
                    lead_time_days=45,
                    incoterms="FOB",
                    note="Стабильный поставщик, но цена выше на 8%.",
                    is_winner=False,
                )
                s.add_all([bid_gz, bid_sz])
            if open_rfq:
                bid_ti = RfqBid(
                    rfq_id=open_rfq.id,
                    supplier_id=existing_suppliers.get("ООО ТехноИмпорт"),
                    price_byn=D("760"),
                    lead_time_days=21,
                    incoterms="CIF",
                    note="Включено таможенное оформление.",
                    is_winner=False,
                )
                s.add(bid_ti)
            print("seed: RFQ + биды добавлены")

        # PO (заказы) с позициями — идемпотентно (только если таблица пуста)
        if (await s.execute(select(PurchaseOrder))).scalars().first() is None:
            orders, _ = _demo_po_and_lines(existing_suppliers)
            s.add_all(orders)
            await s.flush()
            all_orders = (await s.execute(select(PurchaseOrder))).scalars().all()
            po_by_number = {o.number: o for o in all_orders}
            D = Decimal
            # Позиции shipped-заказа (партия батареек из Шэньчжэня)
            po301 = po_by_number.get("PO-2026-0301")
            if po301:
                s.add_all([
                    PurchaseOrderLine(
                        order_id=po301.id, sku_code="AKB-60",
                        qty=D("500"), goods_value_byn=D("115750"), weight=D("12.0"), volume=D("0.0480"),
                    ),
                    PurchaseOrderLine(
                        order_id=po301.id, sku_code="AKB-100",
                        qty=D("300"), goods_value_byn=D("105600"), weight=D("6.9"), volume=D("0.0288"),
                    ),
                    PurchaseOrderLine(
                        order_id=po301.id, sku_code="LFP-12-100",
                        qty=D("200"), goods_value_byn=D("37000"), weight=D("3.8"), volume=D("0.0140"),
                    ),
                ])
            # Позиции ordered-заказа (зарядные от белорусского импортёра)
            po305 = po_by_number.get("PO-2026-0305")
            if po305:
                s.add_all([
                    PurchaseOrderLine(
                        order_id=po305.id, sku_code="ZU-30A",
                        qty=D("50"), goods_value_byn=D("38000"), weight=D("40.0"), volume=D("0.2500"),
                    ),
                    PurchaseOrderLine(
                        order_id=po305.id, sku_code="ZU-15A",
                        qty=D("80"), goods_value_byn=D("33600"), weight=D("48.0"), volume=D("0.3200"),
                    ),
                ])
            print("seed: заказы PO + позиции добавлены")

        # Претензии — идемпотентно (только если таблица пуста)
        if (await s.execute(select(SupplierClaim))).scalars().first() is None:
            s.add_all(_demo_claims(existing_suppliers))
            print("seed: претензии поставщикам добавлены")

        # ── Логистика ──────────────────────────────────────────────────────────
        # Перевозчики (Carrier) — идемпотентно по code
        existing_carrier_codes = {
            c.code
            for c in (await s.execute(select(Carrier))).scalars().all()
            if c.code
        }
        if not existing_carrier_codes:
            for item in CARRIERS_RB:
                s.add(
                    Carrier(
                        name=item["name"],
                        code=item["code"],
                        kind=item["kind"],
                        mode=item["mode"],
                        integration=item["integration"],
                        track_url=item["track_url"],
                    )
                )
            # «Свой транспорт» — внутренний перевозчик без track_url
            s.add(
                Carrier(
                    name="Свой транспорт",
                    code="own",
                    kind="РБ",
                    mode="авто",
                    integration="manual",
                    track_url="",
                )
            )
            await s.flush()
            existing_carrier_codes = {
                c.code
                for c in (await s.execute(select(Carrier))).scalars().all()
                if c.code
            }
            print(f"seed: логистика — перевозчики: {len(existing_carrier_codes)}")

        # Зоны доставки (Zone) — идемпотентно по code
        if (await s.execute(select(Zone))).scalars().first() is None:
            for z in logistics_seeds.ZONES_SEED:
                s.add(Zone(**z))
            await s.flush()
            print("seed: логистика — зоны добавлены")

        # Тарифная матрица (CarrierTariff) — идемпотентно (пустая таблица)
        if (await s.execute(select(CarrierTariff))).scalars().first() is None:
            for t in logistics_seeds.TARIFFS_SEED:
                s.add(CarrierTariff(**t))
            await s.flush()
            print(f"seed: логистика — тарифы: {len(logistics_seeds.TARIFFS_SEED)}")

        # Scorecard перевозчиков — идемпотентно (пустая таблица)
        if (await s.execute(select(CarrierScorecard))).scalars().first() is None:
            for sc in logistics_seeds.SCORECARD_SEED:
                s.add(CarrierScorecard(**sc))
            await s.flush()
            print("seed: логистика — scorecard добавлен")

        # Аудит счетов (FreightAuditLog) — идемпотентно (пустая таблица)
        if (await s.execute(select(FreightAuditLog))).scalars().first() is None:
            for a in logistics_seeds.AUDIT_SEED:
                s.add(FreightAuditLog(**a))
            await s.flush()
            print("seed: логистика — аудит счетов добавлен")

        # Парк машин (CarrierVehicle) — идемпотентно (пустая таблица)
        if (await s.execute(select(CarrierVehicle))).scalars().first() is None:
            for v in logistics_seeds.VEHICLES_SEED:
                s.add(CarrierVehicle(**v))
            await s.flush()
            print(f"seed: логистика — транспорт: {len(logistics_seeds.VEHICLES_SEED)}")

        # Допуски по категориям груза (CarrierCargoCapability) — идемпотентно
        if (await s.execute(select(CarrierCargoCapability))).scalars().first() is None:
            for cap in logistics_seeds.CAPABILITIES_SEED:
                s.add(CarrierCargoCapability(**cap))
            await s.flush()
            print("seed: логистика — допуски грузов добавлены")

        # Доставки по РБ/РФ (Shipment) — демо-воронка (4 статуса)
        if (await s.execute(select(Shipment))).scalars().first() is None:
            D = Decimal
            s.add_all(
                [
                    Shipment(
                        number="ЛОГ-2026-0051",
                        customer="ООО МеталлПром",
                        address="г. Гомель, ул. Советская, 12",
                        route_from="Минск",
                        route_to="Гомель",
                        carrier="Автолайт Экспресс",
                        carrier_code="autolight",
                        carrier_order_no="AL-88421",
                        cargo="Металлопрокат лист 5 мм · 12 паллет",
                        weight_kg=D("3840"),
                        amount=D("210"),
                        payer="компания",
                        priority="Высокий",
                        owner="Иванов И.И.",
                        status="in_transit",
                        eta="14.06",
                        tracking_no="AL-2026-88421",
                        tracking_status="В пути · Бобруйск",
                    ),
                    Shipment(
                        number="ЛОГ-2026-0055",
                        customer="АО СтройКомплект",
                        address="г. Минск, пр. Независимости, 58",
                        route_from="Минск",
                        route_to="Минск",
                        carrier="DPD",
                        carrier_code="dpd",
                        carrier_order_no="DPD-9901234",
                        cargo="Комплектующие · 3 коробки",
                        weight_kg=D("24"),
                        amount=D("14"),
                        payer="клиент",
                        priority="Средний",
                        owner="Петров П.П.",
                        status="assigned",
                        eta="13.06",
                        tracking_no="DPD-9901234",
                        tracking_status="Принято к доставке",
                    ),
                    Shipment(
                        number="ЛОГ-2026-0048",
                        customer="ПАО ХимПром",
                        address="г. Брест, ул. Ленина, 5",
                        route_from="Минск",
                        route_to="Брест",
                        carrier="СДЭК",
                        carrier_code="cdek",
                        carrier_order_no="CDEK-77001",
                        cargo="Аккумуляторные ячейки LiFePO4 · 8 ящиков",
                        weight_kg=D("96"),
                        amount=D("31"),
                        payer="компания",
                        priority="Средний",
                        owner="Сидоров С.С.",
                        status="delivered",
                        eta="10.06",
                        tracking_no="CDEK-77001",
                        tracking_status="Доставлено",
                    ),
                    Shipment(
                        number="ЛОГ-2026-0060",
                        customer="ООО РегионСталь",
                        address="г. Витебск, ул. Замковая, 3",
                        route_from="Минск",
                        route_to="Витебск",
                        carrier="Европочта",
                        carrier_code="evropochta",
                        cargo="Power bank 10000 · 20 шт",
                        weight_kg=D("4.2"),
                        amount=D("8.50"),
                        payer="клиент",
                        priority="Низкий",
                        owner="Иванов И.И.",
                        status="planned",
                        eta="16.06",
                    ),
                ]
            )
            await s.flush()
            print("seed: логистика — доставки РБ/РФ добавлены")

        # Импорт из Китая (ImportShipment) — демо-воронка (3 стадии)
        if (await s.execute(select(ImportShipment))).scalars().first() is None:
            D = Decimal
            s.add_all(
                [
                    ImportShipment(
                        number="ИМП-2026-0041",
                        supplier="Shenzhen SunPower Co.",
                        flag="🇨🇳",
                        container_no="TEMU2345678",
                        route="Шэньчжэнь → Брест (ж/д) → Минск",
                        incoterms="FOB",
                        mode="море+ж/д",
                        cargo="АКБ LiFePO4 ячейки 3.2V · 2000 шт",
                        qty=2000,
                        amount=D("18500"),
                        priority="Высокий",
                        owner="Иванов И.И.",
                        stage="in_transit",
                        eta="25.07",
                        po_ref="PO-2026-0301",
                        insight="Контейнер в пути — 22 дня до Бреста",
                    ),
                    ImportShipment(
                        number="ИМП-2026-0038",
                        supplier="Guangzhou Cells Ltd.",
                        flag="🇨🇳",
                        container_no="MSCU8812001",
                        route="Гуанчжоу → Гамбург → Брест",
                        incoterms="EXW",
                        mode="море",
                        cargo="LiFePO4 ячейки партия 12 · 2000 шт",
                        qty=2000,
                        amount=D("16200"),
                        priority="Высокий",
                        owner="Сидоров С.С.",
                        stage="customs",
                        customs_status="Таможенное оформление в Бресте",
                        eta="12.06",
                        po_ref="PO-2026-0289",
                        insight="Таможня — оплата пошлины 5% → выпуск сегодня",
                    ),
                    ImportShipment(
                        number="ИМП-2026-0044",
                        supplier="ООО ТехноИмпорт",
                        flag="🇧🇾",
                        container_no="",
                        route="Минск → (авто)",
                        incoterms="CIF",
                        mode="авто",
                        cargo="Зарядные устройства ЗУ-30А · 50 шт",
                        qty=50,
                        amount=D("4200"),
                        priority="Средний",
                        owner="Петров П.П.",
                        stage="warehouse",
                        customs_status="",
                        eta="10.06",
                        po_ref="PO-2026-0305",
                        insight="Принято на склад, идёт приёмочный контроль",
                    ),
                ]
            )
            await s.flush()
            print("seed: логистика — импорт из Китая добавлен")

        # Тендер на перевозку (CarrierRfq + приглашения + ставки)
        if (await s.execute(select(CarrierRfq))).scalars().first() is None:
            D = Decimal
            rfq_data = logistics_seeds.RFQ_DEMO.copy()
            rfq_data["weight_kg"] = D(str(rfq_data["weight_kg"]))
            rfq_data["declared_value"] = D(str(rfq_data["declared_value"]))
            rfq = CarrierRfq(**rfq_data)
            s.add(rfq)
            await s.flush()
            for carrier_code in logistics_seeds.RFQ_DEMO_INVITES:
                s.add(
                    CarrierRfqInvite(
                        rfq_id=rfq.id,
                        carrier_code=carrier_code,
                        channel="manual",
                        status="responded",
                    )
                )
            await s.flush()
            for bid in logistics_seeds.RFQ_DEMO_BIDS:
                s.add(
                    CarrierBid(
                        rfq_id=rfq.id,
                        carrier_code=bid["carrier_code"],
                        price=D(str(bid["price"])),
                        eta_days=bid["eta_days"],
                        vehicle_class=bid["vehicle_class"],
                        comment=bid["comment"],
                        round=1,
                    )
                )
            await s.flush()
            print("seed: логистика — тендер + ставки добавлены")
        # ── /Логистика ─────────────────────────────────────────────────────────

        # ── WMS: ячейки, движения, приёмки, пороги, задачи, план пересчёта, инвентаризация ──

        # Ячейки/зоны (Location) — идемпотентно по (code, warehouse)
        existing_loc_codes = set(
            (await s.execute(select(Location.code, Location.warehouse))).all()
        )
        new_locs = [
            loc for loc in _wms_locations()
            if (loc.code, loc.warehouse) not in existing_loc_codes
        ]
        if new_locs:
            s.add_all(new_locs)
            await s.flush()
            print(f"seed: WMS locations — {len(new_locs)} записей")

        # Движения склада (StockMovement) — идемпотентно: пропускаем если уже есть
        if (await s.execute(select(StockMovement))).scalars().first() is None:
            s.add_all(_wms_movements())
            print("seed: WMS движения добавлены")

        # Приёмки (Receipt) + строки (ReceiptLine) — идемпотентно по номеру
        existing_rcpt_nums = set(
            (await s.execute(select(Receipt.number))).scalars().all()
        )
        receipts_list, receipts_lines_pairs = _wms_receipts_and_lines()
        new_receipts = [r for r in receipts_list if r.number not in existing_rcpt_nums]
        if new_receipts:
            new_nums = {r.number for r in new_receipts}
            s.add_all(new_receipts)
            await s.flush()
            rcpt_by_num = {r.number: r for r in new_receipts}
            for rcpt, lines_data in receipts_lines_pairs:
                if rcpt.number not in new_nums:
                    continue
                for sk, ti, ex, ac, rj, rr, br in lines_data:
                    s.add(ReceiptLine(
                        receipt_id=rcpt_by_num[rcpt.number].id,
                        sku_code=sk,
                        sku_title=ti,
                        expected_qty=ex,
                        accepted_qty=ac,
                        rejected_qty=rj,
                        reject_reason=rr,
                        batch_ref=br,
                    ))
            print(f"seed: WMS приёмки — {len(new_receipts)} документа")

        # Пороги дефицита (StockThreshold) — идемпотентно по (sku_code, warehouse)
        existing_thr = set(
            (await s.execute(select(StockThreshold.sku_code, StockThreshold.warehouse))).all()
        )
        new_thr = [t for t in _wms_thresholds() if (t.sku_code, t.warehouse) not in existing_thr]
        if new_thr:
            s.add_all(new_thr)
            print(f"seed: WMS пороги дефицита — {len(new_thr)} записей")

        # Задачи кладовщика (Task) — идемпотентно: пропускаем если уже есть
        if (await s.execute(select(Task))).scalars().first() is None:
            s.add_all(_wms_tasks())
            print("seed: WMS задачи добавлены")

        # План цикл-пересчёта (CycleCountPlan) — один план на основной склад
        if (await s.execute(select(CycleCountPlan))).scalars().first() is None:
            s.add(_wms_cycle_plan())
            print("seed: WMS план цикл-пересчёта добавлен")

        # Инвентаризация (InventoryCount + InventoryLine) — идемпотентно по номеру
        existing_inv = set((await s.execute(select(InventoryCount.number))).scalars().all())
        if "ИНВ-2026-0003" not in existing_inv:
            inv_count, inv_lines = _wms_inventory_count_and_lines()
            s.add(inv_count)
            await s.flush()
            for line in inv_lines:
                line.count_id = inv_count.id
                s.add(line)
            print("seed: WMS инвентаризация добавлена")

        await s.commit()
        print("seed: готово")

    await services.db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
