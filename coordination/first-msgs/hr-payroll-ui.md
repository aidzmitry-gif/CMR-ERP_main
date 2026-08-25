# Воркер: hr-payroll-ui — Ведомость зарплат: список по периодам + карточка сотрудника

## Цель (Goal-Driven)

Достроить UI ведомости зарплат в HR-модуле:
1. **Период-сводка** — агрегированный список начислений по периодам (`YYYY-MM`): итог BYN, количество сотрудников, статус (все выплачено / есть ожидающие).
2. **Карточка сотрудника** — при клике на строку периода → раскрывается список начислений конкретного сотрудника внутри периода (или фильтр по employee_id).
3. **Тонкий GET-агрегатор на backend** (если нужен): `GET /hr/payroll/summary?period=YYYY-MM` — список `{period, total_byn, count, pending_count}` по периодам. Добавить в `modules/hr/routes.py` и `modules/hr/schemas.py` (submodule modules/hr).

Критерий готовности: `pytest tests/test_hr_payroll.py tests/test_hr_payroll_list.py` = 0 failed,
`import main` = OK, `tsc --noEmit` = OK, `ruff check` чисто.

## Контекст

- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/hr/` (HR-10.git) — коммить туда ОТДЕЛЬНО, потом bump gitlink в суперпроекте
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`

### Уже существующие символы (читай перед правкой — НЕ выдумывай)

**Backend — `modules/hr/`:**
- `models.py`: `Employee` (id, full_name, position, department, status), `PayrollEntry` (id, employee_id, period: str "YYYY-MM", amount_byn: str, status: str "pending"|"paid")
- `schemas.py`: `PayrollAccrueIn`, `PayrollPayIn`, `PayrollEntryOut` (id, employee_id, period, amount_byn: str, status)
- `routes.py` — **уже есть все нужные эндпоинты**:
  - `GET /hr/payroll` — список с фильтрами `?employee_id=&period=&status=`
  - `GET /hr/payroll/{entry_id}` — одна запись
  - `POST /hr/payroll/accrue` — начисление (создаёт PayrollEntry + событие `hr.payroll.accrued`)
  - `POST /hr/payroll/pay` — выплата pending→paid + событие `hr.payroll.paid`
  - `GET /hr/employees` — список сотрудников

**Frontend — уже существуют:**
- `frontend/src/app/erp/hr/payroll/page.tsx` — заглушка-страница, рендерит `<HrPayrollView />`
- `frontend/src/components/erp/hr-payroll-view.tsx` — компонент с таблицей начислений, фильтром по статусу (all/pending/paid), формой начисления и кнопкой «Выплатить»

**Тесты — уже существуют:**
- `tests/test_hr_payroll.py` — тесты accrue/pay + outbox-события (5 тестов)
- `tests/test_hr_payroll_list.py` — тесты GET /hr/payroll (7 тестов)

### Что именно строить (delta от текущего состояния)

Текущий `HrPayrollView` — плоский список всех начислений. Нужно добавить:

1. **Период-сводку**: режим «Ведомость» — группировка начислений по периоду.
   Каждая строка: `период | кол-во сотрудников | итог BYN | ожидает/выплачено`.
   Клик раскрывает детали (строки сотрудников в этом периоде).

2. **Агрегатор на backend**: `GET /hr/payroll/summary` возвращает список `PayrollPeriodSummary`.
   Реализовать через Python (groupby по результату существующего `GET /hr/payroll`) — без сырого SQL,
   чтобы уложиться в SQLite dev-режим. Схема:
   ```
   class PayrollPeriodSummary(BaseModel):
       period: str        # "YYYY-MM"
       total_byn: str     # сумма всех amount_byn как str (Decimal)
       count: int         # кол-во записей
       pending_count: int # сколько со status="pending"
   ```

3. **Обновить `frontend/src/components/erp/hr-payroll-view.tsx`** — добавить вкладку/переключатель
   «Ведомость» (по периодам) vs «Детально» (текущий плоский вид). Ведомость: таблица периодов +
   раскрывающиеся строки с сотрудниками периода. Текущий код НЕ удалять — сохранить «Детально».

4. **Тест агрегатора** добавить в `tests/test_hr_payroll.py`:
   - `GET /hr/payroll/summary` → 200
   - После двух accrue за один период: count=2, total_byn = сумма обоих
   - pending_count корректно уменьшается после pay

## Шаг 1 — Схема PayrollPeriodSummary в modules/hr/schemas.py

Добавить в конец файла:
```python
class PayrollPeriodSummary(BaseModel):
    period: str        # "YYYY-MM"
    total_byn: str     # сумма amount_byn через Decimal, возвращать str
    count: int
    pending_count: int
```

