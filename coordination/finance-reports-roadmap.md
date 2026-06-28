# Финансовые отчёты — roadmap (Финансы → координатор)

> Полоса **finance** (session `ce567d7c`). Создано 2026-06-28 после ТЗ-Р3.
> **Цель:** дать собственнику 4 канонических финансовых отчёта (P&L, платёжный
> календарь, ДДС, баланс) в управленческом виде, без дублирования ledger 1С.

## Принципы

1. **«1С = ledger, finance = операционка».** Полные бухотчёты по двойной записи остаются в 1С. Из ERP — управленческие срезы по фактам-проводкам (`finance.payment`) + читать пасс-через из 1С там, где нужно (банк-сальдо, баланс).
2. **Honest-empty.** Нет источника → плашка, не нулевая выдумка.
3. **BYN на хранении, валюты сохраняем в `amount_orig`.**
4. **Push не делать**, миграции через `scripts/next_migration.py finance "..."`, коммиты по именам.

## Текущее состояние (после Р3)

| Отчёт | Готовность | Что уже работает |
|---|---|---|
| **Платёжный календарь** | 80% | `cashflow-forecast` понедельно; due_date+статусы; po_planned в оттоке |
| **P&L** | 40% | revenue/COGS(landed−claim_refund)/freight; `/finance/summary.margin` |
| **ДДС** | 50% | `/finance/summary.cash` — приток/отток/сальдо; opening через paid receivable−paid expenses |
| **Баланс** | 15% | AR/AP из aging; запасы через `core.services.stock`; денежных счетов и ОС нет |

## Предлагаемые ТЗ (по убыванию окупаемости)

### ТЗ-Р4 — Платёжный календарь до прод-готовности (3–4 ч)

**FIN-R4 пункты:**
- **R4-1** Дневная гранулярность: `cashflow.py` параметр `mode=week|day`; роут `/finance/cashflow-forecast?mode=day&days=30`.
- **R4-2** Таблица `finance.bank_account` (id, code, title, currency, opening_balance_at_date) + миграция.
- **R4-3** Колонка `Payment.account_id` (FK) + миграция; default — основной счёт.
- **R4-4** Эндпоинт `/finance/bank-accounts` (CRUD min) + переключатель в UI.
- **R4-5** UI: новая вкладка «Календарь» (день × счёт, цвета приток/отток, разворот по платежам).

**Источники событий** — все уже есть в Р3. Без внешних блокеров.

### ТЗ-Р5 — P&L (нужен HR + опц. вручную) (4–6 ч)

**FIN-R5 пункты:**
- **R5-1** Новые `kind`: `payroll`, `opex`, `tax`, `bank_fee` (свободная строка — без миграции).
- **R5-2** Подписки: `hr.payroll.accrued` → `Payment(kind=payroll, status=pending, due_date=...)`; `hr.payroll.paid` → авто `paid`. **Блокирует HR — нужно открыть полосу payroll и согласовать события.**
- **R5-3** `POST /finance/payments` уже принимает kind свободной строкой → opex/tax вводятся вручную UI «Косвенные расходы».
- **R5-4** Эндпоинт `/finance/pnl?from=&to=`: revenue / COGS / gross / opex / payroll / tax / net_income (без амортизации — отдельным kind, если появится модуль ОС).
- **R5-5** UI вкладка «P&L» с таблицей период × показатель; экспорт CSV.
- **R5-6** Recognition: ловить `sales.deal.handoff` (контракт уже есть) → отделять `revenue_recognized` от `receivable` — для аккуратной выручки «по отгрузке». Опционально.

**Зависит от:** полоса HR (события зарплаты), решение координатора — нужен ли strict accrual или достаточно cash-basis.

### ТЗ-Р6 — ДДС с разделением видов деятельности (2–3 ч)

**FIN-R6 пункты:**
- **R6-1** Колонка `Payment.activity_section` (32) с дефолтом по kind: `receivable/freight/landed/payroll/opex/claim_refund → operating`; покупка ОС → `investing`; кредиты/дивиденды → `financing`. Миграция.
- **R6-2** Эндпоинт `/finance/cash-flow-statement?from=&to=` — 3 секции (operating/investing/financing), opening/closing.
- **R6-3** Расширение `OneCGateway` (аддитивно, СТРОГО ЧТЕНИЕ): `fetch_bank_balance(account_code) -> dict | None`. Согласовать с полосой Синк.
- **R6-4** Использовать `fetch_bank_balance` для `opening` (вместо paid-вычисления); fail-soft → старый opening + плашка.
- **R6-5** UI вкладка «ДДС» с 3 секциями и сравнением «opening из 1С vs опер-расчёт».

**Зависит от:** полоса Синк (1С-фасад), пакет работ R5 (нужны kinds payroll/opex для корректной операционной секции).

### ТЗ-Р7 — Управленческий мини-баланс + полный пасс-через 1С (3–4 ч)

**FIN-R7 пункты:**
- **R7-1** Эндпоинт `/finance/balance-management` (управленческий): денежные счета (Σ bank_account.balance) + дебиторка (AR) + запасы (WMS valued_balances) − кредиторка (AP) − авансы клиентов = чистый оборотный капитал.
- **R7-2** `OneCGateway.fetch_balance_sheet(date) -> dict | None` (аддитивно, СТРОГО ЧТЕНИЕ).
- **R7-3** Эндпоинт `/finance/balance-1c?date=` — пасс-через бухбаланс из 1С, fail-soft.
- **R7-4** UI вкладка «Баланс»: 2 колонки — «Управленческий» / «1С (бух)»; дельта между ними как «несверено».
- **R7-5** Авансы клиентов: `receivable status=paid` но `sales.deal.handoff` не наступил → отдельный сегмент пассива. Требует ловить handoff.

**Зависит от:** R4 (bank_account для денег), R6 (activity_section), Синк (fetch_balance_sheet), Sales (deal.handoff — контракт уже есть).

## Что нужно от координатора

1. **Решение по очерёдности.** Моя рекомендация — последовательно Р4 → Р5 → Р6 → Р7 (по убыванию окупаемости и нарастанию блокеров).
2. **Открыть HR-полосу payroll** (для Р5) и согласовать события `hr.payroll.accrued/paid`.
3. **Открыть Синк-полосу** (для Р6/Р7) с тремя расширениями `OneCGateway` (СТРОГО чтение): `fetch_payments` (уже в Protocol), `fetch_bank_balance` (Р6), `fetch_balance_sheet` (Р7).
4. **Решение управленческого аккранта vs cash-basis** для P&L:
   - Cash-basis (проще): доход = `receivable status=paid`, расход = `landed status=paid`.
   - Accrual (точнее, нужно): доход = `sales.deal.handoff` (revenue_recognized), расход в момент landed.calculated.
5. **Подтверждение, что мы НЕ строим полный двойной учёт** — только управленческие срезы + пасс-через 1С.

## Что НЕ делаем

- Двойную запись (debit/credit), план счетов — это домен 1С.
- НДС-расчёт и ЭСЧФ — остаются в 1С.
- Полноценный баланс по PCAOB/IFRS — только пасс-через 1С.
- Бюджетирование/план-факт — отдельный пакет, не часть отчётности.
