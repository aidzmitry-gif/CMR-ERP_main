# zak-fe-ai — scope

## Задача (уровень 2: касаемые файлы + верификация)
Сверстать 2 статичных HTML-превью модуля закупок: `zak-ai-comms-preview.html` (AI-переписка с
поставщиками) и `zak-price-monitor-preview.html` (Мониторинг цен 1688/Taobao/Alibaba + проверка
контрагентов). Эталон хрома — `zak-cockpit-preview.html` (head + панель чатов + вкладки копируются
дословно). Полное ТЗ — `coordination/first-msgs/zak-fe-ai.md`.

Проверка: оба файла открываются без поломок; содержат скопированные из эталона `<head>`,
`<aside class="chatrail">`, блок вкладок (с верной активной вкладкой); переписка показывает тред с
переводом ИИ и черновиком ответа; мониторинг — watchlist по площадкам + реестр контрагентов. Самопроверка
через `python -m http.server` + grep (и глазами, если есть браузер).

## LOOP CONTRACT
```yaml
scope:
  include:
    - zak-ai-comms-preview.html
    - zak-price-monitor-preview.html
  read_only_reference:
    - zak-cockpit-preview.html
    - zak-preview-index.html
  exclude:
    - "zak-price-inquiry-preview.html"   # воркер zak-fe-process
    - "zak-board-preview.html"           # воркер zak-fe-process
    - "zak-shipment-preview.html"        # воркер zak-fe-logistics
    - "zak-landed-cost-preview.html"     # воркер zak-fe-logistics
    - "rop-*"
    - "frontend/**"
    - "modules/**"
    - "core/**"
    - "migrations/**"
    - "coordination/**"
    - "**/*.py"
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 4
  max_runtime_minutes: 30
  max_files_changed: 2
  max_consecutive_test_failures: 2
stop:
  - file_touched_outside_scope
  - need_to_modify_reference_file
  - product_behavior_ambiguous
report:
  destination: coordination/zak-fe-ai-status.md
```

## Acceptance gate
- [ ] `zak-ai-comms-preview.html`: полоса метрик ИИ, список диалогов, тред с пузырями (кит. текст +
      перевод ИИ под ним + исходящие brand), черновик ответа ИИ (violet dashed), блок «Аналитика беседы»
      (цена/срок/MOQ/предоплата/риск), блок «Документы».
- [ ] `zak-price-monitor-preview.html`: алерты цен, таблица watchlist (бейджи 1688/Taobao/Alibaba, ↑↓%
      цветом, спарклайны), реестр контрагентов с рейтингом ИИ (Надёжный/Осторожно/Риск), ИИ-блок.
- [ ] В обоих: `<head>`, `<aside class="chatrail">`, блок вкладок — дословно из cockpit; активна нужная
      вкладка; `pr-[92px]`; навигация на корректные `zak-*-preview.html`.
- [ ] Тронуты только 2 целевых файла; six-layer в коммите; status → `STATE: COMPLETE`.

## Anticipated failure modes
- Менять панель чатов/токены — НЕ надо, копируй дословно.
- pytest/npm нерелевантны и сломаются — НЕ гейтись, проверка визуальная/структурная.
- Забыть `pr-[92px]` → контент под рейкой чатов.
- Китайский текст без перевода ИИ под ним — обязателен перевод (это суть экрана).

## Образец визуала
`zak-cockpit-preview.html` — хром, карточки, бейджи, ИИ-блок, панель чатов (в cockpit уже есть мини-блоки
переписки и проверки контрагентов — разверни их до полноценных экранов). Эстетика ИИ-кокпита —
как в marketing-prototype/ (центр — AI-агенты).
