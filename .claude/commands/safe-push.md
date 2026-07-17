---
description: Безопасный пуш своих коммитов в общую ветку — worktree от origin-tip, cherry-pick, верификация авторства, гарантированный cleanup
argument-hint: <ветка> [sha...]
---

Выполни безопасный пуш в общую ветку: $ARGUMENTS

1. Если коммиты двигали указатели submodule (`modules/*`) — СНАЧАЛА запушь репо
   субмодуля, потом супер-репо (иначе CI падает на gitlink).
2. Запусти:
   `powershell -ExecutionPolicy Bypass -File scripts/safe-push.ps1 -Branch <ветка>`
   (точечный набор коммитов: `-Commits sha1,sha2`). Скрипт сам: fetch → временный
   worktree от origin-tip → cherry-pick только своих → верификация авторства →
   push → cleanup. Любой сбой = ничего не запушено, главный чекаут не тронут.
3. Проверь вывод `OK old..new` и сообщи диапазон в отчёте. Строку пуша журналирует
   post-commit/pre-push хук координации (PUSH-LOG.md).
4. НЕ пушить в общие ветки мимо этого скрипта и НЕ выставлять `AIOS_ALLOW_PUSH=1`
   вручную — скрипт делает это сам только после верификации.
