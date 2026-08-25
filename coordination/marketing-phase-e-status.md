# Статус воркера: marketing-phase-e

## Loop iteration 1

### Think
- Допущения: Campaign.leads уже накапливается через on_lead_received, BFF только читает
- Риск: маршрут `/campaigns/attribution` может конфликтовать с `/campaigns/{id}` → ставить ПЕРЕД
- Риск: budget: float теряет BYN-точность → нужен str
- Путь отката: если budget: str ломает старые вызовы — изолировать через CampaignAttributionOut (но нет, в ТЗ требуется и для CampaignOut)
- Импорты: модуль не должен касаться modules/sales

### Test
- Написаны 5 тестов в test_marketing_phase_e.py (pytest.mark.asyncio)
- Паттерн: сессия + api из conftest.py (SQLite in-memory, SCHEMA_TRANSLATE)
- Тест attribution_counts_leads: FakeCtx + on_lead_received + session.commit + GET attribution

### Validate
- pytest tests/test_marketing_phase_e.py: **5 passed** (6.19s)
- import main: OK
- ruff check: All checks passed! (исправлены pre-existing I001+F401 в models.py, seo_schemas.py)
- tsc --noEmit: exit 0

### Wire
Файлы (scope-clean, только marketing + тесты + frontend):
- `modules/marketing/schemas.py` — +CampaignAttributionOut; budget: float→str в CampaignOut
- `modules/marketing/routes.py` — +GET /campaigns/attribution перед {campaign_id}; явный str(budget) везде
- `modules/marketing/models.py` — ruff I001 fix (import sort)
- `modules/marketing/seo_schemas.py` — ruff F401 fix (unused date)
- `frontend/src/components/erp/marketing-campaign-board.tsx` — новый async server component
- `frontend/src/app/erp/marketing/page.tsx` — ModuleBoard + MarketingCampaignBoard
- `tests/test_marketing_phase_e.py` — 5 тестов

### Review — Acceptance-gate

| Критерий | Результат |
|----------|-----------|
| pytest tests/test_marketing_phase_e.py = 0 failed | ✅ 5/5 GREEN |
| import main = OK | ✅ |
| ruff check modules/marketing/ tests/test_marketing_phase_e.py | ✅ чисто |
| tsc --noEmit в frontend/ | ✅ exit 0 |
| Коммит в submodule modules/marketing (MAR-8) | ✅ 76c0f1d |
| Bump gitlink в суперпроекте ветки marketing-phase-e | ✅ 6c908a8 |
| НЕ трогать modules/sales/ | ✅ |
| НЕ пушить | ✅ |

→ **ВСЕ 8 GREEN — выход из цикла.**

## Six-layer (коммит modules/marketing 76c0f1d)

```
SYMPTOM:    GET /marketing/campaigns/attribution → 404; budget = float (теряет дробь BYN)
DISEASE:    routes.py: нет attribution endpoint; schemas.py: budget: float
ROOT CAUSE: Класс A — отсутствующая проводка (Phase E не была реализована)
EVIDENCE:   modules/marketing/routes.py (до правки) — 3 роута, нет attribution
            modules/marketing/schemas.py:21 — budget: float
PATTERN:    BFF-агрегация поверх уже работающего event-handler (leads уже считаются)
SOLUTION:   + CampaignAttributionOut; budget: str; GET /campaigns/attribution перед {campaign_id}
UX IMPACT:  Маркетолог видит UTM-отчёт атрибуции с точным бюджетом BYN
```

## Deliverables

- [x] GET /marketing/campaigns/attribution (BFF, список кампаний отсортирован по leads desc)
- [x] CampaignAttributionOut схема (id, name, channel, utm_*, leads, budget:str, goal)
- [x] CampaignOut.budget: str (все эндпоинты: list, create, launch)
- [x] Маршрут attribution ДО {campaign_id} routes
- [x] frontend/src/components/erp/marketing-campaign-board.tsx — async server component
- [x] frontend/src/app/erp/marketing/page.tsx — ModuleBoard + MarketingCampaignBoard
- [x] tests/test_marketing_phase_e.py — 5 тестов, все green
- [x] Коммит в submodule MAR-8 (76c0f1d в main checkout, 1c3e34c в Сlaude CRM)
- [x] Bump gitlink в marketing-phase-e branch (commit 6c908a8)

## Out-of-scope findings

- Pre-existing ruff errors в models.py (I001) и seo_schemas.py (F401) — исправлены как
  блокер DoD (ruff check на директорию modules/marketing/ включает все файлы), это
  минорные lint-фиксы, не функциональные изменения.

================================================================
STATE: COMPLETE
================================================================
