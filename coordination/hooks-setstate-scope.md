# Scope: hooks-setstate — починить react-hooks/set-state-in-effect (22 файла)

## Цель (Goal-Driven)
В 22 файлах ниже eslint даёт по 1 ошибке `react-hooks/set-state-in-effect` (всего 22).
Сделать так, чтобы `npx eslint <эти файлы>` = **0 ошибок** И `npx tsc --noEmit` = 0,
не меняя видимого поведения экранов.

## Файлы (ровно эти, по 1 ошибке в каждом)
```
src/components/deal-approvals.tsx
src/components/deal-contacts.tsx
src/components/deal-documents.tsx
src/components/deal-items.tsx
src/components/deal-messages.tsx
src/components/deal-tasks.tsx
src/components/erp/bom-panel.tsx
src/components/erp/claims-panel.tsx
src/components/erp/logistics-audit.tsx
src/components/erp/logistics-fleet.tsx
src/components/erp/logistics-insights.tsx
src/components/erp/logistics-scorecard.tsx
src/components/erp/logistics-tariffs.tsx
src/components/erp/logistics-tender.tsx
src/components/erp/module-board.tsx
src/components/erp/norms-table.tsx
src/components/erp/otk-panel.tsx
src/components/erp/vyrabotka-table.tsx
src/components/erp/zayavki-table.tsx
src/components/funnel/funnel-board.tsx
src/components/kanban/deals-workspace.tsx
src/components/theme-toggle.tsx
```

## Контекст
`react-hooks/set-state-in-effect` (React 19) ругается на синхронный `setState` в теле
`useEffect` — это вызывает каскадные ререндеры. Типичные корректные фиксы (выбирай по случаю,
НЕ слепо):
- Если стейт **производный** от пропсов/стейта — вычислять его прямо в рендере (или `useMemo`),
  а не хранить в state и пихать через effect.
- Если effect грузит данные и зовёт setState в `.then()`/async-колбэке — это нормально, ошибка
  обычно на **синхронном** setState в самом теле. Часто помогает обернуть инициализацию в
  ленивый `useState(() => ...)` либо убрать лишний effect.
- Большинство этих 22 — однотипные паттерны загрузки/инициализации. Разберись с первым-двумя,
  выведи паттерн, примени к остальным аккуратно.

⚠️ НЕ глушить через `// eslint-disable`. ⚠️ Поведение экранов сохрани 1:1 — это рабочие экраны
сделок/логистики/ERP. Если для какого-то файла честный фикс невозможен без смены поведения —
оставь его, доделай остальные, и в финале перечисли проблемные в status-файле.

## LOOP CONTRACT
- model: sonnet
- include: только 22 файла выше
- exclude: всё прочее (другие воркеры правят sprav-ai.tsx, leads-workspace.tsx, charts/page.tsx — НЕ трогать)
- budget: max_iterations=14, max_files_changed=22
- проверка (обе обязательны, из `frontend/`):
  - `npx eslint <22 файла>` → 0 ошибок (или прогнать `npx eslint .` и убедиться, что
    set-state-in-effect не осталось в твоих файлах)
  - `npx tsc --noEmit` → 0 ошибок
- stop: eslint=0 по твоим файлам И tsc=0 → COMPLETE. Иначе — NEEDS-ORCHESTRATOR-ANSWER
  с конкретикой по файлам, что не поддалось.

## node_modules (Windows-worktree)
В свежем worktree нет `frontend/node_modules`. Перед проверками подними junction:
```powershell
cmd /c mklink /J "frontend\node_modules" "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\frontend\node_modules"
```
Если уже есть — пропусти. node_modules коммитить НЕ нужно.
