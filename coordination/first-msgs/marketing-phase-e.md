# Воркер: marketing-phase-e — UTM-атрибуция и доска кампаний

## Цель (Goal-Driven)
Реализовать Phase E маркетинга:
1. **UTM-отчёт атрибуции** — новый BFF-эндпоинт `GET /marketing/campaigns/attribution` в `modules/marketing/routes.py`, который агрегирует по каждой кампании количество атрибутированных лидов (инкрементируемых через event `sales.lead.received` → `on_lead_received` → `campaign.leads`). Поле `Campaign.leads` уже обновляется событийно — эндпоинт читает его вместе с UTM-параметрами и возвращает отчёт (`list[CampaignAttributionOut]`). Деньги (`budget`) — строкой (Decimal→str).
2. **Живая доска кампаний** — обновить страницу `/erp/marketing` в фронтенде: вместо голого `ModuleBoard` — новый компонент `MarketingCampaignBoard` с таблицей кампаний (название, канал, UTM-source/medium/campaign, бюджет BYN, лиды, статус) и блоком «Attribution» (вызов `/marketing/campaigns/attribution`).

Критерий готовности: `pytest tests/test_marketing_phase_e.py` = 0 failed, `import main` = OK, `ruff check` = чисто, `tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/marketing/` (MAR-8.git) — коммитить ТУДА отдельно, потом bump gitlink в суперпроекте
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`

### Реальные символы модуля marketing

**models.py** — `Campaign` (schema `marketing`):
- `id`, `name`, `channel`, `budget` (Numeric 14,2), `leads` (Integer),
  `utm_source` (String 128), `utm_medium` (String 128), `utm_campaign` (String 255),
  `goal`, `kpi_json`, `created_at`
- Также: `Site`, `SeoProject`, `SeoSnapshot`, `SeoTask`

**routes.py** — `router = APIRouter(tags=["marketing"])`:
- `GET /marketing/campaigns` → `list[CampaignOut]`
- `POST /marketing/campaigns` → `CampaignOut` (201)
- `POST /marketing/campaigns/{campaign_id}/launch` → `CampaignOut` (эмитит `marketing.campaign.launched`)

**schemas.py** — `CampaignCreate`, `CampaignOut` (поля: id, name, channel, budget:float, leads, utm_source, utm_medium, utm_campaign, goal)

**module.py** — `MarketingModule`: подписан на `sales.lead.received` → `on_lead_received`

**seo_events.py** — `on_lead_received(payload, ctx)`:
- матчит кампанию по `utm_campaign` или `utm_source == "seo"`
- инкрементирует `campaign.leads += 1`

**seo_routes.py** — `router = APIRouter(prefix="/seo", tags=["marketing-seo"])`: все SEO-маршруты

**frontend/src/app/erp/marketing/page.tsx** — сейчас `ModuleBoard` с endpoint `/marketing/campaigns`

### Как лиды достигают marketing БЕЗ касания modules/sales

`sales.lead.received` — стандартное событие outbox шины. Sales эмитит его при каждом новом лиде с payload `{lead_id, source, utm_source, utm_medium, utm_campaign, landing_url}`. Marketing уже **подписан** на него (`core.subscribe("sales.lead.received", on_lead_received)` в `module.py`). Хэндлер `on_lead_received` обновляет `campaign.leads` в той же сессии события.

**Атрибуционный эндпоинт читает только `marketing.campaign`** — никакого обращения к `modules/sales`. Поле `Campaign.leads` является накопленным счётчиком атрибутированных лидов.

## Шаг 1 — Схемы Pydantic в modules/marketing/schemas.py

Добавить:
```python
class CampaignAttributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    channel: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    leads: int           # атрибутированных лидов (Campaign.leads)
    budget: str          # Decimal → str, BYN
    goal: str
```

Также обновить `CampaignOut`: поле `budget` изменить с `float` на `str` (Decimal→str в роуте), добавить `utm_source`, `utm_medium`, `utm_campaign`, `goal` если ещё не экспонированы.

## Шаг 2 — BFF-эндпоинт атрибуции в modules/marketing/routes.py

```python
@router.get("/campaigns/attribution", response_model=list[CampaignAttributionOut])
async def campaigns_attribution(session: AsyncSession = Depends(get_session)):
    """UTM-отчёт: кампании с накопленными счётчиками лидов."""
    rows = (await session.execute(
        select(Campaign).order_by(Campaign.leads.desc())
    )).scalars().all()
    return [
        CampaignAttributionOut(
            id=c.id,
            name=c.name,
            channel=c.channel,
            utm_source=c.utm_source,
            utm_medium=c.utm_medium,
            utm_campaign=c.utm_campaign,
            leads=c.leads,
            budget=str(c.budget),
            goal=c.goal,
        )
        for c in rows
    ]
