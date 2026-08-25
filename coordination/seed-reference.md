<!-- Транзитный засев новой полосы. Не коммитить. Координатор 2026-06-27 — сверено адверсариально (с правками). -->
# Справочники (reference-data) — новый чат

Ты — полоса **Справочники / reference-data** (core shared-kernel, MDM, registry-витрина). НЕ субмодуль — работаешь в корневом дереве. Ветка: `sales-2.0-redesign`, cwd = корень.

## Зона
- `core/domain/reference.py`, `core/domain/models.py` (ТОЛЬКО `Sku.category_id` — Sku ведёшь ты; остальную карточку SKU CRM делает как UI, не дублируйте), `core/runtime/reference_registry.py`, `core/runtime/reference_routes.py`, `core/services/reference_query.py`, `core/reference/` (+ аддитивно `core/runtime/{contract,core,system_routes,app}.py`).
- Фронт: `frontend/src/lib/reference-data*`, экраны справочников; `frontend/src/components/source-tag.tsx` (провенанс MDM/1С — ОБЩИЙ с CRM, согласуй).
- MDM-адаптер в ЯДРЕ: `core/services/reference_import.py` (refs-сторона импорта) + `tests/test_reference_*`.
- ⚠️ `modules/integrations/{service,client}.py` (коннектор 1С `OneCClient` + `sync_1c`) и `tests/test_integrations.py` — **территория СИНК-сессии** (`mdm-data-class-seam.md §4`), НЕ трогай. Граница: синк отдаёт `[{name,unp,id}]` → твой `core.services.reference_import`.

## Состояние (проверено git)
- Свежие твои коммиты на линии HEAD: `3d05e16` (свободные общие данные группы — Производитель/коробка/габариты), `c454b3d` (общие данные группы по умолч.: НДС/ед/страна), `8f4dbef` (code-review: страна из легаси JSONB, read-path устойчив к битым attributes), `9c43079` (фикс скролла справочников).
- Сделано (M1–M5 и дальше): гигиена/дедуп/аудит (M1), правила слияния survivorship (M2), мастер-данные номенклатуры + landed-фасад (M4), досье 360° (M5), синк ERP→1С (M3); план счетов РБ, регионы/города, ТН ВЭД ЕАЭС + ставки, группы номенклатуры (`category_id`), атрибуты группы (миграция 0055), богатая карточка номенклатуры, виды из 1С в дереве.
- Незакоммичено: `M frontend/src/components/source-tag.tsx` — ⚠️ ОБЩИЙ с CRM (провенанс SourceTag); перед коммитом сверь авторство, `git add` по имени, не утащи чужое.
- Твои миграции: 0037, 0039, 0040, 0049 (ТН ВЭД), 0050 (ТН ВЭД на группе), 0054, 0055.

## Координация (канон)
- Реестр (ACTIVE-SESSIONS/DEPENDENCY-MAP/STATUS/счётчик миграций) и `.claude/settings.json` — только координатор; пингуй. Писать тебе МОЖНО только в `.activity.local.md`/`PUSH-LOG.md` (авто).
- ⚠️ `core/domain/models.py` — shared-kernel ХОТСПОТ: меняешь схему Sku/counterparty/ref_* → ломаешь все модули; согласуй + миграция. `Sku.category_id` ведёшь ты.
- Миграции: голова 0055, следующий свободный 0057 (0056 за Складом/WMS). Номер бери у координатора.
- Сейм данных — `coordination/mdm-data-class-seam.md`: «Справочники» = registry-витрина (НЕ второе хранилище); JSONB не EAV; SCD2 `[start,end)`. Остатки/резервы — НЕ твои (операционные, 1С=истина).
- Не трогать чужое: submodules других полос (sales/finance/logistics/wms/procurement), `core.services.stock`.
- Push: cherry-pick ТОЛЬКО своих refs-коммитов на чистую ветку от origin (НЕ тащи security/CRM/coord-коммиты); никакого amend/reset/rebase на общей ветке.

## Следующий шаг (выбор с оператором)
- История SKU (SCD2-вьюшка), survivorship-CRUD (редактор правил слияния), редактор group-default атрибутов, дозаполнение карточки номенклатуры. Импорт ~4766 контрагентов 1С в MDM (backlog §5 шва — был откачен, согласуй с СИНК-сессией).
- В конце доложи координатору.
