# Scope: hr-worktime-fe

## LOOP CONTRACT
- include:
  - frontend/src/app/erp/hr/worktime/page.tsx          (НОВЫЙ — обёртка AppShell)
  - frontend/src/components/erp/worktime-view.tsx       (НОВЫЙ — 3 экрана в табах, demo-данные)
  - frontend/src/components/sidebar.tsx                 (ТОЛЬКО добавить пункт в HR-подменю)
- exclude:
  - modules/**, core/, config/, migrations/**           (бэкенда/схемы НЕТ — фронт с demo-данными)
  - scripts/seed.py
model: sonnet
- max_iterations: 8
- max_files_changed: 3
- stop_conditions:
  - npx tsc --noEmit = 0 ошибок (в frontend/)
  - страница рендерится (dev-сервер отдаёт /erp/hr/worktime без ошибок)

## Ограничения
- Это РЕАЛЬНЫЕ страницы Next.js в приложении (App Router), НЕ HTML-мокап. Дизайн наследуется из `AppShell`
  (сайдбар/шапка/тема) — НЕ верстать свой шелл.
- Стиль view-компонента КОПИРОВАТЬ у `frontend/src/components/erp/office-claims-view.tsx`: `"use client"`,
  TS-интерфейсы, Tailwind-классы с `dark:`-вариантами, map'ы label/badge. Те же цвета/скругления/типографика.
- Demo-данные ВНУТРИ компонента (mock-массив, реальные ФИО как в системе). Бэкенда нет — никаких fetch к API
  (или honest-empty). НЕ выдумывать эндпоинты.
- НЕ пушить (пуш — координатор). Коммит в суперпроект (submodule-ей нет).
