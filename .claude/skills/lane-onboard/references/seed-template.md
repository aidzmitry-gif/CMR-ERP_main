<!-- Транзитный засев полосы. НЕ коммитить. Заполни плейсхолдеры <…>, удали неподходящее. -->
# <Полоса> (<repo/submodule>) — засев

Ты — полоса **<Полоса>**, <субмодуль `modules/<x>` (<REPO>) | core/shared-kernel | прототипы в корне>.
Ветка суперпроекта: `sales-2.0-redesign`, cwd = корень суперпроекта; правки субмодуля — через `git -C modules/<x>`.

## Зона
- Бэк: `modules/<x>/**` <или core-пути>. Фронт: `frontend/src/app/<...>/**`, компоненты `<...>`.
- Схема БД `<schema>`, API-префикс `/<x>`.

## Состояние (ПРОВЕРЕНО по git+реестру)
- <HEAD субмодуля/линии, хеши; что сделано; что закоммичено vs незакоммичено — точно «кто где грязный»>.
- <Открытые хэндоффы/блокеры, если есть>.

## Хэндоффы (направления — не путать)
- Эмитишь: `<event>` → <модуль-подписчик>. Ждёшь: `<event>` от <модуль>.
- <Если единый писатель чего-то — указать; «X эмитит, Y проецирует», не наоборот>.

## Координация (канон)
- Реестр (ACTIVE-SESSIONS/DEPENDENCY-MAP/STATUS/счётчик миграций) и `.claude/settings.json` правит ТОЛЬКО
  координатор — пингуй. Писать тебе МОЖНО только в `coordination/.activity.local.md` и `PUSH-LOG.md` (авто).
- Миграции: голова **<NNNN>** (сверь `scripts/next_migration.py --peek`); номер бери через `next_migration.py`, НЕ руками.
- Не трогать: shared-kernel (`core/domain/models.py`: Sku/counterparty/ref_*), `core.services.stock`, `modules/integrations`
  (территория СИНК), чужие submodules, хотспоты (config/*, `frontend/src/lib/api.ts`) без захвата у координатора.
- Деньги — `Decimal(str(...))`, не float. Валюта — BYN через CurrencyProvider, не хардкод ₽.
- Push: `git add` ТОЛЬКО свои файлы по именам; НИКАКОГО amend/reset/rebase на общей ветке; cherry-pick своего
  на чистую ветку от origin; правка субмодуля = коммит + bump указателя. Push/commit — по явной просьбе оператора.

## Следующий шаг (выбор с оператором)
- <вариант A> / <вариант B>.

## Готово
Перед закрытием — сверься с `coordination/DoD.md` и доложи координатору строкой:
`КООРД: DONE <Полоса> — <суть> [DoD: ✓review ✓tests ✓lint ✓commit (+✓migration/✓security/✓depmap по триггеру)]`
(или `BLOCKED`/`NEEDS-MIG`/`NEEDS-ARB`/`INFO` вместо DONE).
