# Scope: hooks-refs — починить react-hooks/refs в sprav-ai.tsx

## Цель (Goal-Driven)
`cd frontend; npx eslint src/components/erp/spravochniki/sprav-ai.tsx` сейчас даёт **11 ошибок
`react-hooks/refs`**. Сделать так, чтобы по этому файлу eslint = **0 ошибок** И
`npx tsc --noEmit` = 0, не меняя видимого поведения экрана.

## Контекст
Правило `react-hooks/refs` (React 19, eslint-plugin-react-hooks v6) запрещает читать/писать
`ref.current` во время рендера. Корректные места — внутри `useEffect`, обработчиков событий,
колбэков. Типичный фикс: перенести доступ к ref из тела компонента в effect/handler, либо
если значение нужно для рендера — это должно быть `useState`/производное, а не ref.

⚠️ НЕ глушить правило через `// eslint-disable` — это запрещено (нужен реальный фикс).
⚠️ Поведение экрана (AI-каталог справочников) менять НЕЛЬЗЯ — только привести работу с ref
к правилам. Если фикс требует изменить логику — сначала разберись, что ref реально делает.

## LOOP CONTRACT
- model: sonnet
- include: `frontend/src/components/erp/spravochniki/sprav-ai.tsx`
- exclude: всё остальное (другие воркеры правят свои файлы — НЕ трогать)
- budget: max_iterations=8, max_files_changed=1
- проверка (обе обязательны, гнать из `frontend/`):
  - `npx eslint src/components/erp/spravochniki/sprav-ai.tsx`  → 0 ошибок
  - `npx tsc --noEmit`  → 0 ошибок
- stop: если eslint=0 и tsc=0 — COMPLETE. Если фикс требует менять поведение/другие файлы —
  STATE: NEEDS-ORCHESTRATOR-ANSWER с описанием, что мешает.

## node_modules (важно для Windows-worktree)
В свежем worktree нет `frontend/node_modules` (он git-ignored). ESLint/tsc оттуда не запустятся.
Перед проверками поднять симлинк на node_modules основного чекаута:
```powershell
cmd /c mklink /J "frontend\node_modules" "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\frontend\node_modules"
```
Если junction уже есть — пропустить. Это локальный приём проверки, коммитить node_modules НЕ нужно.
