# Воркер: scd2-partial-unique — partial-unique индекс SCD2 (одна открытая версия на ключ)

## Цель (Goal-Driven)
Заменить прикладную гарантию «ровно одна открытая (`end_date IS NULL`) версия на natural key»
(сейчас держится только в `core/services/scd2.add_version`, см. предупреждение в шапке
`tests/test_scd2_invariants.py`) на **partial-unique индекс Postgres**: `UNIQUE (key) WHERE
end_date IS NULL`. Критерий готовности: race/duplicate-тест показывает, что вторая открытая
версия по тому же ключу отклоняется на уровне БД; `import main` = OK; `ruff check` = чисто;
единственная head-миграция 0084 поверх 0083.

## Контекст
РАБОЧАЯ ДИРЕКТОРИЯ: твой worktree (spawn_workers поставил cwd). НЕ упоминай путь главного
репо, НЕ делай `cd` туда.

Это shared-kernel код ядра (`core/domain/reference.py`, `core/services/scd2.py`), НЕ модуль —
коммит идёт прямо в суперпроект (submodule здесь ни при чём).

### Реальные SCD2-таблицы (схема `public`, ORM в `core/domain/reference.py`)
Все четыре — датированные версии с полуоткрытым интервалом `[start_date, end_date)`,
текущая версия = `end_date IS NULL`:

| Таблица | ORM-класс | Natural key (business key) | Существующий (обычный) индекс |
|---|---|---|---|
| `ref_currency_rate` | `CurrencyRate` | `currency_code` | `ix_ref_currency_rate_lookup` (currency_code, start_date) |
| `ref_vat_rate` | `VatRate` | `code` | `ix_ref_vat_rate_lookup` (code, start_date) |
| `ref_tnved` | `TnvedCode` | `code` | `ix_ref_tnved_lookup` (code, start_date) |
| `ref_sku_version` | `SkuVersion` | `sku_code` | `ix_ref_sku_version_lookup` (sku_code, start_date) |

`core/services/scd2.py` (`current_version`, `version_as_of`, `add_version`) — общая логика,
используется для всех четырёх таблиц. `add_version` закрывает текущую открытую версию и
вставляет новую, НЕ коммитит (коммитит вызывающий роут) — это и есть окно гонки: две
параллельные транзакции могут обе увидеть «открытой версии нет» и обе вставить новую.

