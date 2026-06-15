# sprav-ai — scope (экран 4: AI-каталог + структурный запрос reference.query)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 4).
Визуальный эталон: `spravochniki-ai-preview.html`.

## Задача (уровень 2)

Порт экрана «AI-доступ к справочникам»: узкий каталог `ai_exposed`-справочников (что AI видит и
как точно запросить) + интерактивный структурный запрос `reference.query` (точное значение с
историчностью as_of; pgvector вторичен). Маршрут `/erp/spravochniki/ai`.

Данные (LIVE) через готовый клиент:
- `fetchAiCatalog(role)` → узкий каталог только `ai_exposed` (SSR): tool-описание + поля/эндпоинты.
- `runReferenceQuery({ref, key, as_of, name, limit})` → результат структурного lookup (мутация → /api).

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/ai/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-ai.tsx
    - frontend/src/lib/spravochniki-ai.ts
    - frontend/src/lib/spravochniki-ai.test.ts
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
  destination: coordination/sprav-ai-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/ai` показывает AI-каталог (`fetchAiCatalog`): какие справочники видны AI, поля, эндпоинты.
- [ ] Есть форма структурного запроса (ref/key/as_of/name/limit) → `runReferenceQuery`, результат рендерится.
- [ ] Graceful degrade без бэка. Вид как `spravochniki-ai-preview.html`.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- `fetchAiCatalog` может вернуть null (бэк недоступен/ai выкл) — обработай пустое состояние.
- as_of требует YYYY-MM-DD; пустые поля не слать как "".
