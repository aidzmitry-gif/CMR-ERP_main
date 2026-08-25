# service-intake — Status

## Loop iteration 1

- **Think:** Задача — добавить ServiceRequest модель + CRUD /service/requests + подписку на
  `sales.deal.won`. Допущения: submodule modules/service уже существует (Ticket, routes, module);
  funnel-configs.ts расширяем ключом `service`. Откат: git revert коммита сабмодуля + суперпроекта.
- **Test:** Определены 8 тест-кейсов (list, create, get, get-404, patch, filter, deal_id, import main).
- **Validate:** 8 passed in 8.39s. ruff — чисто. tsc --noEmit — чисто. import main — OK.
- **Wire:** 6 файлов изменено/создано (modules/service × 4, migration, test, frontend × 2).
- **Review:** Все acceptance-gate GREEN → DONE.

---

## Karpathy 5-step compliance

- [x] Think: допущения и путь отката задокументированы
- [x] Test: тесты написаны ДО wire
- [x] Validate: `pytest tests/test_service_intake.py` — 8 passed
- [x] Wire: хирургические изменения только в scope
- [x] Review: все критерии зелёные

---

## Six-layer

```
SYMPTOM:    Модуль Сервис не имел заявок на обслуживание; выигранные сделки не создавали follow-up
DISEASE:    Отсутствовали модель ServiceRequest, API /service/requests и подписка на events шины
ROOT CAUSE: A — отсутствующая проводка; service-intake не был реализован
EVIDENCE:   modules/service/models.py (только Ticket), module.py (нет subscribe), routes.py (нет /requests)
PATTERN:    Model + Schema + Router + EventSubscription + FunnelBoard
SOLUTION:   ORM ServiceRequest + миграция 0083 + CRUD роуты + идемпотентный on_deal_won_create_request
            + funnel-configs.ts секция service + /erp/service/requests/page.tsx
UX IMPACT:  Выигранная сделка → автозаявка поддержки; доска /erp/service/requests показывает статус SLA
```

---

## Deliverables

- [x] `modules/service/models.py` — добавлен `ServiceRequest`
- [x] `modules/service/schemas.py` — `ServiceRequestCreate`, `ServiceRequestOut`, `ServiceRequestPatch`
- [x] `modules/service/routes.py` — GET/POST/GET{id}/PATCH `/service/requests`
- [x] `modules/service/module.py` — подписка `sales.deal.won` → `on_deal_won_create_request`
- [x] `migrations/versions/0083_service_intake_requests.py` — revision=0083, down_revision=0082
- [x] `tests/test_service_intake.py` — 8 тестов, все GREEN
- [x] `frontend/src/lib/funnel-configs.ts` — секция `service`
- [x] `frontend/src/app/erp/service/requests/page.tsx` — FunnelBoard + фильтр статуса
- [x] Коммит в submodule `modules/service` (SER-POD-9): `69e0f9d`
- [x] Bump gitlink в суперпроекте: `de9b1c8`

---

## Acceptance gate

| Критерий | Результат |
|---------|-----------|
| `pytest tests/test_service_intake.py` = 0 failed | ✅ 8 passed |
| `import main` = OK | ✅ OK |
| `ruff check modules/service/ tests/test_service_intake.py` | ✅ All checks passed |
| `tsc --noEmit` | ✅ нет output (0 errors) |
| Коммит в submodule + bump gitlink | ✅ de9b1c8 |

---

## PITFALLS-DISCOVERED

- **СИМПТОМ: `next_migration.py` возвращает down_revision=0079 вместо реального alembic-head 0082** →
  причина: файл `.migration-reservations.local` содержит старые резервы; `_head()` берёт max резервов,
  игнорируя реальные файлы миграций → **ЛЕЧЕНИЕ: всегда проверять реальный head через `git log` /
  открыть файл последней миграции; корректировать down_revision вручную, если script выдал stale значение**

- **СИМПТОМ: `git commit` в submodule падает с «Author identity unknown»** →
  причина: локальный git-config в submodule не задан, а global config содержит machine-default email →
  **ЛЕЧЕНИЕ: перед первым коммитом в submodule запускать
  `git config user.email "..." && git config user.name "..."`**

---

================================================================
STATE: COMPLETE
================================================================
