# chats-panel-fe — scope

## Задача (уровень 2: касаемые файлы + верификация)

Реализовать **SALES-49**: панель «Чаты и дела» (`components/chats-panel.tsx`) сворачивается в
узкую рейку (только аватарка контрагента + красный бейдж количества непрочитанных), а при
наведении мышью плавно раскрывается полностью **поверх доски** (overlay, не раздвигая канбан).
Эталон поведения — `mockup_Сделки_2.0.html` (правая панель). Только этот один компонент.

Проверка: `npx vitest run src/components/chats-panel.test.tsx` зелёный + `npm run lint` чисто.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/components/chats-panel.tsx
    - frontend/src/components/chats-panel.test.tsx
  exclude:
    - frontend/src/lib/api.ts          # общий: НЕ менять (поле unread добавит бэкенд-воркер)
    - frontend/src/lib/types.ts        # общий: НЕ менять
    - frontend/src/lib/format.ts
    - frontend/src/components/kanban/** # чужой воркер (deals-board-fe)
    - frontend/src/components/funnel/**
    - frontend/src/components/sidebar.tsx
    - frontend/src/app/**
    - modules/**
    - migrations/**
    - "**/*.py"
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 4
  max_runtime_minutes: 25
  max_files_changed: 2
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - need_to_modify_shared_file        # api.ts/types.ts → NEEDS-ORCHESTRATOR-ANSWER
  - product_behavior_ambiguous
report:
  destination: coordination/chats-panel-fe-status.md
```

## Acceptance gate

- [ ] Свёрнутое состояние (по умолчанию): видны только аватарки контрагентов + красный бейдж
      непрочитанных; панель узкая (~64–68px).
- [ ] По наведению на панель она раскрывается до ~300px **поверх** контента (overlay, без reflow
      доски) и показывает название контрагента + последнее сообщение; уводишь курсор — сворачивается.
- [ ] Поведение раскрытия — чистый CSS `:hover` (без JS-стейта на ширину); бейдж непрочитанных
      виден и в свёрнутом виде.
- [ ] Счётчик непрочитанных берётся из необязательного поля диалога (если бэкенд его отдаёт);
      **общий тип `ChatItem` НЕ менять** — читать `unread` как опциональное (`item.unread ?? 0`,
      при отсутствии — бейдж скрыт).
- [ ] `npx vitest run src/components/chats-panel.test.tsx` → 0 (рендер свёрнутой панели: есть
      аватарки; бейдж появляется, когда у диалога есть `unread > 0`).
- [ ] `npm run lint` — чисто по `chats-panel.tsx`.
- [ ] Тронут только `chats-panel.tsx` (+ его тест); six-layer в коммите; status → `STATE: COMPLETE`.

## Anticipated failure modes
- Захочется добавить `unread` в общий `ChatItem`/`api.ts` — НЕ делай (это задача бэкенда/другого
  воркера). Читай поле опционально без правки общего типа. Если кажется, что иначе никак — STOP,
  `NEEDS-ORCHESTRATOR-ANSWER`.
- `frontend/node_modules` нет в worktree → один раз `npm install` в `frontend/` перед vitest/lint.
- `npm run build` сломан на чужом `crypto/page.tsx` — не гейтись на build, проверка через vitest+lint.

## Образец визуала
`mockup_Сделки_2.0.html` (корень репо), правая панель «Чаты и дела»: свёрнутая рейка с бейджами
(СМ², ГА¹, ТЗ³) и раскрытие по наведению. CSS-подход к рейке/наведению можно взять оттуда
(`aside.chats` / `.chatsInner` / `.chat .av .badge`).
