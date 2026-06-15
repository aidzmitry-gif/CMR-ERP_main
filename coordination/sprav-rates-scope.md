# sprav-rates — scope (экран 2: версионные справочники SCD2 — курсы валют + НДС)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 2).
Визуальный эталон: `spravochniki-versioned-preview.html`.

## Задача (уровень 2)

Порт экрана версионных справочников (SCD Type 2): курсы валют и ставки НДС с историей версий
(полуоткрытый интервал; текущая = `end_date=null`). Маршрут `/erp/spravochniki/rates`.

Данные (LIVE) через готовый клиент:
- `fetchCurrencyRates(key, role)` / `fetchVatRates(key, role)` — список версий (SSR).
- `currencyRateAsOf(key, on)` — курс на дату (as-of).
- `addRateVersion(table, payload)` — добавить новую версию (клиентская мутация → /api).
- Хелперы: `isCurrentVersion(row)`, `sortVersionsDesc(rows)`.

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/rates/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-rates.tsx
    - frontend/src/lib/spravochniki-rates.ts
    - frontend/src/lib/spravochniki-rates.test.ts
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
  destination: coordination/sprav-rates-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/rates` показывает версии курса/НДС, текущая выделена (`isCurrentVersion`).
- [ ] Версии отсортированы по убыванию даты (`sortVersionsDesc`); есть as-of-запрос (`currencyRateAsOf`).
- [ ] Форма «добавить версию» зовёт `addRateVersion` (мутация через /api); graceful degrade без бэка.
- [ ] Вид как `spravochniki-versioned-preview.html`; токены/иконки проекта.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- Путаница полуоткрытого интервала (текущая = end_date null) — сверяйся с `isCurrentVersion`.
- Дата as-of в неверном формате (нужен YYYY-MM-DD) — Class D.
