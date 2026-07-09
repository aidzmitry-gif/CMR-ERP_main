# WIP triage - 2026-07-09

Контрольная карта текущего незакоммиченного WIP. Цель: разделить изменения на
безопасные инженерные пакеты и не смешать код приложения с мокапами/артефактами.

## Проверено

- Backend slice: `pytest -q tests/test_sales_db.py tests/test_sales_ai_call.py` - `50 passed`.
- Frontend slice: `npm --prefix frontend run test:run -- channels.test.tsx deal-card.test.tsx` - `2 files / 7 tests passed`.
- Ранее в этой ветке проходили `frontend typecheck`, `frontend lint` с предупреждениями и `next build`.

## Пакеты для раздельных коммитов

1. `connectors/*`
   - Добавляет `--test`, `--limit`, `NullStateStore`, `data/inbox/test/`.
   - Риск низкий/средний: важно отдельно прогнать живой smoke на dev-host, потому что это интеграция Bitrix/1C/Google.
   - Не смешивать с frontend и sales submodule.

2. Sales picker UI
   - Файлы: `frontend/src/components/calls/call-window.tsx`,
     `frontend/src/components/kanban/catalog-picker-modal.tsx`,
     `frontend/src/components/kanban/product-picker.tsx`,
     `frontend/src/components/kanban/deal-drawer-preview.tsx`,
     `frontend/src/lib/api.ts`.
   - `catalog-picker-modal.tsx` уже импортируется в call window и deal drawer.
   - Перед коммитом убрать случайный комментарий `ponytail` около `MIN_MARGIN_FLOOR_PCT`.
   - Проверки: frontend unit slice, `typecheck`, `lint`, `build`.

3. Deal card call action
   - Файлы: `frontend/src/components/channels.tsx`,
     `frontend/src/components/kanban/deal-card.tsx` и их тесты.
   - Смысл: кнопка звонка вынесена из `Link`, тест покрывает отсутствие nested button-in-anchor.
   - Можно коммитить отдельно от picker UI.

4. Sales backend KPI/SKU filter
   - Изменения внутри submodule `modules/sales`: `routes.py`, новый `kpi_facts.py`.
   - Родительский тест `tests/test_sales_db.py` зависит от этих изменений.
   - Коммитить нужно в два шага: сначала submodule `modules/sales`, потом pointer в parent repo.
   - Риск: `won_count`, `won_sum`, `avg_deal` сейчас считаются по `Deal.created_at`; для KPI месяца обычно правильнее `stage_changed_at` или дата закрытия. В коде уже есть примеры для ROP plan по `stage_changed_at`.

5. Marketing geo page
   - `frontend/src/app/erp/marketing/geo/page.tsx` подключен через sidebar.
   - Маленький placeholder-пакет, лучше отдельным коммитом.

6. ZAK previews/mockups
   - `zak-*.html` и большое число PNG/JPEG/HTML мокапов.
   - Держать отдельным design/mockup коммитом или архивировать; не смешивать с app code.

## Не коммитить в кодовый пакет

- `_docs_out/node_modules/`
- `_audit*.png`, `_shot*.png`, `live-*.jpeg`, preview screenshots
- `.playwright-mcp/`
- большие локальные зеркала/заметки вроде `obsidian/`, если нет отдельного решения по vault
- временные `.review/*` patch-файлы без явной цели

## Следующий безопасный порядок

1. Убрать мелкий мусорный комментарий в picker UI.
2. Закоммитить `DealCard/ChannelRow` отдельно.
3. Закоммитить picker UI отдельно после полного frontend gate.
4. Закоммитить `connectors --test` отдельно после smoke/CLI проверки.
5. Для `modules/sales` решить дату факта won KPI, затем submodule commit + parent pointer.
