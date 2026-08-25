# Воркер: landed-duty-fact — пошлина в landed-preview сходится с фактом приёмки

## Цель (Goal-Driven)
Сделать так, чтобы **плановый предпросмотр** landed cost заказа (`GET /procurement/orders/{id}/landed-preview`)
сходился с **фактической** себестоимостью, зафиксированной на приёмке (`_fixate_landed_cost`, stage=`actual`).
Сейчас предпросмотр НЕ применяет пошлину ТН ВЭД вообще, хотя факт на приёмке её применяет — после
приёмки себестоимость «прыгает» вверх на величину пошлины, план и факт расходятся.

**Критерий готовности (ORACLE, уже написан координатором):**
`pytest tests/test_procurement_landed_duty_fact.py::test_landed_plan_fact_reconcile` = PASSED,
плюс `pytest tests/test_procurement_*.py` = 0 failed, `import main` = OK, `ruff check` = чисто.

⚠️ **НЕ трогай `tests/test_procurement_landed_duty_fact.py`** — это оракул координатора. Сделай его
зелёным, меняя КОД (`modules/procurement/routes.py`), а не тест. Ослаблять assert в оракуле нельзя.

## Контекст
РАБОЧАЯ ДИРЕКТОРИЯ: твой worktree (spawn_workers поставил cwd). НЕ упоминай путь главного репо,
НЕ делай `cd` туда. Все git-команды и коммиты — в текущем worktree.

- Submodule: `modules/procurement/` (ZAK-3.git) — коммить туда ОТДЕЛЬНО, потом bump gitlink в суперпроекте.
- Файл: `modules/procurement/routes.py`.
- Реальная история: коммит `feat(zak): пошлина ТН ВЭД в факт landed на приёмке (круг 4 B2)` (submodule
  ZAK-3) уже закрыл пошлину в `_fixate_landed_cost` (факт при реальной приёмке). Это НЕ трогать и НЕ дублировать.
  Оставшийся разрыв — в `landed_preview()` (роут `GET /orders/{order_id}/landed-preview`), который
  использует **другой, урезанный** путь расчёта (`_order_allocation()` напрямую, без пошлины).
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`.
- Деньги: `Decimal` внутри, `str`/JSON-safe на границе API/событий (см. `procurement.landed_cost.calculated`
  payload — `unit_landed_cost_byn (str)`). Валюта BYN. НЕ float во внутренних расчётах пошлины.

## Разбор текущего кода (заземление)

`_fixate_landed_cost()` (`modules/procurement/routes.py`, ~строки 446-517) — ФАКТ на приёмке:
```python
duty_inputs = await sku_master.landed_inputs_batch(
    session, [r["sku_code"] for r in res["lines"]], on_date
)
for r in res["lines"]:
    inp = duty_inputs.get(code)
    duty = inp.get("duty_pct") if inp else None
    duty_rate = Decimal(str(duty)) / Decimal("100") if duty is not None else Decimal("0")
    unit = (r["unit_landed_cost"] * (Decimal("1") + duty_rate)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    landed_total = (r["landed_total"] * (Decimal("1") + duty_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

`landed_preview()` (`modules/procurement/routes.py`, ~строки 737-762) — ПЛАН/предпросмотр, БЕЗ пошлины:
```python
@router.get("/orders/{order_id}/landed-preview")
async def landed_preview(order_id: int, session: AsyncSession = Depends(get_session)):
    """Предпросмотр распределения landed cost по позициям БЕЗ фиксации (live-пересчёт в редакторе).
    Тот же движок, что и на приёмке — фронт не считает сам."""   # ← НЕВЕРНО: пошлины тут нет
    order = await session.get(PurchaseOrder, order_id)
    ...
    res, _ = _order_allocation(lines, Decimal(order.freight_byn))
    return {
        ...
        "lines": [{"unit_landed_cost_byn": float(r["unit_landed_cost"]), "landed_total_byn": float(r["landed_total"]), ...}],
        "total_landed_byn": float(res["total_landed"]),
    }
```

`_order_allocation()` (~строка 346) — общий движок распределения фрахта (goods+фрахт), пошлину НЕ считает
(это намеренно — пошлина добавляется ПОВЕРХ него вызывающим кодом, как в `_fixate_landed_cost`).

## Шаг 1 — добавить пошлину в `landed_preview()`

По образцу `_fixate_landed_cost` (тот же батч-фасад, та же формула, тот же quantize):
1. Импортировать `from core.services import sku_master` (локальный импорт, как в `_fixate_landed_cost`/`_recompute_estimated_landed` — без цикла модулей).
2. После `res, _ = _order_allocation(lines, Decimal(order.freight_byn))` — получить `duty_inputs = await sku_master.landed_inputs_batch(session, [r["sku_code"] for r in res["lines"]])` (без `on_date` — заказ ещё не принят, дата приёмки неизвестна; дефолт фасада = сегодня, как и на приёмке для новых заказов).
3. На каждую строку `r` в `res["lines"]` — применить `duty_rate` (та же формула `Decimal(str(duty))/100`, `None`→`0`) к `unit_landed_cost` и `landed_total` с тем же `quantize` (`0.0001` для unit, `0.01` для total), как в `_fixate_landed_cost`.
4. Пересчитать `total_landed_byn` в ответе как сумму скорректированных `landed_total` по строкам (сейчас берётся `res["total_landed"]` без пошлины).
5. НЕ трогать `_order_allocation()` — это общий движок для обоих путей, пошлина остаётся ответственностью вызывающего (как задокументировано).
6. Обновить docstring `landed_preview` — убрать неверное «тот же движок, что и на приёмке» ИЛИ сделать его верным, добавив пошлину (предпочтительно второе).

## Шаг 2 — тест на не-оракул регресс (опционально, но желательно)
Если после Шага 1 остаётся время — добавь **отдельный** маленький regression-тест в
`tests/test_procurement_landed_cost.py` (НЕ в файл оракула), проверяющий что `landed-preview`
БЕЗ пошлины (нет тарифа/SKU в справочнике → `duty_pct=None`) не ломается (`unit_landed_cost_byn`
не меняется, когда `landed_inputs_batch` возвращает `None`/`{}` — honest-empty, не 0% силой).

## Запуск
```powershell
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
python -m pytest tests/test_procurement_landed_duty_fact.py -x -q
python -m pytest tests/test_procurement_*.py -q
python -c "import main"
ruff check modules/procurement/ tests/test_procurement_landed_duty_fact.py --line-length 100
```

## DoD
- `tests/test_procurement_landed_duty_fact.py::test_landed_plan_fact_reconcile` = PASSED, БЕЗ правок
  этого файла.
- `pytest tests/test_procurement_*.py` = 0 failed, `import main` = OK, `ruff check` = чисто.
- Коммит в `modules/procurement/` (submodule) → bump gitlink в суперпроекте.
- `STATE: COMPLETE` в `coordination/landed-duty-fact-status.md`.
- НЕ пушить. Без миграции (чисто расчётный путь, новых полей/таблиц не требуется).
