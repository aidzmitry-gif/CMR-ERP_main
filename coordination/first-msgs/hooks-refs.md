# Задание: hooks-refs

Почини **11 ошибок `react-hooks/refs`** в одном файле:
`frontend/src/components/erp/spravochniki/sprav-ai.tsx`.

Это новые строгие правила React 19 — нельзя читать/писать `ref.current` во время рендера.
Перенеси доступ к ref в `useEffect`/обработчики событий; если значение нужно для рендера —
это должно быть состояние, а не ref. Поведение экрана (AI-каталог справочников) сохрани 1:1.

Полное ТЗ, критерий приёмки и приём с node_modules-junction — в
`coordination/hooks-refs-scope.md`. Запрещено глушить правило через `// eslint-disable`.

Готово, когда из `frontend/`:
- `npx eslint src/components/erp/spravochniki/sprav-ai.tsx` = 0 ошибок
- `npx tsc --noEmit` = 0 ошибок
