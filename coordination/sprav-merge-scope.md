# sprav-merge — scope (экран 3: дедупликация / MDM — слияние дублей контрагентов)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 3).
Визуальный эталон: `spravochniki-merge-preview.html`.

## Задача (уровень 2)

Порт экрана MDM-дедупликации: кластеры дублей контрагентов по УНП, слияние дубля в эталон
(survivorship) и обратная расклейка. Маршрут `/erp/spravochniki/merge`.

Данные (LIVE) через готовый клиент:
- `fetchDuplicateClusters(role)` — кластеры по одинаковому УНП (SSR).
- `mergeCounterparties(survivorId, duplicateId)` — слить (мутация → /api).
- `unmergeCounterparty(duplicateId)` — расклеить (мутация → /api).
- `totalDuplicates(clusters)` — счётчик кандидатов сверх эталона.

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/merge/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-merge.tsx
    - frontend/src/lib/spravochniki-merge.ts
    - frontend/src/lib/spravochniki-merge.test.ts
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
  destination: coordination/sprav-merge-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/merge` показывает кластеры дублей (из `fetchDuplicateClusters`) + счётчик `totalDuplicates`.
- [ ] Кнопка «Слить» зовёт `mergeCounterparties`, «Расклеить» — `unmergeCounterparty` (через /api), список обновляется.
- [ ] Graceful degrade без бэка (пусто). Вид как `spravochniki-merge-preview.html`.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- После merge не перезапрашиваются кластеры → UI рассинхронен (обнови после мутации).
- Перепутаны survivor/duplicate id — следи, какой эталон, какой дубль.
