# Воркер: office-legal — Реестр юридических договоров

## Цель
Добавить реестр договоров с контрагентами в модуль Office: backend + frontend страница.
Критерий: `pytest tests/test_office_legal.py` = 0 failed, `import main` = OK, `tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/office/` — отдельный репо
- Текущий office: читай modules/office/models.py, routes.py, module.py
- Схема БД: `office`
- Auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev

## Шаг 1 — Читать существующее
- `modules/office/models.py` — что уже есть
- `modules/office/routes.py` — существующие эндпоинты
- `modules/office/module.py` — регистрация

## Шаг 2 — Модель LegalContract (если не существует)
```python
class LegalContract(Base):
    __tablename__ = "legal_contract"
    __table_args__ = {"schema": "office"}
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64))       # "ДОГ-2026-0001"
    counterparty_name: Mapped[str] = mapped_column(String(255))
    contract_type: Mapped[str] = mapped_column(String(64))  # "supply", "service", "lease", "nda"
    status: Mapped[str] = mapped_column(String(32), default="active")  # active/expired/terminated
    signed_at: Mapped[str | None] = mapped_column(String(10), nullable=True)   # "YYYY-MM-DD"
    expires_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    amount_byn: Mapped[str] = mapped_column(String(20), default="0.00")  # Decimal as str
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

## Шаг 3 — Миграция (если модели нет)
`python scripts/next_migration.py office-legal "office legal_contract table"`

## Шаг 4 — Эндпоинты
```
GET  /office/contracts?status=&contract_type=   — список с фильтрами
POST /office/contracts                           — создать (201)
GET  /office/contracts/{id}                     — одна запись
PATCH /office/contracts/{id}                    — изменить статус/описание
```
Автономер: `ДОГ-{YYYY}-{count:04d}`

## Шаг 5 — Frontend: frontend/src/components/erp/office-legal-view.tsx
- Таблица договоров: Номер | Контрагент | Тип | Статус | Подписан | Истекает | Сумма BYN
- Статус badge: active=зелёный, expired=серый, terminated=красный
- Фильтр по типу и статусу
- Форма создания договора

## Шаг 6 — Страница frontend/src/app/erp/office/contracts/page.tsx

## Шаг 7 — Тесты tests/test_office_legal.py
- GET /office/contracts → 200
- POST → 201, автономер
- GET по id → 200
- PATCH status → обновился
- import main OK

## DoD
- тесты зелёные + ruff + tsc --noEmit
- Коммит в modules/office/ → bump gitlink
- НЕ пушить
- STATE: COMPLETE
