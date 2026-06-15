# sprav-card — scope (экран 5: карточка эталона контрагента — golden record)

Читай сначала: `coordination/sprav-fe-common.md` + `coordination/reference-fe-scope.md` (строка 5).
Визуальный эталон: `spravochniki-card-preview.html`.

## Задача (уровень 2)

Порт карточки эталона контрагента (golden record): реквизиты + источники (alias 1С/Bitrix/merge) +
слитые дубли + контакты + аудит-история. Маршрут `/erp/spravochniki/counterparty/[id]`.
**Гэп A закрыт** — это LIVE-экран (эндпоинт `GET /system/mdm/counterparty/{id}` есть).

Данные (LIVE) через готовый клиент:
- `fetchCounterpartyCard(id, role)` → `CounterpartyCard | null` (SSR): `{id,name,unp,is_active,
  merged_into_id, aliases[], merged_duplicates[], contacts[], audit[]}`.
- Поиск/список контрагентов для перехода в карточку — `runReferenceQuery({ref:"core.counterparties", name|key, limit})`.

ВАЖНО: `audit` сейчас реально пуст (доменных событий по контрагенту ещё не пишется) — показывай
«Истории изменений пока нет», это НЕ демо. Источники/дубли/контакты — реальные.

Верификация: `cd frontend && npx tsc --noEmit` чисто; чистая логика — под vitest.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/spravochniki/counterparty/[id]/page.tsx
    - frontend/src/components/erp/spravochniki/sprav-card.tsx
    - frontend/src/lib/spravochniki-card.ts
    - frontend/src/lib/spravochniki-card.test.ts
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
  destination: coordination/sprav-card-status.md
```

## Acceptance gate

- [ ] `/erp/spravochniki/counterparty/[id]` рендерит карточку из `fetchCounterpartyCard(id)`:
      реквизиты, источники (aliases), слитые дубли, контакты, аудит.
- [ ] Пустой аудит → «Истории изменений пока нет» (не плашка «демо»). `null`/404 → состояние «не найдено».
- [ ] Вид как `spravochniki-card-preview.html`; токены/иконки проекта.
- [ ] `npx tsc --noEmit` чисто; vitest зелено. Только файлы scope. Six-layer. `STATE: COMPLETE`. Без push.

## Anticipated failure modes
- Динамический сегмент `[id]`: params в Next 15 — async (`await params`). Учти версию Next в проекте.
- `fetchCounterpartyCard` вернёт null при 404 — отрисуй «не найдено», не падай.
