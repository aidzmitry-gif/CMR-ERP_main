# Воркер: zak-cost-fe — Калькулятор себестоимости Закупки (frontend)

## Цель
Перенести HTML-прототип `zak-cost-calc-preview.html` в Next.js: страница расчёта
предварительной себестоимости позиции (маршрут Китай→Минск).
Критерий: страница рендерится без ошибок, `tsc --noEmit` = OK, `import main` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- HTML-прототип: `zak-cost-calc-preview.html` в корне проекта — ПРОЧИТАЙ его для понимания UI
- Submodule: `modules/procurement/` (ZAK-3.git) — НЕ трогать, только frontend
- Frontend only — нет новых backend-эндпоинтов, нет миграций

## Что делает калькулятор (из HTML-прототипа)
Пользователь вводит:
- Цена FOB (USD) за единицу
- Количество (шт)
- Вес брутто (кг)
- Объём (м³)
- Ставка фрахта (USD/м³ или USD/кг, выбор)
- % пошлины (из ТН ВЭД, вручную)
- Курс USD/BYN (с буфером +10%)

Калькулятор считает:
- Стоимость товара (FOB × qty)
- Фрахт (по объёму или весу)
- Пошлина (% от FOB)
- Брокерские (фиксировано или %)
- Итоговая себестоимость BYN
- Себестоимость на единицу BYN

## Шаг 1 — Компонент
`frontend/src/components/erp/procurement-cost-calc.tsx`
- Клиентский компонент ("use client")
- Все вычисления на клиенте (нет API-запросов)
- Поля ввода с валидацией
- Результаты в реальном времени (пересчёт при изменении любого поля)
- Числа с двумя знаками после запятой

## Шаг 2 — Страница
`frontend/src/app/erp/procurement/cost-calc/page.tsx`
- Использует AppShell (как другие страницы ERP)
- Заголовок «Калькулятор себестоимости»

## Шаг 3 — Проверить
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"
python -c "import main"; echo "OK"
cd frontend; npx tsc --noEmit 2>&1; cd ..
```

## DoD
- tsc --noEmit = OK
- import main = OK
- Коммит в суперпроект (frontend-файлы)
- Submodule НЕ трогать (frontend only)
- НЕ пушить
- STATE: COMPLETE
