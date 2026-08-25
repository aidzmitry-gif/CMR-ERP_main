# Scope: sales-ux-nextstep

## LOOP CONTRACT
- include: frontend/src/app/crm/deals/, frontend/src/components/deal-edit-button.tsx, frontend/src/components/kanban/deal-drawer-preview.tsx, frontend/src/components/funnel/funnel-board.tsx, frontend/src/components/funnel/gate1-picker-modal.tsx, frontend/src/components/calls/call-window.tsx, frontend/src/lib/format.ts, frontend/src/lib/format.test.ts, frontend/src/lib/types.ts
- exclude: modules/, core/, config/, scripts/seed.py, migrations/
model: sonnet
- max_iterations: 8
- max_files_changed: 10
- stop_conditions:
  - tsc --noEmit = OK
  - npm run test:run = 0 failed (vitest, затронутые файлы)

## Ограничения
- FRONTEND-ONLY в суперпроекте — НЕ коммитить в submodule (modules/sales/ и др.), gitlink НЕ обновлять
- НЕ создавать и НЕ применять миграции Alembic — next_step остаётся String(128) на бэкенде
- Если нужна смена типа колонки — только флаг в coordination/sales-ux-nextstep-status.md (писать: RISK: DB migration needed)
- НЕ выбрасывать существующие блоки UI при редактировании компонентов
- НЕ пушить (пуш делает координатор)
- Gate 1 подбор — мокап с честной маркировкой (/* mockup */), демо-данные допустимы
