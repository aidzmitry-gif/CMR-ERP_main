# zak-fe-process — scope

## Задача (уровень 2: касаемые файлы + верификация)
Сверстать 2 статичных HTML-превью модуля закупок: `zak-price-inquiry-preview.html` (Запросы цены,
sales↔закупки) и `zak-board-preview.html` (Воронка закупок, канбан 9 стадий). Эталон хрома —
`zak-cockpit-preview.html` (head + панель чатов + вкладки копируются дословно). Полное ТЗ — в
`coordination/first-msgs/zak-fe-process.md`.

Проверка: оба файла открываются в браузере без поломок; содержат скопированные из эталона `<head>`,
`<aside class="chatrail">` и блок вкладок (с правильной активной вкладкой); воронка — ровно 9 стадий
из `stages.py`. Самопроверка через `python -m http.server` + grep ключевых блоков (и глазами, если есть браузер).

## LOOP CONTRACT
```yaml
scope:
  include:
    - zak-price-inquiry-preview.html
    - zak-board-preview.html
  read_only_reference:           # читать как образец, НЕ менять
    - zak-cockpit-preview.html
    - zak-preview-index.html
  exclude:
    - "zak-shipment-preview.html"        # воркер zak-fe-logistics
    - "zak-landed-cost-preview.html"     # воркер zak-fe-logistics
    - "zak-ai-comms-preview.html"        # воркер zak-fe-ai
    - "zak-price-monitor-preview.html"   # воркер zak-fe-ai
    - "rop-*"                            # чужие прототипы
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
  - need_to_modify_reference_file       # cockpit/index → НЕ менять
  - product_behavior_ambiguous
report:
  destination: coordination/zak-fe-process-status.md
```

## Acceptance gate
- [ ] `zak-price-inquiry-preview.html`: двухпанельный макет (список запросов + детальная карточка),
      статусы-бейджи, блок «уточнение у поставщиков» с ценами ¥ и сроками, блок «ответ продавцу», ИИ-блок.
- [ ] `zak-board-preview.html`: канбан из 9 колонок с цветами/названиями РОВНО из `stages.py`, карточки
      заявок с тегом-источником (под сделку / пополнение), счётчики и суммы по колонкам, ИИ-плашка.
- [ ] В обоих: `<head>`, `<aside class="chatrail">`, блок вкладок — дословно из cockpit; активна нужная
      вкладка; контейнер `pr-[92px]`; навигация ведёт на корректные `zak-*-preview.html`.
- [ ] Тронуты только 2 целевых файла; six-layer в коммите; status → `STATE: COMPLETE`.

## Anticipated failure modes
- Захочется «улучшить» панель чатов или токены — НЕ надо, копируй из эталона дословно (единый вид важнее).
- pytest/npm не нужны и сломаются (это не Python/Node-таск) — НЕ гейтись на них, проверка визуальная/структурная.
- Забыть `pr-[92px]` на контейнере → контент уедет под рейку чатов. Проверь.
- Соблазн поменять `zak-cockpit-preview.html`/`zak-preview-index.html` — они read-only, НЕ трогать.

## Образец визуала
`zak-cockpit-preview.html` (корень) — хром, карточки, бейджи, ИИ-блок, панель чатов.
Стадии воронки — `stages.py` из репозитория модуля ZAK-3 (9 стадий, id/title/color перечислены в first-msg).
