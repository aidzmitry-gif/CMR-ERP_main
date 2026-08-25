# board-stage-move — scope

## Задача (уровень 2: касаемые файлы + верификация)

В `sales-board-mockup.html` переписать `drawerStage()` так, чтобы кнопка «→ Следующая стадия» в drawer реально перемещала карточку в следующую колонку воронки (или обновляла модель и перерисовывала через renderBoard), обновляла стадию, закрывала drawer и показывала toast. Не двигать дальше терминальной стадии. Верификация: `node ".claude/skills/ui-crawl/scripts/handler-audit.mjs" sales-board-mockup.html` зелёный + (если есть браузер) ручная проверка на :8899.

## LOOP CONTRACT

```yaml
scope:
  include:
    - sales-board-mockup.html
  exclude:
    - "**/*.py"
    - sales-card-full.html
    - sales-call-popup.html
    - sales-docs-purge.html
    - core/**
    - modules/**
    - coordination/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 4
  max_runtime_minutes: 20
  max_files_changed: 1
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/board-stage-move-status.md
```

## Acceptance gate
- [ ] `drawerStage()` перемещает карточку в следующую колонку воронки (DOM или через renderBoard)
- [ ] Стадия/бейдж карточки обновляются; drawer закрывается; toast «Стадия → X»
- [ ] На терминальной стадии карточка не двигается (toast сообщает)
- [ ] `node ".claude/skills/ui-crawl/scripts/handler-audit.mjs" sales-board-mockup.html` → MISSING: none ✓, JS OK ✓
- [ ] Тронут только `sales-board-mockup.html`
- [ ] Six-layer в теле коммита; коммит локальный, без push
- [ ] Status-файл заканчивается баннером `STATE: COMPLETE`

## Anticipated failure modes
- Карточка определяется не по той стадии (читать из DOM-колонки, а не из бейджа) — Class A
- Несколько видов доски (стадии/даты): перемещение ломает не-стадийный вид — обработать ветку
- Регэксп/строки с кириллицей в названиях стадий — следить за точным совпадением
