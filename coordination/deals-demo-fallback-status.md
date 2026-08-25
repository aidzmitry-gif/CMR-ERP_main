# deals-demo-fallback — Status

## Worktree
Path: D:\6 Проекты\CRM ERP\Сlaude CRM - проект\.claude\worktrees\trusting-germain-78c832
Branch: claude/trusting-germain-78c832
Commit: 1b9161b (локальный, НЕ пушен)
Completed at: 2026-07-03

## Задача
Молчаливый SSR-fallback `fetchBoardStages()`/`fetchKpis()` на демо-мок (`STAGES`/`KPIS`
из mock-data.ts) выдавал мок за данные `sales.deal` → ложный баг-репорт: демо-сделку
id "0156n" приняли за испорченную строку импорта Bitrix24 (import_month.py), БД чистая.
Сделать fallback различимым: warn на SSR + видимый бейдж на /crm/deals.

## Что сделано (commit 1b9161b, 4 файла, +17/−4)
- `frontend/src/lib/api.ts` — в catch обоих SSR-фетчей `console.warn` с полным URL
  и ошибкой; мок-стадии помечаются `demo: true`. ⚠ **хотспот** (DEPENDENCY-MAP) —
  правка точечная, только 2 catch-блока, сигнатуры/контракты не менялись.
- `frontend/src/lib/types.ts` — опциональный `Stage.demo?: boolean` (аддитивно).
- `frontend/src/app/crm/deals/page.tsx` — amber-бейдж «⚠ Демо-данные: бэкенд
  недоступен…» над доской при `stages.some(s => s.demo)`, с подсказкой про
  `BACKEND_URL=http://127.0.0.1:8000` (IPv6-гоча из frontend/CLAUDE.md).
- `.claude/launch.json` — `autoPort: true` (порт 3000 занят параллельной сессией).

Остальные вызыватели (`fetchOwnerDashboard`, `deal-linked-deals`) не тронуты —
флаг opt-in, бейдж рендерит только доска.

## Acceptance gate
- [x] `tsc --noEmit` чисто (lint в проекте не установлен — проверка через tsc).
- [x] vitest 57/57: api.test, board.test, pages.test — включая существующий тест
      «fetchBoardStages → mock-fallback при ошибке» (не сломан, мок в pages.test
      без `demo` → бейдж не рендерится).
- [x] Живой прогон, бэкенд ЖИВ: доска с реальными данными (15/27 сделок по
      воронкам), бейджа нет, warn нет.
- [x] Живой прогон, бэкенд МЁРТВ (BACKEND_URL → дохлый порт): в SSR-логе
      `[api] fetchBoardStages: бэкенд недоступен (http://…/sales/board) …
      ECONNREFUSED`, на доске демо-сделка 0156 и над ней бейдж.

## ⚠ ДУБЛЬ (обнаружено постфактум, см. REPORTS.md 2026-07-04 05:46)
Та же задача уже закрыта sales-полосой коммитом `f50e753` (2026-07-03 08:26,
ветка `sales-2.0-redesign`) — их решение полнее (обёртка `fetchBoardResult` +
`demoData` для режима «Все вместе»/combinedStages + правки deals-workspace.tsx
и тестов), но БЕЗ `console.warn` на SSR (часть исходного запроса). Ветки
разошлись на `66f6487` (до PR#9), поэтому пересечение не было видно заранее.
**Рекомендация координатору:** при реконсиляции взять `f50e753` за основу,
портировать в неё только `console.warn` (2 строки); мой `1b9161b` на этой
ветке — не мержить как есть (типы `Stage.demo` конфликтуют с их `demoData`).

## Открытый хвост (решение координатора)
`fetchKpis`: живой бэкенд с ПУСТЫМ списком KPI тоже молча подменяется моком
(`data.length ? … : KPIS`, api.ts) — выглядит намеренным (нет засеянных планов),
не трогал. Если надо пометить и его — одна строка по образцу.

## PITFALLS-DISCOVERED

- Программный click по submit-кнопке React-формы (preview_click/dispatchEvent) не
  триггерит `onSubmit`. **ЛЕЧЕНИЕ:** `document.querySelector('form').requestSubmit()`
  через eval.
- Cookies на localhost НЕ привязаны к порту: httpOnly-сессия dev-логина с одного
  dev-сервера (:54748) действует на другом (:63873) — удобно для проверки страниц
  за логин-гейтом, когда бэкенд для самого логина недоступен.

---

STATE: COMPLETE

---

## АРБИТРАЖ КООРДИНАТОРА (2026-07-04)

Вердикт по NEEDS-ARB (дубль работы «честный fallback»):
1. **База — `f50e753`** (полоса sales, уже в origin/sales-2.0-redesign): реализация полнее
   (fetchBoardResult-обёртка + demoData для «Все вместе»), конфликт типов решён в её пользу.
2. **`1b9161b` (ветка `claude/trusting-germain-78c832`) НЕ мержить** — `Stage.demo` /
   `stages.some(demo)` конфликтует с demoData-пропом базы. Ветку можно ретайрить.
3. **Дельта к портированию** (микро-задача полосе sales, ~2 строки): `console.warn` с URL+ошибкой
   в catch `fetchBoardResult()` и `fetchKpis()` (api.ts) — явная часть исходного запроса
   оператора (различать fallback в SSR-логе). Внесено в бэклог полосы sales.

Причина дубля: ветка ответвилась от main (merge-base 66f6487) и не видела ушедшую вперёд
sales-2.0-redesign. Понижение риска — правило: перед стартом задачи в отдельной ветке/worktree
сверять «не закрыта ли задача в основной ветке» (git log --grep по ключевым словам + REPORTS.md).
