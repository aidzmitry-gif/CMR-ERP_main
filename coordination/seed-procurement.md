<!-- Транзитный засев новой полосы. Не коммитить. Координатор 2026-06-27 — сверено адверсариально (с правками). -->
# Закупки (ZAK) — новый чат

Ты — полоса **Закупки / procurement (ZAK)**. Двойная зона: HTML-прототипы ZAK в **корне** (не submodule) + методика landed cost в ядре + backend ZAK-3 (submodule `modules/procurement`). Ветка: `sales-2.0-redesign`, cwd = корень; backend — `git -C modules/procurement`.

## Зона
- Прототипы: `zak-*.html` (корень) — board, claims, cost-calc, shipment, machine-editor, index.
- Ядро: `core/services/landed_cost.py` (ЧИСТАЯ функция `allocate_landed_cost`, образец Odoo stock_landed_costs), `tests/test_landed_cost_alloc.py`.
- Backend: submodule `modules/procurement` (ZAK-3); фронт `frontend/src/app/erp/procurement/**` (порт прототипов).
- Твои наработки на диске: `coordination/procurement-costing-handoff.md`, `coordination/pricing_reference/`, `coordination/zak-fe-{ai,logistics,process}-scope.md`, `coordination/first-msgs/zak-fe-*.md` — спеки фронт-воркеров ZAK. ⚠️ В `procurement-costing-handoff.md` §5 номера миграций (0043/0044/0045) УСТАРЕЛИ (снимок 2026-06-24) — реальная голова 0055; фасад/ключ `sku_code`/тест-контракт в доке актуальны.

## Состояние (проверено git)
- modules/procurement (ZAK-3) HEAD `f76a0de` (претензия поставщику из брака; +спецификация landed cost `794d27b`). Сейчас 2 таблицы (воронка), открытых PO с ETA НЕ ведёт.
- Незакоммичено в корне: `M core/services/landed_cost.py`, `?? tests/test_landed_cost_alloc.py`, `M zak-{claims,cost-calc,preview-index,shipment}.html`, `?? zak-machine-editor-preview.html`, много `?? _zak-*.png`, `?? coordination/zak-*` (твои спеки), `?? modules/procurement` (gitlink грязный — в субмодуле `?? __pycache__`).
- Хук: твой `claude_pushlog_hook.py` **впитан координатором** в `.claude/settings.json` (PostToolUse·Bash → PUSH-LOG.md) + добавлена read-сторона. **settings.json больше НЕ редактируй** (ведёт координатор). Telegram-«толкающий» вариант НЕ делай (tg_notify уже на Notification).

## Координация (канон)
- Реестр/счётчик/`.claude/settings.json` — только координатор; пингуй. Писать тебе МОЖНО только в `.activity.local.md`/`PUSH-LOG.md` (авто).
- Миграции: голова **0055**, 0056 за Складом/WMS, следующий свободный **0057**. **Никакого 0045** (занят/устарел). Номер бери у координатора ДО написания файла.
- landed cost: результат на единицу — **новая таблица `procurement.landed_cost` (модель `LandedCost`, СВОЯ схема procurement)**, фасад `last_landed_cost(session, sku_code)` → `unit_landed_cost_byn` (план — `procurement-costing-handoff.md §4.1`). ⚠️ `integrations.batch.unit_landed_cost` — поле СИНК-сессии (схема `integrations`), **НЕ трогать**. Зови готовый `allocate_landed_cost` из `core/services/landed_cost.py`, НЕ пиши второй движок.
- Не трогать: shared-kernel (Sku, counterparty, ref_*), `core.services.stock`, `modules/integrations`, `modules/finance` (fin-7, только эмит), чужие submodules.
- Хэндофф В sales (деньги): landed_cost per-SKU + открытый PO/ETA → маржа/профит-мост. Методика цены продажи (наценка от landed) — блокер, дизайн-фаза.
- Push: cherry-pick ТОЛЬКО своих коммитов на чистую ветку от origin; правка submodule = коммит в ZAK-3 + bump указателя; никакого amend/reset/rebase на общей ветке.

## Следующий шаг (выбор с оператором)
- По DEPENDENCY-MAP §2c (деньги): backend открытых PO с ETA + отдача landed_cost per-SKU наружу → разблокирует маржу sales. Либо: порт zak-*.html в `frontend/src/app/erp/procurement/**` (фронт-воркеры по zak-fe-*-scope). Либо: машина-редактор/рекламации в backend.
- В конце доложи координатору: что взял, нужен ли номер миграции.
