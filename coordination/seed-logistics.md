<!-- Транзитный засев для переоткрытия полосы. Не коммитить. Сгенерирован координатором 2026-06-27, сверен адверсариально. -->
# Логистика (LOG-6) — переоткрытие

Ты — полоса **Логистика**, submodule **LOG-6** (`modules/logistics`). Открыта заново под координацию флота. Ветка суперпроекта: `sales-2.0-redesign`. Запускайся из корня суперпроекта (cwd = корень), правки субмодуля — через `git -C modules/logistics`.

## Зона
- `modules/logistics/**` (модель, роуты, события); фронт `frontend/src/app/erp/logistics/**`, `frontend/src/components/erp/logistics-*.tsx`, `frontend/src/lib/logistics-*.ts`.
- Схема БД `logistics`, API-префикс `/logistics`. Версия 0.4.0 (доставка РБ/РФ, импорт из Китая, перевозчики+тарифы, парк, scorecard, аудит счётов, тендер).

## Состояние (проверено в коде/git)
- LOG-6 HEAD `50b9043` — запушен в origin/main: эмит `logistics.freight.cost` (доставка, amount>0) и `logistics.freight.audit_refund` (аудит счёта, variance>0). Тесты 15+19 passed, ruff чист.
- ⚠️ **Финансы (fin-7 278dadd) проецируют ТОЛЬКО `freight.cost`** (Payment kind=freight). **Проекция `audit_refund` — ОТКРЫТА**: твоя сторона+тест готовы, finance ещё НЕ подписан на freight_refund. Это задача finance-чата, НЕ твоя.
- Отозвана ошибочная связка `import.arrived`→WMS (двойной учёт): приход импорта делает `procurement.received`→wms; `logistics.import.*` — только информационные эмиты (routes.py:359, подписчика нет). НЕ предлагай эмит импорта под склад.

## Рабочее дерево (незакоммичено)
- `M modules/logistics/routes.py`, `M modules/logistics/CLAUDE.md` — твои, в субмодуле.
- `M tests/test_links.py` (суперпроект) — твой тест audit_refund; коммить `git add` ТОЛЬКО по имени (в дереве лежат чужие незакоммиченные правки finance/sales/frontend — не `add .`).
- `coordination/DEPENDENCY-MAP.md` — **НЕ коммить и НЕ мержить сам**: карту/реестр ведёт координатор. Пингуй его вписать в §2 новые эмиты (freight.cost, freight.audit_refund).

## Хэндоффы (направления — не путать)
- Логистика **ЭМИТИТ** → Финансы **ПОДПИСЫВАЕТСЯ**: `freight.cost` `{deal_id,ref,carrier,amount,entity_ref:"shipment:{id}"}`; `freight.audit_refund` `{shipment_code,carrier,amount,entity_ref:"audit:{id}"}`.
- Sales→Логистика: `sales.document.posted`(order)→Shipment. Office→Логистика: `logistics.delivery.requested`. Логистика→Sales: `logistics.shipment.delivered`. Логистика→Office: `delivery.tracking/delivered`.
- Финансы — **единый писатель** fin-7. Нужна правка finance — пингуй finance-чат, сам не пиши.

## Координация (канон)
- Реестр (`ACTIVE-SESSIONS.md`/`DEPENDENCY-MAP.md`/`STATUS.md`/счётчик миграций) и `.claude/settings.json` правит **ТОЛЬКО координатор** — пингуй. Писать МОЖНО только в `coordination/.activity.local.md` и `coordination/PUSH-LOG.md` (авто, git-хуки).
- Миграции: голова **0055**, 0056 за Складом/WMS, 0057 ориентир для импорта логистики — **номер бери у координатора**, не сам.
- Не трогать: `core/services/*`, `modules/integrations`, shared-kernel (`core/domain/models.py::Sku`, counterparty, ref_*), чужие фронт-воркеры.
- Push: коммить мелко в субмодуль; пуш — cherry-pick ТОЛЬКО своего коммита на чистую ветку от origin; **никакого amend/reset/rebase на общей ветке** (гард в `.githooks/prepare-commit-msg`). Правка субмодуля = коммит в его репо + bump указателя. Push/commit — по явной просьбе.

## Следующий шаг (на выбор)
1. **Углубить тендер/scorecard** (бэк, самодостаточно): веса оценок per-carrier (OTD/брак/претензии), ranking best-fit.
2. **Живой фронт 6 вкладок** (Доставка/Импорт/Перевозчики/Парк/Тендер/Расходы) из макета `modules/logistics/ui/logistics-module.html` → React `frontend/src/app/erp/logistics/**`; API `/logistics/*` готовы.

В конце доложи координатору: что сделано, хеши, нужен ли номер миграции/захват хотспота.