⚠️ ВАЖНО прочитать перед правкой: шапка `tests/test_scd2_invariants.py` — там прямо написано
«NEEDS-ARB круга 2, не закрыт: на уровне БД НЕТ partial-unique индекса... гонку не
воспроизводим (нужен индекс)». Твоя задача — закрыть этот пробел и обновить/дополнить
docstring в тесте, когда индекс появится (убрать формулировку «не закрыт», описать
факт наличия constraint).

Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`.

## Шаг 1 — Заземление (уже сделано выше, свериться с кодом)
Прочитай `core/domain/reference.py` (классы `CurrencyRate`, `VatRate`, `TnvedCode`,
`SkuVersion`) и `core/services/scd2.py` — подтверди имена таблиц/колонок из таблицы выше
СОВПАДАЮТ с кодом на момент твоего запуска (модели не менять).

## Шаг 2 — Миграция `migrations/versions/0084_scd2_partial_unique.py`
Номер **0084 уже выделен координатором** — `python scripts/next_migration.py` НЕ вызывать.
`revision = "0084"`, `down_revision = "0083"`.

Для каждой из 4 таблиц — `op.create_index(..., unique=True, postgresql_where=sa.text("end_date IS NULL"))`
по business-key колонке. Имена индексов — по образцу существующих `ix_ref_*_lookup`, но с
суффиксом, например `uq_ref_currency_rate_open`, `uq_ref_vat_rate_open`, `uq_ref_tnved_open`,
`uq_ref_sku_version_open` (это НЕ NAMING_CONVENTION auto-name, поэтому имя пишем явно первым
позиционным аргументом `op.create_index`, как делают существующие `ix_ref_*_lookup` в 0037/0057).

```python
def upgrade() -> None:
    op.create_index(
        "uq_ref_currency_rate_open", "ref_currency_rate", ["currency_code"],
        unique=True, postgresql_where=sa.text("end_date IS NULL"),
    )
    op.create_index(
        "uq_ref_vat_rate_open", "ref_vat_rate", ["code"],
        unique=True, postgresql_where=sa.text("end_date IS NULL"),
    )
    op.create_index(
        "uq_ref_tnved_open", "ref_tnved", ["code"],
        unique=True, postgresql_where=sa.text("end_date IS NULL"),
    )
    op.create_index(
        "uq_ref_sku_version_open", "ref_sku_version", ["sku_code"],
        unique=True, postgresql_where=sa.text("end_date IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ref_sku_version_open", table_name="ref_sku_version")
    op.drop_index("uq_ref_tnved_open", table_name="ref_tnved")
    op.drop_index("uq_ref_vat_rate_open", table_name="ref_vat_rate")
    op.drop_index("uq_ref_currency_rate_open", table_name="ref_currency_rate")
```

Docstring вверху файла — по образцу 0057/0067 (кратко: что за индекс, зачем, что заменяет
прикладную проверку, дата, `Revises: 0083`).

⚠️ SQLite dev-режим не понимает `postgresql_where` в смысле полноценного partial-index —
`Database.connect` в SQLite создаёт таблицы через `create_all` из ORM-моделей напрямую, минуя
Alembic. Эта миграция — источник истины ТОЛЬКО для Postgres; для dev/тестов ORM-модели
(`core/domain/reference.py`) менять не нужно (partial-unique там не описывается декларативно
в этом контуре, `__table_args__` трогать не надо — риск сломать SQLite create_all).

## Шаг 3 — Race/duplicate-тест
В `tests/test_scd2_invariants.py` (или новом `tests/test_scd2_partial_unique.py` — выбери
исходя из того, что там уже импортировано) добавь тест, который:
1. Вставляет напрямую через ORM (`session.add`, без `scd2.add_version`) ДВЕ строки
   `VatRate` с одинаковым `code` и `end_date=None` (обходя прикладную проверку — так
   моделируем гонку двух параллельных транзакций, которые обе не увидели открытую версию
   друг друга).
2. На SQLite (тестовая БД `conftest.py` — проверь фикстуру `session`) partial-unique индекса
   нет (Alembic не применяется), поэтому **этот тест должен быть помечен как требующий
   Postgres** — используй маркер `integration` (см. `pytest.ini`/`conftest.py` за примером
   существующих `integration`-тестов, вероятно через `testcontainers`) ИЛИ, если в проекте нет
   готового Postgres-integration harness под рукой, задокументируй в docstring теста, что
   индекс проверяется вручную/на CI c Postgres, а тест на SQLite версии проверяет ХОТЯ БЫ
   что `add_version` (прикладной путь) по-прежнему не допускает второй открытой версии
   (это уже покрыто существующими тестами — не дублируй, просто убедись, что они зелёные).
3. Если найдёшь в проекте живой Postgres integration-контур (testcontainers, маркер
   `@pytest.mark.integration`) — напиши там реальный тест на дублирующий INSERT: ожидай
   `IntegrityError`/`UniqueViolationError` от второго INSERT с тем же ключом и
   `end_date IS NULL`.
4. Обнови шапку `tests/test_scd2_invariants.py`: убери фразу «NEEDS-ARB круга 2, не закрыт» —
   опиши, что partial-unique индекс добавлен миграцией 0084, гонка теперь невозможна на
   уровне БД (укажи имена индексов).

Не выдумывай несуществующий testcontainers-harness — если такого совсем нет, честно
задокументируй ограничение (SQLite dev не проверяет partial index) вместо фиктивного теста.

## Запуск
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python -m pytest tests/test_scd2_invariants.py -x -q
python -c "import main"
ruff check core/domain/reference.py core/services/scd2.py migrations/versions/0084_scd2_partial_unique.py tests/test_scd2_invariants.py --line-length 100
alembic heads
```

## DoD
- Миграция `migrations/versions/0084_scd2_partial_unique.py`: `revision="0084"`,
  `down_revision="0083"`, линейная цепь, `alembic heads` показывает ровно один head (0084).
- Race/duplicate-тест зелёный (0 failed) — вторая открытая версия по тому же ключу отклоняется
  на уровне БД (или честно задокументировано ограничение SQLite dev, если Postgres-контур
  недоступен).
- `import main` = OK, `ruff check` = чисто.
- Docstring `tests/test_scd2_invariants.py` обновлён — снят статус «не закрыт».
- Коммит в суперпроект (это core/, не submodule).
- `STATE: COMPLETE` в `coordination/scd2-partial-unique-status.md`.
- НЕ пушить.