```

⚠️ Маршрут `/campaigns/attribution` должен быть зарегистрирован **до** `/campaigns/{campaign_id}/launch`, иначе FastAPI сматчит `attribution` как `campaign_id`.

## Шаг 3 — Обновить schemas.py: budget строкой

В `CampaignOut` заменить `budget: float` → `budget: str`. В `create_campaign` (`routes.py`) возврат остаётся через `session.refresh(obj)`; добавить `@validator` / `model_serializer` или вернуть явный dict с `str(obj.budget)`, чтобы Pydantic не обрезал дробь.

Минималистично: создать `CampaignOutV2` → или просто добавить `budget: str` и `@classmethod` / `model_validator`. Самый короткий путь — вернуть response напрямую, не через ORM-объект, аналогично `CampaignAttributionOut`.

## Шаг 4 — Frontend: компонент marketing/page.tsx

Файл: `frontend/src/app/erp/marketing/page.tsx`

Заменить (или дополнить) существующую страницу. **Все текущие блоки оставить** — не выкидывать `ModuleBoard` логику, а расширить страницу.

```tsx
// Два раздела:
// 1. Таблица кампаний (живая, через /marketing/campaigns)
//    колонки: Кампания | Канал | UTM source | UTM medium | UTM campaign | Бюджет BYN | Лиды | Цель | [Запустить]
// 2. UTM Attribution (из /marketing/campaigns/attribution)
//    та же таблица но со счётчиком лидов, сортировка по убыванию лидов
```

Минимальный вариант: серверный компонент Next.js (async), два `fetch(backendUrl + '/marketing/campaigns')` и `fetch(backendUrl + '/marketing/campaigns/attribution')`, рендер как `<table>` с Tailwind-классами. Кнопка «Запустить» → `POST /marketing/campaigns/{id}/launch` через клиентский action.

Использовать `AppShell` (уже импортирован), `process.env.BACKEND_URL ?? "http://localhost:8000"`.

Новый компонент можно создать в `frontend/src/components/erp/marketing-campaign-board.tsx`.

## Шаг 5 — Тесты tests/test_marketing_phase_e.py

```python
"""tests/test_marketing_phase_e.py — Phase E: attribution + campaign board."""
import pytest
from httpx import AsyncClient, ASGITransport
import pytest_asyncio

@pytest.mark.asyncio
async def test_attribution_empty():
    """GET /marketing/campaigns/attribution → 200, список пуст."""
    ...

@pytest.mark.asyncio
async def test_attribution_counts_leads():
    """POST кампания → эмитировать sales.lead.received вручную → attribution показывает leads=1."""
    ...

@pytest.mark.asyncio
async def test_campaigns_list_has_utm_fields():
    """GET /marketing/campaigns → поля utm_source, utm_medium, utm_campaign присутствуют."""
    ...

@pytest.mark.asyncio
async def test_budget_is_string():
    """Поле budget в ответе — строка (не float), BYN-совместимо."""
    ...

@pytest.mark.asyncio
async def test_import_main():
    import main  # noqa
```

Паттерн тестов — смотри существующие `tests/test_marketing*.py` (если есть) или `tests/test_sales*.py`:
- `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev`, SQLite in-memory
- `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`
- Таблицы: `async_engine` + `Base.metadata.create_all` перед тестами

Атрибуцию (leads += 1) проверить напрямую через `on_lead_received(payload, ctx)` с фиктивным ctx-объектом (или через прямой UPDATE campaign.leads).

## Запуск

```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"
$env:AIOS_ENVIRONMENT="dev"
$env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python -m pytest tests/test_marketing_phase_e.py -x -q
python -c "import main"
ruff check modules/marketing/ tests/test_marketing_phase_e.py --line-length 100
# frontend:
cd frontend
npx tsc --noEmit
cd ..
```

## ⚠️ Критическое ограничение — граница модулей

**ЗАПРЕЩЕНО:**
- `import modules.sales` — ни прямо, ни косвенно
- Читать `sales.*` таблицы напрямую (JOIN через schema `sales`)
- Редактировать любые файлы в `modules/sales/`

**Разрешённый механизм получения данных по лидам:**
Только через событие `sales.lead.received` (уже обрабатывается `on_lead_received` в `seo_events.py`) → данные накапливаются в `Campaign.leads`. BFF-эндпоинт читает ТОЛЬКО таблицу `marketing.campaign`.

Если нужна информация о конкретном лиде — использовать только публичный HTTP-эндпоинт sales (`GET /sales/leads/{id}`) как внешний вызов из фронтенда, НЕ из backend marketing-модуля.

## DoD
- `pytest tests/test_marketing_phase_e.py` = 0 failed
- `import main` = OK (без ImportError)
- `ruff check modules/marketing/ tests/test_marketing_phase_e.py` = чисто
- `tsc --noEmit` в `frontend/` = OK
- Коммит в `modules/marketing/` (submodule MAR-8) → bump gitlink в суперпроекте
- `STATE: COMPLETE` записать в `coordination/marketing-phase-e-status.md`
- НЕ пушить
