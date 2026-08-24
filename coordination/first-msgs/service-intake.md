# Воркер: service-intake — ServiceRequest + доска Сервиса

## Цель (Goal-Driven)
Добавить модель `ServiceRequest` и доску Сервиса: backend (модель, схемы, роуты, подписка на
`sales.deal.won`), фронт (FunnelBoard-конфиг), миграция. Критерий готовности:
`pytest tests/test_service_intake.py` = 0 failed, `import main` = OK, `ruff check` = чисто,
`tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/service/` (SER-POD-9.git) — коммитить ТУДА отдельно, потом bump gitlink в суперпроекте
- Модуль Service уже имеет:
  - `module.py` — `ServiceModule(ModuleContract)`, `name="service"`, `api_prefix="/service"`,
    регистрирует роуты + `Widget("service", ...)`. Подписок нет — добавить `sales.deal.won`.
  - `models.py` — ORM-модель `Ticket` (схема `service`, поля: `id`, `customer`, `subject`,
    `body`, `status`, `created_at`). Добавить `ServiceRequest` рядом.
  - `routes.py` — `APIRouter(tags=["service"])`, эндпоинты `/tickets` (GET list, POST create).
    Добавить эндпоинты `/requests`.
  - `schemas.py` — `TicketCreate`, `TicketOut`. Добавить схемы `ServiceRequest*`.
