# Воркер: sales-rop-plan — РОП: план/факт таблица менеджеров

## Цель
Добавить на страницу /crm/rop вкладку «План/Факт» — таблица показателей менеджеров
с планом и фактом за текущий месяц.
Критерий: `pytest tests/test_rop_plan.py` = 0 failed, `tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule sales: `modules/sales/` (CRM.git)
- Текущий РОП: читай `frontend/src/app/crm/rop/` — что уже есть
- Backend sales: `modules/sales/routes.py` — есть ли /crm/rop/* эндпоинты
- Auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev

## Шаг 1 — Читать существующее
- `frontend/src/app/crm/rop/` — структура страниц РОП
- `modules/sales/routes.py` — ищи `/rop/` эндпоинты
- `modules/sales/models.py` — есть ли KpiTarget / ManagerTarget

## Шаг 2 — Эндпоинт план/факт (если нет)
```
GET /crm/rop/plan-fact?period=YYYY-MM
```
Ответ:
```json
{
  "period": "2026-06",
  "managers": [
    {
      "name": "Иванов А.",
      "plan_deals": 10,
      "fact_deals": 7,
      "plan_revenue": "50000.00",
      "fact_revenue": "34500.00",
      "conversion_pct": 23.5
    }
  ]
}
```
Если модели для планов нет — вернуть данные из seed/fake (честно обозначить в UI).

## Шаг 3 — UI компонент
`frontend/src/components/crm/rop-plan-fact.tsx`
- Таблица: Менеджер | План сделок | Факт | % выполнения | План выручки | Факт выручки | % выручки
- % выполнения: зелёный ≥100%, жёлтый 70-99%, красный <70%
- Фильтр по месяцу (DatePicker)

## Шаг 4 — Добавить вкладку в /crm/rop страницу

## Шаг 5 — Тест tests/test_rop_plan.py
- GET /crm/rop/plan-fact → 200 + managers array
- Если нет менеджеров → пустой массив (не 500)
- import main OK

## DoD
- pytest зелёный + tsc --noEmit + ruff
- Коммит в modules/sales/ (если была правка бэка) → bump gitlink; или только суперпроект (если только фронт)
- НЕ пушить
- STATE: COMPLETE
