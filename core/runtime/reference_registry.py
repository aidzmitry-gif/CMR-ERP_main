"""Регистрация системных справочников ядром в реестре-витрине «Справочники».

Ядро владеет общесистемными справочниками (единицы, валюты+курсы, страны, банки,
НДС) и общими мастер-данными (контрагенты, контакты, номенклатура, сотрудники) в
схеме ``public``. Здесь они регистрируются тем же контрактом ``core.register_reference``,
что и модульные классификаторы, — данные остаются у владельца, реестр хранит метаданные
для UI, прав (RBAC) и каталога AI.

Импорт ``core.domain.reference`` ниже нужен и ради side-effect: ORM-модели попадают в
``Base.metadata`` (dev на SQLite поднимает их через ``create_all``).
"""
from __future__ import annotations

from core.domain import reference as _reference_models  # noqa: F401  (регистрация таблиц)
from core.runtime.contract import Reference, ReferenceColumn
from core.runtime.core import Core

# --- частые колонки ---
_CODE = ReferenceColumn(
    "code", "Код", "string", editable=False, semantic="стабильный код для мягких ссылок"
)
_TITLE = ReferenceColumn("title", "Наименование", "string")
_ACTIVE = ReferenceColumn(
    "is_active", "Активен", "bool", semantic="архивные записи не выбираются в новых документах"
)


def _versioned_cols(value_label: str) -> tuple[ReferenceColumn, ...]:
    return (
        _CODE,
        ReferenceColumn("rate", value_label, "number", semantic="значение, действующее в периоде"),
        ReferenceColumn(
            "start_date", "Действует с", "date", semantic="начало периода (включительно)"
        ),
        ReferenceColumn(
            "end_date", "По", "date", semantic="конец периода (исключительно); пусто = текущая"
        ),
    )


