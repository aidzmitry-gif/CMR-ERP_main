# sprav-card — Status

================================================================
STATE: COMPLETE
================================================================

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-sprav-card
Branch: sprav-card
Spawned at: 2026-06-15T14:55:23.170902+00:00
Completed at: 2026-06-15T18:35:00+00:00 (approx)

---

## Loop Iteration 1

### Think
**Гипотеза:** Все данные `CounterpartyCard` доступны через `fetchCounterpartyCard` (уже реализовано в `reference-data.ts`). Нужно лишь создать 4 файла в рамках scope.

**Допущения:**
- Next.js 15 async params — `const { id } = await params` ✓
- `audit` реально пуст → показывать «Истории изменений пока нет», не плашку «демо» ✓
- `lucide-react@^1.17.0` не поддерживает `title` prop на SVG-иконках → убрать ✓
- `node_modules` в worktree нет — нужен junction к main-репо ✓
- Pure logic (`groupAliasesBySource`, `formatAuditDate`) → `spravochniki-card.ts` + vitest

**Путь отката:** если tsc не пройдёт — откатить только новые файлы (они все новые).

### Test (TDD)
Написаны до кода компонента:
- `groupAliasesBySource`: 5 кейсов (пустой, один, дубли, разные источники, порядок)
- `formatAuditDate`: 3 кейса (DD.MM.YYYY, паддинг, конец года без TZ drift)

Результат: **8/8 GREEN** (`vitest run src/lib/spravochniki-card.test.ts`, exit 0)

### Validate
- `vitest run` → 1 test file, 8 tests, все PASSED (v4.1.8)
- `tsc --noEmit` → exit 0, нет ошибок (после fix `title` prop)

### Wire
Файлы (все новые, в рамках scope):
- `frontend/src/lib/spravochniki-card.ts` — 2 чистые функции
- `frontend/src/lib/spravochniki-card.test.ts` — 8 vitest-тестов
- `frontend/src/app/erp/spravochniki/counterparty/[id]/page.tsx` — async server
- `frontend/src/components/erp/spravochniki/sprav-card.tsx` — client component

Найденная гоча: `node_modules` отсутствует в worktree → создан junction:
`New-Item -ItemType Junction -Path frontend\node_modules -Target "...\Сlaude CRM - проект\frontend\node_modules"`

### Review
**Acceptance gate:**

- [x] `/erp/spravochniki/counterparty/[id]` рендерит карточку из `fetchCounterpartyCard(id)`:
      реквизиты (name/unp/is_active), источники (aliases), слитые дубли, контакты, аудит ✓
- [x] Пустой аудит → «Истории изменений пока нет» (не плашка «демо»). `null` → «Контрагент не найден» ✓
- [x] Вид как `spravochniki-card-preview.html`; токены/иконки проекта (canvas/ink/muted/brand/shadow-card/rounded-2xl, lucide-react) ✓
- [x] `tsc --noEmit` чисто (exit 0) ✓
- [x] `vitest run` зелено (8/8) ✓
- [x] Только файлы scope (4 файла, все в `include`, ни одного из `exclude`) ✓
- [x] Six-layer в теле коммита ✓
- [x] Без push ✓

**→ DONE (все 8/8 GREEN, один чистый прогон)**

---

## Six-layer (коммит)

```
SYMPTOM:    Маршрут /erp/spravochniki/counterparty/[id] отсутствовал — 404
DISEASE:    Экран 5 вкладки «Справочники» не был портирован в Next.js
ROOT CAUSE: A — отсутствующая проводка (page + component не созданы)
EVIDENCE:   frontend/src/app/erp/spravochniki/ — директория не существовала до этого коммита
PATTERN:    SSR page → client component, данные через готовый fetchCounterpartyCard
SOLUTION:   4 файла scope: page.tsx (async/await params), sprav-card.tsx ("use client"),
            spravochniki-card.ts (groupAliasesBySource+formatAuditDate), test.ts (8 тестов)
UX IMPACT:  Пользователь открывает /erp/spravochniki/counterparty/1 и видит golden record:
            реквизиты, алиасы/источники, слитые дубли, контакты, аудит (или «пока нет»)
```

---

## Deliverables (по scope)

- [x] `frontend/src/app/erp/spravochniki/counterparty/[id]/page.tsx` — async server, await params, null→не найдено
- [x] `frontend/src/components/erp/spravochniki/sprav-card.tsx` — client, все 5 секций
- [x] `frontend/src/lib/spravochniki-card.ts` — groupAliasesBySource + formatAuditDate
- [x] `frontend/src/lib/spravochniki-card.test.ts` — 8 vitest-тестов, все GREEN

## Out-of-scope findings

- `node_modules` junction нужен в worktree перед tsc/vitest; оркестратор может автоматизировать при spawn.
- Таб-бар (Адреса, Банковские счета, Товарные группы) из HTML-превью не реализован — данных из backend нет, согласно scope только реквизиты/aliases/merged_duplicates/contacts/audit.
