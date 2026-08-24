# docs-trash — scope

## Задача (уровень 2: касаемые файлы + верификация)

Связать пометки на удаление из карточки сделки с модулем «Архив документов» через localStorage (`'docTrash'`). В `sales-card-full.html` писать/удалять записи в markDoc/unmarkDoc/markVer/unmarkVer; в `sales-docs-purge.html` читать ключ при загрузке (с демо-fallback) и обновлять в restore/purge. Верификация: node handler-audit зелёный по обоим файлам + (если есть браузер) сквозной сценарий пометка→архив на :8899.

## LOOP CONTRACT

```yaml
scope:
  include:
    - sales-card-full.html
    - sales-docs-purge.html
  exclude:
    - "**/*.py"
    - sales-board-mockup.html
    - sales-call-popup.html
    - core/**
    - modules/**
    - coordination/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 25
  max_files_changed: 2
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - product_behavior_ambiguous
report:
  destination: coordination/docs-trash-status.md
```

## Acceptance gate
- [ ] markDoc/markVer пишут запись в localStorage['docTrash']; unmarkDoc/unmarkVer удаляют её
- [ ] sales-docs-purge.html при загрузке читает 'docTrash' и рендерит; пусто → демо-fallback
- [ ] restore(id)/purge(id) обновляют localStorage и список
- [ ] localStorage обёрнут в try/catch (не падать)
- [ ] `node ".claude/skills/ui-crawl/scripts/handler-audit.mjs" sales-card-full.html sales-docs-purge.html` → оба MISSING: none ✓, JS OK ✓
- [ ] Тронуты только эти два файла
- [ ] Six-layer в теле коммита; коммит локальный, без push
- [ ] Status-файл заканчивается баннером `STATE: COMPLETE`

## Anticipated failure modes
- Несовпадение id при mark/unmark → дубли или «не удаляется» (использовать стабильный ключ) — Class B
- render() в карточке пересобирает DOM — следить, что запись в localStorage делается в самой функции mark*, а не в разметке — Class A
- Существующий демо-fallback затирает реальные данные — читать localStorage ПЕРВЫМ, демо только если пусто
