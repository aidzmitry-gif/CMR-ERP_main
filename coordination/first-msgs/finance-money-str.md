# Воркер: finance-money-str — float→str для денег в API Finance

## Цель (Goal-Driven)
Конвертировать все money-поля в API-слое модуля Finance из `float` в `str`
(Decimal→str, BYN-форматирование). DB-колонки уже `Numeric(14,2)` — менять схему НЕ нужно.
Критерий готовности: `pytest tests/test_finance*.py` = 0 failed (включая снятый xfail
`test_money_outputs_use_str_not_float_scan`), `import main` = OK, `ruff` = чисто, `tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/finance/` (fin-7.git) — коммить ТУДА отдельно, потом bump gitlink в суперпроекте
- Файлы модуля:
  - `modules/finance/schemas.py` — Pydantic-схемы (PaymentCreate, PaymentOut, AllocationCreate,
    AllocationOut, PaymentDetail, BankAccountCreate, BankAccountUpdate, BankAccountOut, PnlOut)
  - `modules/finance/routes.py` — HTTP-API; функция `_enrich()` и роуты bank-accounts возвращают
    `float(p.amount)`, `float(obj.opening_balance)`, `float(outstanding)` напрямую в dict
  - `modules/finance/summary.py`, `aging.py`, `cashflow.py`, `margin.py`, `cost_center.py`,
    `reconcile.py` — вспомогательные функции, тоже возвращают float-поля
  - `modules/finance/models.py` — ORM (Payment, BankAccount, PaymentAllocation):
    `amount` = `Numeric(14,2)`, `opening_balance` = `Numeric(14,2)` — БД уже Numeric, НЕ Float
  - `frontend/src/components/erp/finance-view.tsx` — единственный фронт-компонент Finance
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`

## ⚠️ Важно перед началом

**ПРОВЕРЬ ТИПЫ КОЛОНОК БД**: убедись, что в `models.py` все денежные колонки — `Numeric`
(не `Float`). Если найдёшь `Float` в моделях — занеси в `coordination/finance-money-str-status.md`
раздел `SCHEMA-RISK: <поле>` и НЕ пиши миграцию самостоятельно. Текущие данные — `Numeric(14,2)`
для `amount`, `amount_orig`, `opening_balance` — всё ОК, миграция НЕ нужна.

**ПОСЛЕ КАЖДОГО ИЗМЕНЁННОГО ПОЛЯ** добавляй строку в `coordination/finance-money-str-status.md`:
```
CHANGED: <файл> <поле> :: before=float, after=str (BYN)
```
Это нужно координатору для ⚠️ REVIEW денег собственника.

## Шаг 1 — Pydantic-схемы: float → str в modules/finance/schemas.py

Заменить все `float`-аннотации money-полей на `str`. Для правильной сериализации `Decimal`→`str`
добавить `field_serializer` или `model_validator` — либо использовать `Annotated` с кастомным типом.

**Конкретные поля для замены:**

В `PaymentCreate`:
- `amount: float = 0` → `amount: str = "0.00"`

В `PaymentOut`:
- `amount: float` → `amount: str`
- `outstanding: float | None = None` → `outstanding: str | None = None`

В `AllocationCreate`:
- `amount: float` → `amount: str`

В `AllocationOut`:
- `amount: float` → `amount: str`

В `BankAccountCreate`:
- `opening_balance: float = 0` → `opening_balance: str = "0.00"`

В `BankAccountUpdate`:
- `opening_balance: float | None = None` → `opening_balance: str | None = None`

В `BankAccountOut`:
- `opening_balance: float` → `opening_balance: str`

Для корректной сериализации ORM Decimal → str в `PaymentOut`, `AllocationOut`, `BankAccountOut`
(с `model_config = ConfigDict(from_attributes=True)`) используй `field_serializer`:
```python
from pydantic import field_serializer
from decimal import Decimal

@field_serializer("amount")
def serialize_amount(self, v) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))
```

## Шаг 2 — routes.py: убрать float() из _enrich() и bank-account роутов

Функция `_enrich()` (строки 436-448) напрямую возвращает `float(p.amount)`, `float(outstanding)`.
Заменить на `str(Decimal(str(p.amount)).quantize(Decimal("0.01")))`.

Аналогично в `list_bank_accounts`, `create_bank_account`, `update_bank_account` — убрать
`float(a.opening_balance)` и `float(obj.opening_balance)`.

В `create_payment` (routes.py строки 493-509): `Decimal(str(payload.amount))` уже работает,
т.к. payload.amount теперь `str`.

В `create_allocation` (routes.py): `Decimal(str(payload.amount))` — аналогично.

## Шаг 3 — summary.py, aging.py, cashflow.py, margin.py, cost_center.py

Каждая из этих функций возвращает dict с float-значениями денег.
Обход: для каждой функции пройдись по возвращаемым dict-значениям и замени
`float(val)` / `Decimal(...)` на `str(Decimal(str(val)).quantize(Decimal("0.01")))`.

Конкретно в каждом файле читай что возвращает функция и список полей-денег фиксируй
в статус-файл (`CHANGED: ...` строками).

## Шаг 4 — frontend: finance-view.tsx — принять str вместо number

Файл: `frontend/src/components/erp/finance-view.tsx`

**Интерфейсы, которые надо обновить (заменить `number` → `string`):**

```typescript
interface Payment {
  amount: string;          // было: number
  outstanding: string | null;  // было: number | null
}

interface BankAccount {
  opening_balance: string;    // было: number
}

