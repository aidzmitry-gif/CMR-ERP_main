# rop-stages — scope

## Задача (уровень 2: касаемые файлы + верификация)

Собрать demo-экран РОП «Этапы воронки · старение сделок» под `/crm/rop/stages`:
страница + свой файл данных. Стиль — как эталон `frontend/src/app/crm/rop/cash/page.tsx`.
Верификация: `npx tsc --noEmit` в `frontend` — 0 ошибок, маршрут компилируется.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/crm/rop/stages/page.tsx        # СОЗДАТЬ
    - frontend/src/lib/rop-stages-data.ts             # СОЗДАТЬ
  exclude:
    - frontend/src/components/rop/**      # ui.tsx и rop-tabs.tsx — ТОЛЬКО ЧИТАТЬ, не менять
    - frontend/src/components/sidebar.tsx # уже содержит пункт (не трогать)
    - frontend/src/lib/rop-data.ts        # чужой файл — не трогать
    - frontend/src/app/crm/rop/**         # другие экраны РОП — не трогать
    - modules/**
    - config/**
    - migrations/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 4
  max_runtime_minutes: 25
  max_files_changed: 2
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - tsc_red_after_4_iters
  - design_ambiguous
report:
  destination: coordination/rop-stages-status.md
```

## Acceptance gate

- [ ] Созданы РОВНО 2 файла: `app/crm/rop/stages/page.tsx` + `lib/rop-stages-data.ts`
- [ ] Маршрут `/crm/rop/stages` рендерит серверный компонент (без `"use client"`, без хуков/onClick)
- [ ] Использованы примитивы `@/components/rop/ui` (Card, Caption, Tag, Bar, Dot, Avatar) и палитры
      TEXT_TONE/BAR_TONE/TAG_TONE — БЕЗ хардкода hex
- [ ] `<RopTabs active="stages" />` (ключ уже в union — не править rop-tabs.tsx)
- [ ] `AppShell crumbs={["CRM", "РОП", "Этапы воронки"]}`
- [ ] `npx tsc --noEmit` (в `frontend`) → 0 ошибок
- [ ] Тронуты ТОЛЬКО 2 файла скоупа; shared не изменены (`git status`)
- [ ] Six-layer в теле коммита; status-файл заканчивается баннером `STATE: COMPLETE`

## Anticipated failure modes
- Нет `node_modules` в worktree → `tsc` не запускается (Class D). Лечение — junction (см. first-msg).
- Импорт типа `Tone` — из `@/lib/rop-data` (type-only) либо локальный union.
- Попытка править rop-tabs/sidebar — ЗАПРЕЩЕНО, ключ уже есть.
