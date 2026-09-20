# Контракт атрибуции статьи расхода

## Подтверждённые факты

- Неразнесённая строка — expense/BYN строка организации в месяце, у которой `expense_article_id` отсутствует либо не найден в текущем справочнике; cash-срез дополнительно требует `Line.cash=true`. См. [expenses.py](../../modules/accounting/expenses.py) и [test_expense_control.py](../../tests/accounting/test_expense_control.py).
- Реестр ограничен организацией, posting date, basis и keyset `Line.id`; он не выводит статью по счёту или контрагенту. См. [expenses.py](../../modules/accounting/expenses.py).
- Группы и статьи принадлежат организации; бюджет имеет год, basis и snapshot статьи. См. [expense_models.py](../../modules/accounting/expense_models.py) и [expenses.py](../../modules/accounting/expenses.py).
- Проведённые `Entry`/`Line` являются историей; прямое изменение строки не является допустимой коррекцией. См. [models.py](../../modules/accounting/models.py) и [test_expense_control.py](../../tests/accounting/test_expense_control.py).

## PROPOSAL: append-only атрибуция

`POST /accounting/organizations/{org}/expense-attributions`

```json
{"request_key":"UUID","source_line_id":123,"article_id":45,"evidence":"...","explanation":"...","effective_date":"YYYY-MM-DD","expected_basis_digest":"..."}
```

Результат — неизменяемая квитанция с `organization_id`, `source_line_id`, `article_snapshot` (включая group), actor, request key, evidence, effective date, status и digest. Исходная Line не изменяется; read model применяет последнюю действующую атрибуцию только после проверки scope и периода.

| Состояние | Условие | Результат |
| --- | --- | --- |
| proposed | line/article/policy доступны, период открыт | preview без записи |
| confirmed | idempotency и basis подтверждены | append-only receipt |
| rejected | чужая org, отсутствует article/policy, закрытый период, stale basis | без мутации |
| replay | тот же request key и payload | исходная квитанция |

## Preconditions и stop conditions

Остановить операцию при отсутствующей/чужой статье, отсутствии применимой политики, закрытом периоде, чужой строке, повторе с другим payload или изменении basis. Не выводить статью из account/dimensions автоматически.

## Аудит и UX

Read-only реестр должен показывать исходную line, текущую/историческую квитанцию, actor, evidence, дату и drill-down проводки; существующий UI уже открывает проводку из неразнесённого реестра. См. [expense-control.tsx](../../frontend/src/components/erp/expense-control.tsx), [expense-control-api.ts](../../frontend/src/lib/expense-control-api.ts) и [test_expense_control_api.py](../../tests/accounting/test_expense_control_api.py).

## GAP / UNKNOWN

GAP: append-only модель/route/receipt для атрибуции в доступном коде не подтверждена. UNKNOWN: нормативная допустимость даты коррекции и конкретная политика закрытых периодов для такого документа.

## Рекомендуемый единственный срез

Добавить только append-only `ExpenseArticleAttribution` + preview/confirm read model для одной source line, с org/policy/period/idempotency guards и без изменения `accounting.line`.