- Миграция: выполнить `python scripts/next_migration.py service-intake "service intake requests"`
  → получить номер N; создать файл `migrations/versions/N_service_intake_requests.py`
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`
- `service` уже есть в `config/modules.py` ENABLED_MODULES — трогать этот файл НЕ нужно

## Событие `sales.deal.won` (откуда подписываться)
Эмитируется в `modules/sales/routes.py` (~строка 1423). Payload:
```python
{
    "deal_id": deal.id,        # int
    "number": deal.number,     # str
    "amount": float(deal.amount),  # float
    "owner": deal.owner,       # str
    "entity_ref": f"deal:{deal.id}",  # str
}
```
При подписке модуль service должен создать `ServiceRequest` из этих данных идемпотентно
(проверка по `deal_id IS NOT NULL AND deal_id = payload["deal_id"]`).

## Шаг 1 — Модель ServiceRequest в modules/service/models.py
Добавить рядом с `Ticket` (не удалять `Ticket`!):
```python
class ServiceRequest(Base):
    """Заявка на обслуживание: ручная или автоматическая (от выигранной сделки)."""
    __tablename__ = "service_request"
    __table_args__ = {"schema": "service"}

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="new", server_default="new")
    # Допустимые значения: new | in_progress | done
    priority: Mapped[str] = mapped_column(String(32), default="normal", server_default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```
Импорты добавить: `Integer` из `sqlalchemy`.

## Шаг 2 — Миграция
```powershell
$env:PYTHONPATH="."
python scripts/next_migration.py service-intake "service intake requests"
```
Получить номер N. Создать `migrations/versions/N_service_intake_requests.py`:
```python
def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS service")
    op.create_table(
        "service_request",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("counterparty_id", sa.Integer, nullable=True),
        sa.Column("deal_id", sa.Integer, nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="new", nullable=False),
        sa.Column("priority", sa.String(32), server_default="normal", nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("now()"), nullable=False),
        schema="service",
    )

def downgrade() -> None:
    op.drop_table("service_request", schema="service")
```

## Шаг 3 — Схемы Pydantic в modules/service/schemas.py
Добавить рядом с `TicketCreate`/`TicketOut`:
```python
from datetime import datetime

class ServiceRequestCreate(BaseModel):
    counterparty_id: int | None = None
    deal_id: int | None = None
    title: str
    description: str = ""
    priority: str = "normal"

class ServiceRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    counterparty_id: int | None
    deal_id: int | None
    title: str
    description: str
    status: str
    priority: str
    created_at: datetime

class ServiceRequestPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
```

## Шаг 4 — Эндпоинты в modules/service/routes.py
Добавить к существующим `/tickets`:
```
GET  /service/requests?status=   — список заявок (фильтр по status), desc id
POST /service/requests            — создать заявку (201)
GET  /service/requests/{id}       — одна запись
PATCH /service/requests/{id}      — обновить статус/приоритет
```
Использовать `ServiceRequest`, `ServiceRequestCreate`, `ServiceRequestOut`, `ServiceRequestPatch`.
Для PATCH — `session.commit()` + `session.refresh(obj)` по аналогии с `create_ticket`.
Для GET list: если параметр `status` передан — добавлять `.where(ServiceRequest.status == status)`.

## Шаг 5 — Подписка на sales.deal.won в modules/service/module.py
Добавить обработчик (2 аргумента → получает `ctx`):
```python
async def on_deal_won_create_request(payload: dict, ctx) -> None:
    """Сделка выиграна → создать онбординговую заявку поддержки (идемпотентно по deal_id)."""
    if ctx is None:
        return
    deal_id = payload.get("deal_id")
    if not deal_id:
        return
    from sqlalchemy import select
    from modules.service.models import ServiceRequest
    existing = (
        await ctx.session.execute(
            select(ServiceRequest).where(ServiceRequest.deal_id == deal_id)
        )
    ).scalars().first()
    if existing:
        return  # идемпотентность
    number = payload.get("number", "")
    counterparty = payload.get("counterparty", "")
    req = ServiceRequest(
        deal_id=deal_id,
        title=f"Онбординг: сделка {number}",
        description=f"Автозаявка по выигранной сделке {number}. Контрагент: {counterparty}.",
        status="new",
        priority="normal",
    )
    ctx.session.add(req)
    # коммит делает вызывающий eventbus-цикл
```
В `register()` добавить:
```python
core.subscribe("sales.deal.won", on_deal_won_create_request)
```

## Шаг 6 — Frontend: FunnelBoard-конфиг для Сервиса
Добавить секцию `service` в `frontend/src/lib/funnel-configs.ts` по аналогии с `procurement`:
```typescript
service: {
  createLabel: "Создать заявку",
  kpis: [
    { label: "Заявок в работе", value: "12", target: "20", note: "60% от плана", percent: 60, tone: "blue" },
    { label: "Закрыто сегодня", value: "4", target: "8", note: "50% плана", percent: 50, tone: "green" },
    { label: "SLA выполнен", value: "87%", note: "цель ≥ 90%", percent: 87, tone: "amber" },
  ],
  statusNote: "12 заявок в работе · 3 просрочены · 2 ждут ответа",
  panel: {
    title: "Активные обращения",
    tabs: ["Лента", "Клиенты", "Задачи"],
    items: [
      { title: "Онбординг: сделка CRM-042", text: "Клиент подключён, ждёт инструкций", tone: "info" },
      { title: "Рекламация #SR-007", text: "Ожидает ответа клиента 2 дня", tone: "alert", badge: 1 },
      { title: "Техподдержка #SR-011", text: "Решено, ожидает закрытия", tone: "ok" },
    ],
  },
  summary: [
    { label: "Всего заявок", value: "38", delta: "+5%" },
    { label: "Закрыто", value: "26", delta: "+8%" },
    { label: "SLA", value: "87%", delta: "-2%" },
    { label: "Среднее время", value: "4.2 ч", delta: "-0.3" },
  ],
},
```
Создать страницу `frontend/src/app/erp/service/requests/page.tsx`:
- Заголовок «Заявки на обслуживание»
- `FunnelBoard` с конфигом `service` (из `FUNNEL_EXTRAS`)
- Таблица запросов: ID | Заголовок | Статус | Приоритет | Дата создания
- Фильтр по статусу (new / in_progress / done)
- Кнопка «Создать заявку»

## Шаг 7 — Тесты tests/test_service_intake.py
```python
# GET /service/requests → 200, список
# POST /service/requests → 201, поля в ответе
# GET /service/requests/{id} → 200
# PATCH /service/requests/{id} → 200, status обновлён
# GET /service/requests?status=new → только new
# import main = OK (в conftest или отдельным тестом)
# deal_id уникален: POST дважды с одним deal_id через подписку не создаёт дубль
```
Использовать `httpx.AsyncClient(app=app, base_url="http://test")` + `AsyncSession` на SQLite
(как в других тестах, например `tests/test_hr_okk.py` или `tests/test_sales.py`).

## Запуск
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python scripts/next_migration.py service-intake "service intake requests"
python -m pytest tests/test_service_intake.py -x -q
python -c "import main"
ruff check modules/service/ tests/test_service_intake.py --line-length 100
cd frontend; npx tsc --noEmit; cd ..
```

## DoD
- pytest tests/test_service_intake.py зелёный + import main + ruff чисто + tsc --noEmit OK
- Коммит в `modules/service/` (submodule SER-POD-9) → bump gitlink в суперпроекте
- `STATE: COMPLETE` записать в `coordination/service-intake-status.md`
- НЕ пушить (пуш делает координатор)
