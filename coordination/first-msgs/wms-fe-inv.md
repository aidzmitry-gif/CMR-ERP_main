# Воркер: wms-fe-inv — WMS Инвентаризация и остатки (frontend)

## Цель
Добавить UI страницы для управления складом: текущие остатки и история движений.
Критерий: `tsc --noEmit` = OK, `import main` = OK, страницы рендерятся без ошибок.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule WMS: `modules/wms/` (SKL-5.git) — НЕ трогать (только frontend)
- Существующие эндпоинты: читай `modules/wms/routes.py` — что доступно (stock, movements, receipts, tasks)
- Seed данные уже есть (locations, stock_movements, receipts, thresholds, tasks)
- Frontend: `frontend/src/app/erp/wms/` — что уже есть

## Шаг 1 — Читать существующее
- `modules/wms/routes.py` — список всех /wms эндпоинтов
- `frontend/src/app/erp/wms/` — структура WMS-фронта

## Шаг 2 — Страница «Остатки» frontend/src/app/erp/wms/stock/page.tsx
Компонент `frontend/src/components/erp/wms-stock-view.tsx`:
- Таблица: SKU код | Наименование | Зона/Ячейка | Кол-во | Резерв | Доступно | Пороговое значение
- Фильтр по зоне/ячейке
- Подсветка: если кол-во < порога → красная строка (предупреждение о нехватке)
- Кнопка «Обновить»

## Шаг 3 — Страница «Движения» frontend/src/app/erp/wms/movements/page.tsx
Компонент `frontend/src/components/erp/wms-movements-view.tsx`:
- Таблица: Дата | Тип (receipt/shipment/reserve/release) | SKU | Кол-во | Причина | Документ
- Тип с badge разными цветами
- Фильтр по типу и дате
- Пагинация (показывать последние 50)

## Шаг 4 — Страница «Приёмки» frontend/src/app/erp/wms/receipts/page.tsx (если нет)
Компонент `frontend/src/components/erp/wms-receipts-view.tsx`:
- Список приёмок: Номер | Статус | Поставщик | Дата | Позиций | PO-номер
- Клик по приёмке → детали позиций

## Проверка
```powershell
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"
python -c "import main"; echo "backend OK"
cd frontend; npx tsc --noEmit; cd ..
```

## DoD
- tsc --noEmit = OK + import main = OK
- Коммит в суперпроект (frontend-файлы)
- submodule modules/wms/ НЕ трогать
- НЕ пушить
- STATE: COMPLETE
