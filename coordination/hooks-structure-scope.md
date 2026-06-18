# Scope: hooks-structure — static-components + immutability (2 файла)

## Цель (Goal-Driven)
2 файла, 4 ошибки. Сделать `npx eslint <эти 2 файла>` = **0 ошибок** И `npx tsc --noEmit` = 0,
поведение экранов 1:1.

## Файлы и ошибки
1. `src/components/leads/leads-workspace.tsx` — **3× react-hooks/static-components**
   Компонент(ы) определены ВНУТРИ другого компонента → пересоздаются на каждый рендер.
   Фикс: вынести вложенные компоненты на верхний уровень модуля (или мемоизировать, если
   они замыкают пропсы — но предпочтительно вынести и передавать пропсами).
2. `src/app/design/charts/page.tsx` — **1× react-hooks/immutability** (строка ~231: `acc += len`)
   Реассайн переменной после завершения рендера. Фикс: пересчитать накопитель без мутации
   во время маппинга (напр. через `reduce`, или вычислить смещения заранее массивом), чтобы
   не было `acc +=` в теле, исполняемом при рендере.

## Контекст
- `static-components`: React 19 не любит компоненты, объявленные в теле другого компонента —
  они теряют идентичность между рендерами (ломает память/состояние дочернего дерева). Вынести наружу.
- `immutability`: правило ловит мутацию переменной, читаемой во время рендера. `acc += len`
  внутри `.map(...)` при рендере SVG-сегментов — классика. Переписать на чистый расчёт смещений.

⚠️ НЕ глушить через `// eslint-disable`. ⚠️ Графики/leads-экран должны выглядеть и работать так же.

## LOOP CONTRACT
- model: sonnet
- include: `frontend/src/components/leads/leads-workspace.tsx`, `frontend/src/app/design/charts/page.tsx`
- exclude: всё прочее (другие воркеры — НЕ трогать)
- budget: max_iterations=8, max_files_changed=2
- проверка (обе, из `frontend/`):
  - `npx eslint src/components/leads/leads-workspace.tsx src/app/design/charts/page.tsx` → 0 ошибок
  - `npx tsc --noEmit` → 0 ошибок
- stop: оба зелёные → COMPLETE; иначе NEEDS-ORCHESTRATOR-ANSWER.

## node_modules (Windows-worktree)
В свежем worktree нет `frontend/node_modules`. Перед проверками подними junction:
```powershell
cmd /c mklink /J "frontend\node_modules" "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\frontend\node_modules"
```
Если уже есть — пропусти. node_modules коммитить НЕ нужно.
