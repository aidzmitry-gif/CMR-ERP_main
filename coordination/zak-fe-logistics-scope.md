# zak-fe-logistics — scope

## Задача (уровень 2: касаемые файлы + верификация)
Сверстать 2 статичных HTML-превью модуля закупок: `zak-shipment-preview.html` (Планирование машины,
вехи Китай→Минск) и `zak-landed-cost-preview.html` (Себестоимость импорта). Эталон хрома —
`zak-cockpit-preview.html` (head + панель чатов + вкладки копируются дословно). Полное ТЗ —
`coordination/first-msgs/zak-fe-logistics.md`.

Проверка: оба файла открываются без поломок; содержат скопированные из эталона `<head>`,
`<aside class="chatrail">`, блок вкладок (с верной активной вкладкой); машина имеет 7 вех в правильном
порядке; себестоимость показывает инвойс + доп.расходы + landed unit cost. Самопроверка через
`python -m http.server` + grep (и глазами, если есть браузер).

## LOOP CONTRACT
```yaml
scope:
  include:
    - zak-shipment-preview.html
    - zak-landed-cost-preview.html
  read_only_reference:
    - zak-cockpit-preview.html
    - zak-preview-index.html
  exclude:
    - "zak-price-inquiry-preview.html"   # воркер zak-fe-process
    - "zak-board-preview.html"           # воркер zak-fe-process
    - "zak-ai-comms-preview.html"        # воркер zak-fe-ai
    - "zak-price-monitor-preview.html"   # воркер zak-fe-ai
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
  destination: coordination/zak-fe-logistics-status.md
```

## Acceptance gate
- [ ] `zak-shipment-preview.html`: 3–4 машины, у каждой горизонтальный таймлайн из 7 вех (правильный
      порядок/подписи/цвета: пройдено=emerald, текущее=цвет вехи, будущее=slate-200); одна машина
      развёрнута (таблица заявок + индикатор загрузки объём/вес + план/факт); ИИ-блок.
- [ ] `zak-landed-cost-preview.html`: переключатель предв./итоговая, блок инвойса, блок доп.расходов
      (с «НДС возмещаемый — не в себестоимости»), база распределения, таблица landed unit cost (¥ и BYN), ИИ-блок.
- [ ] В обоих: `<head>`, `<aside class="chatrail">`, блок вкладок — дословно из cockpit; активна нужная
      вкладка; `pr-[92px]`; навигация на корректные `zak-*-preview.html`.
- [ ] Тронуты только 2 целевых файла; six-layer в коммите; status → `STATE: COMPLETE`.

## Anticipated failure modes
- Менять панель чатов/токены — НЕ надо, копируй дословно.
- pytest/npm нерелевантны и сломаются — НЕ гейтись, проверка визуальная/структурная.
- Забыть `pr-[92px]` → контент под рейкой чатов.
- Порядок вех перепутан — строго ① Выкуп → ② Производство → ③ Склад Китай → ④ Проверка → ⑤ Отправка →
  ⑥ Таможня Минск → ⑦ Склад Минск.
- Включить возмещаемый НДС в себестоимость — НЕЛЬЗЯ (он помечается «не в себестоимости»).

## Образец визуала
`zak-cockpit-preview.html` — хром, карточки, бейджи, ИИ-блок, панель чатов, мини-таймлайн машин
(в cockpit уже есть упрощённый — разверни его до полноценного экрана). Контекст landed cost —
docs/landed-cost.md в репозитории модуля ZAK-3.