## Шаг 2 — Эндпоинт GET /hr/payroll/summary в modules/hr/routes.py

Добавить ПЕРЕД `@router.get("/payroll/{entry_id}", ...)` (иначе FastAPI поглотит `/summary` как `entry_id`):

```python
from decimal import Decimal as D
from itertools import groupby

@router.get("/payroll/summary", response_model=list[PayrollPeriodSummary])
async def payroll_summary(session: AsyncSession = Depends(get_session)):
    """Сводка начислений по периодам: итог BYN, кол-во, ожидает."""
    rows = (
        await session.execute(select(PayrollEntry).order_by(PayrollEntry.period.asc()))
    ).scalars().all()
    result: list[PayrollPeriodSummary] = []
    for period, group in groupby(rows, key=lambda r: r.period):
        items = list(group)
        total = sum(D(r.amount_byn) for r in items)
        pending = sum(1 for r in items if r.status == "pending")
        result.append(PayrollPeriodSummary(
            period=period,
            total_byn=str(total),
            count=len(items),
            pending_count=pending,
        ))
    return result
```

Добавить `PayrollPeriodSummary` в импорт из `modules.hr.schemas` в `routes.py`.

## Шаг 3 — Обновить HrPayrollView (frontend/src/components/erp/hr-payroll-view.tsx)

Добавить:
- Интерфейс `PayrollPeriodSummary { period, total_byn, count, pending_count }`
- Состояние `viewMode: "summary" | "detail"` (по умолчанию `"summary"`)
- Два таба «Ведомость» / «Детально» в шапке
- В режиме `summary`: fetch `/api/hr/payroll/summary`, таблица периодов.
  Колонки: Период | Сотрудников | Итог BYN | Ожидает | Выплачено | [кнопка раскрыть]
- Раскрытие строки: fetch `/api/hr/payroll?period=YYYY-MM` → детальная таблица ниже строки
- В режиме `detail`: текущий плоский список (весь существующий код — не удалять)
- Цветовая индикация: если pending_count > 0 → жёлтый значок; если 0 → зелёный

## Шаг 4 — Тесты в tests/test_hr_payroll.py

Добавить в конец файла:
```python
async def test_payroll_summary_empty(api):
    """GET /hr/payroll/summary → 200 + пустой список."""
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    assert r.json() == []

async def test_payroll_summary_aggregates(api):
    """Два начисления за один период → count=2, total_byn = сумма."""
    emp1 = await _make_employee(api)
    emp2_r = await api.post("/hr/employees", json={"full_name": "Сидоров Сидор"})
    emp2 = emp2_r.json()["id"]
    await api.post("/hr/payroll/accrue", json={"employee_id": emp1, "period": "2026-10", "amount_byn": "1000.00"})
    await api.post("/hr/payroll/accrue", json={"employee_id": emp2, "period": "2026-10", "amount_byn": "2000.00"})
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    periods = {s["period"]: s for s in r.json()}
    assert "2026-10" in periods
    s = periods["2026-10"]
    assert s["count"] == 2
    from decimal import Decimal
    assert Decimal(s["total_byn"]) == Decimal("3000.00")
    assert s["pending_count"] == 2

async def test_payroll_summary_pending_decreases(api):
    """После pay pending_count уменьшается."""
    emp_id = await _make_employee(api)
    await api.post("/hr/payroll/accrue", json={"employee_id": emp_id, "period": "2026-11", "amount_byn": "500.00"})
    await api.post("/hr/payroll/pay", json={"employee_id": emp_id, "period": "2026-11"})
    r = await api.get("/hr/payroll/summary")
    assert r.status_code == 200
    periods = {s["period"]: s for s in r.json()}
    assert "2026-11" in periods
    assert periods["2026-11"]["pending_count"] == 0
```

## Запуск

```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"
$env:AIOS_ENVIRONMENT="dev"
$env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python -m pytest tests/test_hr_payroll.py tests/test_hr_payroll_list.py -x -q
python -c "import main"
ruff check modules/hr/ tests/test_hr_payroll.py tests/test_hr_payroll_list.py --line-length 100
# Frontend
Set-Location frontend
npx tsc --noEmit
Set-Location ..
```

## DoD

- `pytest tests/test_hr_payroll.py tests/test_hr_payroll_list.py` = 0 failed
- `import main` = OK
- `ruff check` чисто
- `tsc --noEmit` = OK
- Коммит в `modules/hr/` (submodule) с добавленными символами → bump gitlink в суперпроекте
- `STATE: COMPLETE` записать в `coordination/hr-payroll-ui-status.md`
- НЕ пушить
