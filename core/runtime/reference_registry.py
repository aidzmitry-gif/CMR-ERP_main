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
            ReferenceColumn("attributes", "Характеристики", "json", semantic="переменные атрибуты (JSONB)"),
        ),
        permissions=("refs.view", "refs.edit"),
        ai_exposed=True,
        description="Номенклатура (товарные позиции) + характеристики.",
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
)


def register_system_references(core: Core) -> None:
    """Зарегистрировать системные справочники ядра от имени владельца ``core``.

    Идёт публичным путём ``Core.register_owned_reference`` — без приватного ``_current``
    и без добавления ``core`` в ``loaded_modules``.
    """
    for reference in SYSTEM_REFERENCES:
        core.register_owned_reference("core", reference)
