# Задание: hooks-setstate

Почини **22 ошибки `react-hooks/set-state-in-effect`** — ровно по 1 в каждом из 22 файлов,
список в `coordination/hooks-setstate-scope.md`.

Это правило React 19 про синхронный `setState` в теле `useEffect` (каскадные ререндеры).
Чини по сути: производный стейт → вычислять в рендере/useMemo; лишний init-effect → убрать
или ленивый `useState(() => ...)`. Разбери первые пару, выведи паттерн, аккуратно примени
к остальным. Поведение рабочих экранов (сделки/логистика/ERP) сохрани 1:1.

Полное ТЗ + node_modules-junction — в `coordination/hooks-setstate-scope.md`.
Запрещено глушить через `// eslint-disable`.

Готово, когда из `frontend/`:
- `npx eslint .` не показывает `set-state-in-effect` в твоих 22 файлах (0 по ним)
- `npx tsc --noEmit` = 0 ошибок
