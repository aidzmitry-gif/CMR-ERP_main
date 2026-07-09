# WIP triage - 2026-07-09

Контрольная карта текущего незакоммиченного WIP. Цель: разделить изменения на
безопасные инженерные пакеты и не смешать код приложения с мокапами/артефактами.

## Проверено

- Backend slice: `pytest -q tests/test_sales_db.py tests/test_sales_ai_call.py` - `50 passed`.
- Frontend slice: `npm --prefix frontend run test:run -- channels.test.tsx deal-card.test.tsx` - `2 files / 7 tests passed`.
- Frontend gate после picker/geo: `typecheck` - passed, `lint` - `0 errors / 57 warnings`,
  `next build` - passed (`115/115` pages).
- Connectors unit slice: `45 passed` (обычный Windows-run; sandbox падал на `os.replace` permission).

## Пакеты для раздельных коммитов

1. `connectors/*`
   - Добавляет `--test`, `--limit`, `NullStateStore`, `data/inbox/test/`.
   - Риск низкий/средний: важно отдельно прогнать живой smoke на dev-host, потому что это интеграция Bitrix/1C/Google.
   - Не смешивать с frontend и sales submodule.
   - Закрыто: `9ea9aae feat: add safe connector test mode`.

2. Sales picker UI
   - Файлы: `frontend/src/components/calls/call-window.tsx`,
     `frontend/src/components/kanban/catalog-picker-modal.tsx`,
     `frontend/src/components/kanban/product-picker.tsx`,
     `frontend/src/components/kanban/deal-drawer-preview.tsx`,
     `frontend/src/lib/api.ts`.
   - `catalog-picker-modal.tsx` уже импортируется в call window и deal drawer.
   - Перед коммитом убрать случайный комментарий `ponytail` около `MIN_MARGIN_FLOOR_PCT`.
   - Проверки: frontend unit slice, `typecheck`, `lint`, `build`.
   - Закрыто: `4a1635a feat: add compact sales catalog picker`.

3. Deal card call action
   - Файлы: `frontend/src/components/channels.tsx`,
     `frontend/src/components/kanban/deal-card.tsx` и их тесты.
   - Смысл: кнопка звонка вынесена из `Link`, тест покрывает отсутствие nested button-in-anchor.
   - Можно коммитить отдельно от picker UI.
   - Закрыто: `15ff75f fix: keep deal card actions outside links`.

4. Sales backend KPI/SKU filter
   - Изменения внутри submodule `modules/sales`: `routes.py`, новый `kpi_facts.py`.
   - Родительский тест `tests/test_sales_db.py` зависит от этих изменений.
   - Коммитить нужно в два шага: сначала submodule `modules/sales`, потом pointer в parent repo.
   - Риск был снят: `won_count`, `won_sum`, `avg_deal` переведены на `stage_changed_at`.
   - Закрыто: `modules/sales@9e7f8f3` + parent `9659e01 test: cover sales operational KPI facts`.

5. Marketing geo page
   - `frontend/src/app/erp/marketing/geo/page.tsx` подключен через sidebar.
   - Placeholder заменён на статический рабочий экран geo factory.
   - Закрыто: `533b8c8 feat: add marketing geo factory page`.

6. ZAK previews/mockups
   - `zak-*.html` и большое число PNG/JPEG/HTML мокапов.
   - Держать отдельным design/mockup коммитом или архивировать; не смешивать с app code.
   - Tracked `zak-*.html` закрыты отдельно: `7b25d33 design: refresh procurement preview flows`.

7. Module hygiene/context
   - Закрыто:
     - `15a921c docs: update HR module context` (`modules/hr@e4be466`).
     - `360e74e chore: update module hygiene metadata`
       (`modules/leads@590ba85`, `modules/service@3d33800`, `modules/wms@9833140`).

## Не коммитить в кодовый пакет

- `_docs_out/node_modules/`
- `_audit*.png`, `_shot*.png`, `live-*.jpeg`, preview screenshots
- `.playwright-mcp/`
- большие локальные зеркала/заметки вроде `obsidian/`, если нет отдельного решения по vault
- временные `.review/*` patch-файлы без явной цели

## Осталось после прохода

- `coordination/STATUS.md` - tracked WIP, вероятно текущий runtime/coordination state.
- Detached submodules:
  - `modules/finance`: только `__pycache__/`.
  - `modules/procurement`: только `__pycache__/`.
  - `modules/marketing`: `CLAUDE.md` + `__pycache__/`; коммитить лучше после checkout на нужную ветку.
- Большие untracked группы:
  - `obsidian/` - vault/зеркало знаний; не коммитить без отдельного решения по ownership.
  - `coordination/` - много scope/status/handoff файлов; нужен отдельный docs/coordination пакет.
  - Скриншоты и визуальные пруфы (`_audit-*`, `_shot*`, `live-*`, `screen-*`, `*_dark/light.png`) - artifact/design archive.
  - `.claude/skills/*` - локальные навыки Claude; не смешивать с app code.
  - `scripts/import_month.py`, `scripts/lane_check.py`, `scripts/lane_worktree.py`, `scripts/next_migration.py`,
    `tg_bridge.py`, `tg_notify_hook.py`, `tg_send_photo.py`, `tg_sessions.py` - source-ish, требуют отдельного ревью.

## Следующий безопасный порядок

1. Не трогать detached submodules, пока не выбран branch/remote flow.
2. Разобрать `coordination/STATUS.md` отдельно от generated coordination dump.
3. Принять решение по `obsidian/`: versioned vault или локальное зеркало.
4. Отдельно ревьюить source-ish scripts/Telegram bridge.
5. Скриншоты/HTML-мокапы архивировать или игнорировать только явными prefix-группами, не глобальным `*.png`/`*.html`.
