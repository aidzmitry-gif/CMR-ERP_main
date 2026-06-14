# Гейт приёмки воркера (durable JSON-чеклист)

Машинно-проверяемый гейт «готово/не готово» для каждого воркера. Реализация —
[`acceptance_gate.py`](../../acceptance_gate.py). Файлы гейтов: `coordination/acceptance/<worker>.json`.

## Зачем (доказательная база)

- **Компактация контекста недостаточна** даже для Opus 4.5 на длинных прогонах → нужен
  *внешний durable* спецификации-гейт, переживающий смену окон контекста.
  ([Anthropic — Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents))
- **«Галлюцинация done»**: агенты помечают фичу готовой без реальной проверки. Гейт
  не верит флагу — для критериев с `cmd` он **перезапускает** проверку и переписывает
  `passes` объективным результатом.
- **JSON, а не markdown** — модель реже перезаписывает JSON-файл целиком (там же).
- Гейт даёт ещё и **наблюдаемость стадии**: `status` — сводка готовности по всему флоту.

## Схема

```json
{
  "worker": "deals-board-fe",
  "checks": [
    {"id": "lint",  "kind": "lint",   "desc": "ruff чисто на owned-файлах",
     "cmd": "\"./.venv/Scripts/python.exe\" -m ruff check modules/sales", "passes": false, "evidence": ""},
    {"id": "types", "kind": "types",  "desc": "tsc без ошибок",
     "cmd": "cd frontend && node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json", "passes": false, "evidence": ""},
    {"id": "tests", "kind": "test",   "desc": "юнит модуля зелёные",
     "cmd": "\"./.venv/Scripts/python.exe\" -m pytest modules/sales -q", "passes": false, "evidence": ""},
    {"id": "board", "kind": "manual", "desc": "доска рендерит карточки (E2E)",
     "passes": false, "evidence": ""}
  ]
}
```

- `cmd` есть (`lint`/`types`/`test`) → **объективно**: `check` запускает, `passes = (exit 0)`,
  флаг воркера игнорируется/перезаписывается.
- `cmd` нет (`manual`) → засчитывается ТОЛЬКО при `passes:true` **и** непустом `evidence`
  (путь к скрину Playwright, лог, ссылка). Браузерную верификацию автоматизируй через
  Playwright-плагин — это рекомендованная митигация галлюцинации done.

## Контракт воркера

1. Гейт сидируется до старта (оркестратором/инициализатором) из acceptance-матрицы scope-файла.
2. Ты вправе менять **только** поле `passes` (и прикладывать `evidence`). **Нельзя**
   править/удалять сами критерии или их `cmd` — это скрыло бы баги. (Формулировка
   Anthropic: «It is unacceptable to remove or edit tests».)
3. Перед тем как писать `STATE: COMPLETE`, сам прогони
   `acceptance_gate.py check <worker>` и добейся **ЗЕЛЁНОГО** (exit 0).

## Wiring в оркестратор

- **`integrate <worker>`**: перед merge вызвать `acceptance_gate.py check <worker>`;
  **сливать только при exit 0** (плюс уже стоящий лят-гейт хуков). Красный гейт = отказ.
- **Дашборд флота**: `acceptance_gate.py status` → строка готовности на воркера.

## Шпаргалка

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py acceptance_gate.py init  deals-board-fe --from coordination/acceptance/_seed.json
& $py acceptance_gate.py init  deals-board-fe --check "lint|lint|ruff|`"./.venv/Scripts/python.exe`" -m ruff check modules/sales"
& $py acceptance_gate.py check  deals-board-fe   # exit 0 зелёный / 2 красный
& $py acceptance_gate.py status                  # сводка по всем гейтам
```
