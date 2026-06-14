# Контракт `register_reference` + shared-kernel reference-data — спецификация к вживлению

> Готовая к сборке спека под фактический код ядра (сверено: `core/runtime/contract.py`,
> `core/runtime/core.py`, `core/CLAUDE.md`). Не трогает живые модули — добавляет один
> dataclass в контракт, один метод в `Core`, один системный роут и набор ORM-таблиц в public.
> База решения: `coordination/spravochniki-mdm-research.md`.

## Зачем
Один контракт регистрации справочника закрывает три цели сразу:
1. **UI** вкладки «Справочники» (дерево по отделам + универсальная таблица).
2. **RBAC** — права на каждый справочник через access-admin.
3. **Каталог для AI** — машинно-читаемый список «что есть и как точно запросить» (semantic layer без эмбеддингов).

Данные остаются у владельца (модуль или public). Реестр — витрина, НЕ второе хранилище.

---

## 1. Контракт: `core/runtime/contract.py` (+ добавить)

```python
@dataclass(frozen=True)
class ReferenceColumn:
    """Колонка справочника для универсальной таблицы и каталога AI."""
    name: str                       # машинное имя поля (code, title, rate, ...)
    label: str                      # подпись по умолчанию (RU)
    type: str = "string"            # string|number|bool|date|enum|ref
    label_i18n: dict[str, str] | None = None   # {"en": "...", "by": "..."}
    editable: bool = True
    semantic: str = ""              # описание для AI: что значит поле


@dataclass(frozen=True)
class Reference:
    """Справочник, регистрируемый модулем (или ядром) в реестре-витрине.

    Метаданные; сами данные живут у владельца (owner_schema) и читаются по endpoint.
    """
    key: str                        # уникальный ключ: "sales.reject_reasons"
    title: str                      # "Причины отказа"
    department: str                 # группа в дереве: "Продажи" | "Склад" | "Система"
    owner_schema: str               # схема-владелец: "sales" | "public"
    endpoint: str                   # CRUD-эндпоинт: "/sales/refs/reject-reasons"
    columns: tuple[ReferenceColumn, ...] = ()
    permissions: tuple[str, ...] = ()      # RBAC-коды: ("sales.refs.view", "sales.refs.edit")
    archivable: bool = True         # архив вместо жёсткого удаления
    versioned: bool = False         # True → историчность SCD2 (effective-dated)
    ai_exposed: bool = False        # попадает в каталог для AI-агента
    description: str = ""           # человекочитаемое назначение
```

## 2. Фасад: `core/runtime/core.py` (+ добавить)

```python
# в импортах:
from core.runtime.contract import Permission, Role, TelegramCommand, Widget, Reference

@dataclass
class RegisteredReference:
    module: str
    reference: Reference

# в Core.__init__:
        self.references: list[RegisteredReference] = []

# метод (рядом с register_widget):
    def register_reference(self, reference: Reference) -> None:
        """Зарегистрировать справочник в реестре-витрине «Справочники».

        Данные остаются у владельца; реестр хранит только метаданные для UI,
        прав и каталога AI. Атрибутируется модулю автоматически (self._module).
        """
        self.references.append(RegisteredReference(self._module, reference))
```

## 3. Системный роут-каталог: `core/runtime/system_routes.py` (+ добавить)

Витрина для UI и каталог для AI читают один и тот же реестр.

```python
@router.get("/references")
async def list_references(core: Core = Depends(get_core)) -> dict:
    """Каталог справочников, сгруппированный по отделам (для вкладки и для AI)."""
    by_dept: dict[str, list[dict]] = {}
    for rr in core.references:
        r = rr.reference
        by_dept.setdefault(r.department, []).append({
            "key": r.key, "title": r.title, "module": rr.module,
            "endpoint": r.endpoint, "owner_schema": r.owner_schema,
            "columns": [c.__dict__ for c in r.columns],
            "permissions": list(r.permissions),
            "archivable": r.archivable, "versioned": r.versioned,
            "ai_exposed": r.ai_exposed, "description": r.description,
        })
    return {"departments": by_dept}

@router.get("/references/ai-catalog")
async def ai_catalog(core: Core = Depends(get_core)) -> dict:
    """Узкий каталог только ai_exposed — машинный «что есть и как запросить»."""
    return {"references": [
        {"key": r.reference.key, "title": r.reference.title,
         "endpoint": r.reference.endpoint, "owner_schema": r.reference.owner_schema,
         "columns": [{"name": c.name, "type": c.type, "semantic": c.semantic}
                     for c in r.reference.columns],
         "description": r.reference.description}
        for r in core.references if r.reference.ai_exposed]}
```

## 4. Пример использования (модуль sales, внутри `register()`)

