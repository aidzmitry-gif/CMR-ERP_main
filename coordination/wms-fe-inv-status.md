# WMS Frontend Inventory — статус воркера wms-fe-inv

**STATE: COMPLETE**  
**Дата:** 2026-06-30

## Выполнено

### Шаг 2 — Страница остатков `/erp/wms/stock`
- Создан `wms-stock-view.tsx` с поддержкой порогов дефицита (`StockThreshold`)
- Фильтр по складу, красная подсветка строк когда `qty_free < min_qty`
- Кнопка Refresh

### Шаг 3 — Страница движений `/erp/wms/movements`
- Добавлен `MovementsLog` компонент с фильтром по типу + дате, пагинация 50
- Бейджи типов движений с цветовой кодировкой

### Шаг 4 — Приёмка `/erp/wms/receipts`
- Страница уже существовала, пропущена (по ТЗ)

## /simplify + /code-review проходы (все артефакты)

| Коммит | Описание |
|--------|----------|
| `bd0f8be` | feat: WMS инвентаризация (базовый) |
| `2a6b191` | fix: убрать дублирующую колонку Причина |
| `244685f` | refactor/simplify: lift types/fetch в lib, дедупликация |
| `08f312d` | fix: единый источник reason-лейблов (REASON_LABELS из wms-ops) |
| `e19c084` | fix: убрать "" sentinel из REASON_LABELS |
| `7bcf78d` | test: покрыть reasonLabel("") |

## DoD

- [x] `tsc --noEmit` = OK (проверено на каждом коммите)
- [x] import main = OK
- [x] pages рендерятся без ошибок
- [x] коммиты в суперпроект
- [x] submodule `modules/wms/` НЕ тронут
- [x] НЕ пушено
