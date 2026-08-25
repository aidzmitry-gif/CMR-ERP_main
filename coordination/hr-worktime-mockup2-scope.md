# Scope: hr-worktime-mockup

## LOOP CONTRACT
- include:
  - hr-worktime.html            (НОВЫЙ self-contained мокап в КОРНЕ суперпроекта, как sales-*.html)
- exclude:
  - modules/**                  (НЕ бэкенд — это html-first МОКАП до Gate 1)
  - migrations/**               (миграций нет)
  - frontend/**                 (порт на Next.js — после Gate 1, отдельная полоса)
  - core/, config/, scripts/seed.py
model: sonnet
- max_iterations: 8
- max_files_changed: 2
- stop_conditions:
  - hr-worktime.html открывается в браузере без JS-ошибок
  - все кнопки/окна кликаются (self-check по skill ui-crawl)
  - обе темы (light C / dark D) переключаются тумблером

## Ограничения
- Это HTML-FIRST МОКАП (skill html-first) — НИКАКОГО бэкенда/схемы/миграций/Next.js. Только один
  self-contained `.html` (inline CSS/JS, без сборки), кликабельный, в корне репо.
- Не выдумывай данные модели — бери структуру из `coordination/spec-hr-worktime-tabel.md` и xlsx-табеля.
- 2 темы (дизайн-система C светлая по умолчанию + D тёмная), тоггл — как в существующих sales-*.html.
- Demo-данные: 20 сотрудников из `config/access.py::USERS` (реальные ФИО/должности/роли).
- НЕ пушить (пуш — координатор). Коммит в суперпроект (submodule-ей нет).
