# Задание: hooks-structure

Почини 4 структурные react-hooks ошибки в 2 файлах:
- `frontend/src/components/leads/leads-workspace.tsx` — 3× `static-components`
  (вложенные компоненты → вынести на верхний уровень модуля).
- `frontend/src/app/design/charts/page.tsx` — 1× `immutability`
  (строка ~231 `acc += len` после рендера → переписать накопитель без мутации, напр. reduce).

Правила React 19. Поведение экранов (leads / графики дизайн-системы) сохрани 1:1.
Полное ТЗ + node_modules-junction — в `coordination/hooks-structure-scope.md`.
Запрещено глушить через `// eslint-disable`.

Готово, когда из `frontend/`:
- `npx eslint src/components/leads/leads-workspace.tsx src/app/design/charts/page.tsx` = 0 ошибок
- `npx tsc --noEmit` = 0 ошибок