# Справочники, которыми владеет ядро (схема public).
SYSTEM_REFERENCES: tuple[Reference, ...] = (
    # --- reference data (§3.1) ---
    Reference(
        key="core.units",
        title="Единицы измерения",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/units",
        columns=(_CODE, _TITLE, _ACTIVE),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Единицы измерения номенклатуры (шт, кг, м).",
    ),
    Reference(
        key="core.currencies",
        title="Валюты",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/currencies",
        columns=(_CODE, _TITLE, _ACTIVE),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Валюты (ISO-коды): BYN, USD, EUR.",
    ),
    Reference(
        key="core.currency_rates",
        title="Курсы валют",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/currency-rates",
        columns=_versioned_cols("Курс к BYN"),
        permissions=("refs.view", "refs.edit"),
        versioned=True,
        ai_exposed=True,
        description="Историчный курс валюты к BYN; документ видит курс на свою дату (SCD2).",
    ),
    Reference(
        key="core.countries",
        title="Страны",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/countries",
        columns=(_CODE, _TITLE, _ACTIVE),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Страны (ISO-коды).",
    ),
    Reference(
        key="core.banks",
        title="Банки",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/banks",
        columns=(
            _CODE,
            _TITLE,
            ReferenceColumn("swift", "SWIFT", "string"),
            _ACTIVE,
        ),
        permissions=("refs.view", "refs.edit"),
        description="Банки (БИК/SWIFT) для реквизитов.",
    ),
    Reference(
        key="core.vat_rates",
        title="Ставки НДС",
        department="Система",
        owner_schema="public",
        endpoint="/system/refs/vat-rates",
        columns=_versioned_cols("Ставка, %"),
        permissions=("refs.view", "refs.edit"),
        versioned=True,
        ai_exposed=True,
        description="Историчная ставка НДС; документ видит ставку на свою дату (SCD2).",
    ),
    # --- master data (§3.2) ---
    Reference(
        key="core.counterparties",
        title="Контрагенты",
        department="Общие",
        owner_schema="public",
        endpoint="/refs/counterparties",
        columns=(
            _CODE,
            _TITLE,
            ReferenceColumn("unp", "УНП", "string", semantic="налоговый № (natural key, РБ)"),
            _ACTIVE,
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Единая эталонная запись контрагента (golden record): клиенты, поставщики, перевозчики.",
    ),
    Reference(
        key="core.contacts",
        title="Контакты",
        department="Общие",
        owner_schema="public",
        endpoint="/refs/contacts",
        columns=(_TITLE, ReferenceColumn("phone", "Телефон", "string"), ReferenceColumn("email", "E-mail", "string")),
        permissions=("refs.view", "refs.edit"),
        description="Контактные лица контрагентов.",
    ),
    Reference(
        key="core.skus",
        title="Номенклатура",
        department="Общие",
        owner_schema="public",
        endpoint="/refs/skus",
        columns=(
            _CODE,
            _TITLE,
            ReferenceColumn("unit", "Ед.", "string"),
            ReferenceColumn(
                "category_id", "Группа", "number",
                semantic="ссылка на группу номенклатуры (core.nomenclature_groups)",
            ),
            ReferenceColumn("attributes", "Характеристики", "json", semantic="переменные атрибуты (JSONB)"),
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Номенклатура (товарные позиции) + характеристики.",
    ),
    Reference(
        key="core.sku_history",
        title="История номенклатуры",
        department="Общие",
        owner_schema="public",
        endpoint="/system/refs/sku-history",
        columns=(
            ReferenceColumn(
                "sku_code", "Код товара", "string", editable=False,
                semantic="natural key номенклатуры (core.skus)",
            ),
            _TITLE,
            ReferenceColumn("unit", "Ед.", "string"),
            ReferenceColumn(
                "category_id", "Группа", "number",
                semantic="группа номенклатуры на дату версии (core.nomenclature_groups)",
            ),
            ReferenceColumn("weight_kg", "Вес, кг", "number"),
            ReferenceColumn("volume_m3", "Объём, м³", "number"),
            ReferenceColumn("tnved_code", "ТН ВЭД", "string", semantic="код ТН ВЭД на дату версии"),
            ReferenceColumn("vat_code", "НДС-код", "string", semantic="свой код НДС на дату версии"),
            ReferenceColumn("shelf_life_days", "Срок годн., дн.", "number"),
            ReferenceColumn("start_date", "Действует с", "date"),
            ReferenceColumn("end_date", "По", "date", semantic="пусто = текущая версия"),
        ),
        permissions=("refs.view", "refs.edit"),
        versioned=True,
        ai_exposed=True,
        description="Датированные версии мастер-характеристик номенклатуры (SCD2): документ "
        "«на дату» видит характеристики, действовавшие тогда. Только мастер-данные "
        "(цена/остаток = операционные, истина 1С — не здесь).",
    ),
    Reference(
        key="core.nomenclature_groups",
        title="Группы номенклатуры",
        department="Общие",
        owner_schema="public",
        endpoint="/system/refs/nomenclature-groups",
        columns=(
            _CODE,
            ReferenceColumn("name", "Наименование", "string"),
            ReferenceColumn(
                "parent_id", "Родитель", "number",
                semantic="родительская группа (иерархия adjacency list); пусто = корень",
            ),
            ReferenceColumn(
                "tnved_code", "ТН ВЭД по умолч.", "string",
                semantic="код ТН ВЭД группы (core.tnved); товар без своего наследует его",
            ),
            _ACTIVE,
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Иерархия групп (категорий) номенклатуры: parent_id (adjacency list), "
        "производный ltree-путь на Postgres. На группу ссылается core.skus.",
    ),
    Reference(
        key="core.employees",
        title="Сотрудники",
        department="Общие",
        owner_schema="public",
        endpoint="/refs/employees",
        columns=(
            ReferenceColumn("username", "Логин", "string", editable=False),
            ReferenceColumn("full_name", "ФИО", "string"),
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Сотрудники/пользователи (мастер-данные); кадровая карточка — в модуле hr.",
    ),
    # --- классификаторы (§3.1) ---
    Reference(
        key="core.tnved",
        title="Коды ТН ВЭД (тарифы)",
        department="Финансы",
        owner_schema="public",
        endpoint="/system/refs/tnved",
        columns=(
            _CODE,
            ReferenceColumn("name", "Описание", "string"),
            ReferenceColumn(
                "duty_rate", "Пошлина, %", "number",
                semantic="ввозная пошлина ЕТТ ЕАЭС, действует в периоде",
            ),
            ReferenceColumn(
                "vat_code", "НДС", "string", semantic="ссылка на ставку НДС (core.vat_rates)",
            ),
            ReferenceColumn("excise", "Акциз", "string"),
            ReferenceColumn("unit", "Ед. (там.)", "string"),
            ReferenceColumn("start_date", "Действует с", "date"),
            ReferenceColumn("end_date", "По", "date", semantic="пусто = текущая"),
        ),
        permissions=("refs.view", "refs.edit"),
        versioned=True,
        ai_exposed=True,
        description="Коды ТН ВЭД ЕАЭС (ЕТТ) с ввозной пошлиной + акциз; НДС ссылкой на core.vat_rates. "
        "Историчны (SCD2): расчёт landed cost берёт ставку на дату оформления.",
    ),
    Reference(
        key="core.accounts",
        title="План счетов",
        department="Финансы",
        owner_schema="public",
        endpoint="/system/refs/accounts",
        columns=(
            _CODE,
            _TITLE,
            ReferenceColumn("kind", "Тип", "string", semantic="актив/пассив/активно-пассивный"),
            ReferenceColumn(
                "parent_id", "Синтетический счёт", "number",
                semantic="родительский счёт (синтетика); пусто = корень",
            ),
            ReferenceColumn(
                "effective_from", "Введён с", "date",
                semantic="дата ввода счёта в оборот; пусто = бессрочно",
            ),
            ReferenceColumn(
                "effective_to", "Выведен с", "date",
                semantic="дата вывода из оборота (искл.); пусто = в силе",
            ),
            _ACTIVE,
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="План счетов бухучёта РБ (постановление Минфина №50): синтетика + субсчета "
        "(иерархия parent_id), датированный ввод/вывод из оборота. Для проводок финмодуля.",
    ),
    Reference(
        key="core.regions",
        title="Регионы и города",
        department="Общие",
        owner_schema="public",
        endpoint="/system/refs/regions",
        columns=(
            _CODE,
            _TITLE,
            ReferenceColumn("kind", "Уровень", "string", semantic="область/район/город"),
            ReferenceColumn(
                "parent_id", "Входит в", "number",
                semantic="родительский регион (область→район→город); пусто = корень",
            ),
            ReferenceColumn(
                "effective_from", "Введён с", "date",
                semantic="дата ввода региона в оборот; пусто = бессрочно",
            ),
            ReferenceColumn(
                "effective_to", "Выведен с", "date",
                semantic="дата вывода из оборота (искл.); пусто = в силе",
            ),
            _ACTIVE,
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Гео-справочник РБ (область→район→город, иерархия parent_id), датированный "
        "ввод/вывод из оборота: адреса контрагентов и территориальная аналитика (territory).",
    ),
)


def register_system_references(core: Core) -> None:
    """Зарегистрировать системные справочники ядра от имени владельца ``core``.

    Идёт публичным путём ``Core.register_owned_reference`` — без приватного ``_current``
    и без добавления ``core`` в ``loaded_modules``.
    """
    for reference in SYSTEM_REFERENCES:
        core.register_owned_reference("core", reference)
