# sprav-import — scope (экран 6: импорт из 1С — синк LIVE, маппинг/предпросмотр ДЕМО)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 6).
Визуальный эталон: `spravochniki-import-1c-preview.html`.

## Задача (уровень 2)

Порт экрана адаптера 1С. Маршрут `/erp/spravochniki/import`. **Смешанный статус (гэп C открыт):**
- **LIVE:** кнопка «Синхронизировать» → `POST /api/integrations/1c/sync`, показать summary ответа
  `{counterparties, new_counterparties, counterparty_aliases, stock}`.
- **ДЕМО (пометить плашкой):** шаги «маппинг полей → предпросмотр конфликтов → импорт» из макета —
  бэкенда нет. Рисуй из макета, но **визуально помечай как демо** (бейдж/плашка), НЕ выдавай за live.

Клиентская мутация синка — обычный `fetch("/api/integrations/1c/sync", {method:"POST"})` (этой функции
в reference-data.ts нет — это не справочник; зови прокси напрямую, как делают мутации в проекте).
reference-data.ts НЕ трогать.

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/import/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-import.tsx
    - frontend/src/lib/spravochniki-import.ts
    - frontend/src/lib/spravochniki-import.test.ts
  exclude:
    - frontend/src/lib/reference-data.ts
    - frontend/src/lib/api.ts
    - frontend/src/components/sidebar.tsx
    - core/**
    - modules/**
    - migrations/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 30
  max_files_changed: 4
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_5_iters
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/sprav-import-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/import`: LIVE-кнопка синка → POST /api/integrations/1c/sync, рендер summary.
- [ ] Демо-шаги (маппинг/конфликты) **визуально помечены** как демо (плашка/бейдж).
- [ ] Graceful degrade без бэка (кнопка не валит страницу). Вид как `spravochniki-import-1c-preview.html`.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- Соблазн «дорисовать» backend маппинга — НЕ делать (гэп C, бэкенд заморожен). Маппинг = демо.
- POST-прокси-путь: бить в `/api/integrations/1c/sync` (клиентский прокси), не в `${BASE}` напрямую.