interface FinanceSummary {
  margin: {
    revenue: string;    // было: number
    landed: string;
    landed_gross?: string;
    claim_refund?: string;
    freight: string;
    gross: string;
    pct: string | null;   // было: number | null (% — оставить как number если приходит number; проверь summary.py)
  };
  cash: {
    inflow: string;
    outflow: string;
    net: string;
    received: string;
    pending_receivable: string;
    freight_refund: string;
  };
  costs: { kind: string; label: string; amount: string }[];
}

interface AgingSide {
  buckets: Record<string, string>;  // было: number
  total: string;
}

interface CashflowWeek {
  inflow: string; outflow: string; net: string; cumulative: string;
}
interface CashflowBucket {
  inflow: string; outflow: string; net: string; cumulative: string;
}
interface CashflowResp {
  opening_balance: string;       // было: number
  not_dated: { inflow: string; outflow: string };
}

interface MarginRow {
  revenue: string; landed: string; freight: string; gross: string;
  pct: string | null;
}

interface ReconDealResp {
  finance_landed: string;
  facade_landed: string | null;
  delta: string | null;
  revenue: string;
  gross_finance: string;
}

interface ReconResp {
  matched: { ref: string; amount: string; counterparty_ref: string | null }[];
  only_in_erp: { ref: string; amount: string; counterparty_ref: string | null }[];
  only_in_1c: { ref: string | null; amount: string; counterparty_ref: string | null }[];
}
```

**Потребители — обновить:**

- `formatByn(p.amount)` — `formatByn` принимает number. Обернуть: `formatByn(parseFloat(p.amount))`.
  Это корректно: parseFloat строки "1234.56" даёт точное число (без накопления ошибки, т.к. строка
  уже пришла из Decimal→str без float-промежуточного).
- Проверки `p.amount >= 0`, `s.cash.net >= 0`, `row.gross >= 0`, `resp.delta !== 0` и т.п. —
  заменить на `parseFloat(p.amount) >= 0` и т.д.
- `String(p.outstanding ?? p.amount)` в строке setAllocAmt — оставить как есть (уже строка).
- `Number(allocAmt)` в onAllocate — остаётся (это пользовательский ввод).
- `data.revenue === "0.00"` — уже работает.
- `(w.inflow / max) * 50` — заменить на `(parseFloat(w.inflow) / max) * 50` и т.п.

**Правило:** везде где раньше было `formatByn(val)` с val: number, теперь
`formatByn(parseFloat(strVal))`. Не менять бизнес-логику, только тип.

## Шаг 5 — Тесты

### 5a. Снять xfail с существующего теста
В `tests/test_finance.py` найди `test_money_outputs_use_str_not_float_scan` (строки ~1217-1242).
Убрать декоратор `@pytest.mark.xfail(...)`. Расширить тест: проверить также
`PaymentOut.amount`, `AllocationOut.amount`, `BankAccountOut.opening_balance`.

### 5b. Добавить тесты в tests/test_finance.py
```python
async def test_payment_api_amount_is_string(session, api):
    """PaymentOut.amount — строка, не float."""
    session.add(Payment(ref="T-STR", amount=Decimal("999.99"), kind="receivable", status="pending"))
    await session.commit()
    r = await api.get("/finance/payments")
    rows = r.json()
    assert len(rows) == 1
    assert isinstance(rows[0]["amount"], str), "amount должен быть строкой"
    assert rows[0]["amount"] == "999.99"


async def test_bank_account_opening_balance_is_string(session, api):
    """BankAccountOut.opening_balance — строка."""
    r = await api.post("/finance/bank-accounts", json={
        "code": "test-main", "title": "Тест", "currency": "BYN", "opening_balance": "5000.00"
    })
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["opening_balance"], str), "opening_balance должен быть строкой"
    assert body["opening_balance"] == "5000.00"


async def test_allocation_amount_is_string(session, api):
    """AllocationOut.amount — строка."""
    session.add(Payment(ref="T-ALLOC", amount=Decimal("200.00"), kind="receivable", status="pending"))
    await session.commit()
    pid = (await session.execute(select(Payment.id))).scalar_one()
    r = await api.post(f"/finance/payments/{pid}/allocations", json={"amount": "100.00"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["amount"], str), "allocation amount должен быть строкой"


async def test_payment_amount_roundtrip_no_float_error(session, api):
    """Деньги проходят сквозь API без float-дрейфа."""
    precise = "1234567.89"
    session.add(Payment(ref="T-PRECISE", amount=Decimal(precise), kind="receivable", status="pending"))
    await session.commit()
    r = await api.get("/finance/payments")
    row = r.json()[0]
    assert Decimal(row["amount"]) == Decimal(precise), "float-дрейф недопустим для денег собственника"
```

## Запуск
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python scripts/seed.py
python -m pytest tests/test_finance.py tests/test_finance_pnl.py tests/test_finance_cashflow.py tests/test_finance_balance.py -x -q
python -c "import main; print('OK')"
ruff check modules/finance/ tests/test_finance.py tests/test_finance_pnl.py tests/test_finance_cashflow.py tests/test_finance_balance.py --line-length 100
cd frontend; npx tsc --noEmit; cd ..
```

## DoD
- `pytest tests/test_finance*.py` = 0 failed (включая снятый xfail)
- `import main` = OK
- `ruff` = чисто
- `tsc --noEmit` = OK
- Все CHANGED-записи занесены в `coordination/finance-money-str-status.md`
- Коммит в `modules/finance/` (submodule fin-7) → bump gitlink в суперпроекте
- `STATE: COMPLETE` в `coordination/finance-money-str-status.md`
- НЕ пушить