```python
core.declare_permissions([
    Permission("sales.refs.view", "Просмотр справочников продаж"),
    Permission("sales.refs.edit", "Правка справочников продаж"),
])
core.register_reference(Reference(
    key="sales.reject_reasons",
    title="Причины отказа",
    department="Продажи",
    owner_schema="sales",
    endpoint="/sales/refs/reject-reasons",
    columns=(
        ReferenceColumn("code", "Код", "string", editable=False,
                        semantic="стабильный код причины для мягких ссылок"),
        ReferenceColumn("title", "Наименование", "string"),
        ReferenceColumn("is_active", "Активен", "bool",
                        semantic="архивные не выбираются в новых сделках"),
    ),
    permissions=("sales.refs.view", "sales.refs.edit"),
    archivable=True, versioned=False, ai_exposed=True,
    description="Причины перевода сделки в отказ; используется в воронке.",
))
```

---

## 5. Shared-kernel reference-data — ORM (public)

> Системные справочники ядро регистрирует на себя тем же `register_reference`.
> Файл: `core/domain/reference.py` (новый), модели наследуют `Base`, схема public по умолчанию.

### 5.1 Простые справочники (архив, без истории)

```python
class Unit(Base):                       # единицы измерения
    __tablename__ = "ref_unit"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)     # "шт", "кг", "м"
    title: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)

class Country(Base):
    __tablename__ = "ref_country"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)     # ISO "BY", "RU"
    title: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)

class Bank(Base):
    __tablename__ = "ref_bank"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)     # БИК
    title: Mapped[str]
    swift: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)

class Currency(Base):
    __tablename__ = "ref_currency"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)     # ISO "BYN", "USD"
    title: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
```

### 5.2 Историчные справочники — SCD Type 2 (versioned=True)

> Курс валюты и ставка НДС меняются во времени; документ от прошлой даты должен видеть
> значение, действовавшее тогда. Нативные temporal Postgres — это PG18/19, у нас PG16 →
> ручной SCD2. Модель заложена под будущий апгрейд (start/end = half-open [start, end)).

```python
class CurrencyRate(Base):               # курс валюты к BYN, историчный
    __tablename__ = "ref_currency_rate"
    id: Mapped[int] = mapped_column(primary_key=True)       # surrogate key
    currency_code: Mapped[str]                              # natural key
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    start_date: Mapped[date]                                # действует с (вкл.)
    end_date: Mapped[date | None]                           # по (искл.); NULL = текущая
    __table_args__ = (
        Index("ix_ref_currency_rate_lookup", "currency_code", "start_date"),
    )

class VatRate(Base):                    # ставка НДС, историчная
    __tablename__ = "ref_vat_rate"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]                                       # natural key: "НДС20"
    title: Mapped[str]
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))    # 20.00
    start_date: Mapped[date]
    end_date: Mapped[date | None]                           # NULL = текущая
```

**Правило записи SCD2** (в сервисе, транзакция — у вызывающего, как принято в ядре):
текущую строку закрыть `end_date = новая_дата`, вставить новую `start_date = новая_дата, end_date = NULL`.
**Чтение на дату:** `WHERE natural_key = ? AND start_date <= :d AND (end_date IS NULL OR end_date > :d)`.

### 5.3 Характеристики номенклатуры — JSONB, не EAV

```python
# в существующей модели Sku (core/domain/models.py) добавить колонку:
attributes: Mapped[dict] = mapped_column(JSONB, default=dict)   # цвет/размер/тех.параметры
# GIN-индекс в миграции для поиска по характеристикам:
# CREATE INDEX ix_sku_attributes ON sku USING gin (attributes);
```

---

## 6. Миграция Alembic (Postgres — источник истины схемы)

`alembic revision -m "reference-data: units, currency(+rate), country, bank, vat(+history), sku.attributes"`

- create: `ref_unit`, `ref_currency`, `ref_currency_rate`, `ref_country`, `ref_bank`, `ref_vat_rate`
- alter `sku`: add `attributes JSONB NOT NULL DEFAULT '{}'` + GIN-индекс
- seed стартовых значений (BYN/USD/EUR, шт/кг/м, BY/RU, НДС 20/10/0) — отдельным data-migration или `scripts/seed.py`
- SQLite-dev: JSONB → JSON, всё создаётся через `create_all` автоматически (схем нет)

---

## 7. Доступ AI поверх этого

- **Точные lookup'ы** (курс на дату, ставка НДС, единица по коду) → предопределённые tools/MCP, читающие эти таблицы по `/system/references/ai-catalog`. НЕ эмбеддинги.
- **pgvector** — позже, только для нечёткого поиска по `Sku.title`/`attributes` и дедупа похожих названий.
- Денормализованные **materialized views** для AI собирать поверх golden records, обновлять по outbox-событиям.

---

## 8. Порядок вживления (когда дашь добро на код в core)

1. `contract.py`: `ReferenceColumn`, `Reference`.
2. `core.py`: `RegisteredReference`, `self.references`, `register_reference`.
3. `system_routes.py`: `/references`, `/references/ai-catalog`.
4. `core/domain/reference.py`: ORM-таблицы; колонка `Sku.attributes`.
5. Alembic-миграция + seed.
6. Регистрация системных справочников ядром (в `app.py`/стартовом хуке) и пример в `sales`.
7. Frontend: вкладка «Справочники» читает `/system/references`.

⚠️ Пункты 1–6 трогают общий `main` — согласовать с параллельным флотом воркеров, лить отдельной полосой (см. parallel-sessions-sync), не вслепую.
