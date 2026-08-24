# conn-tests-onec — scope

## Задача (уровень 2: касаемые файлы + верификация)

Написать юнит-тесты с **замоканным HTTP** на коннектор 1С OData
(`connectors/onec.py`). Источник НЕ дёргать. Сделать `tests/test_connectors_onec.py`
зелёным. Это пункты Definition of Done из `connectors/connectors_spec.md` §7.2.

## Что покрыть (трассировка к FR)

- **FR-22 пагинация**: `_fetch_entity` идёт по `$top`/`$skip`, пока страница полная;
  останавливается, когда `len(rows) < page_size` или `value` пуст (минимум 2 страницы).
- **FR-23 инкремент по date_field**: при наличии курсора в `$filter` появляется
  `"{date_field} gt datetime'{cursor}'"`; после прохода `onec_<name>_cursor` = последнее
  виденное значение `row[date_field]`.
- **FR-23 полный проход без date_field**: `$filter` НЕ добавляется, курсор не трогается.
- **FR-21 модель**: `source="onec"`, `source_id="{name}:{Ref_Key}"`, `record_type="1c_entity"`,
  `payload` содержит `entity=<name>` и поля строки.
- **NFR-3 устойчивость**: HTTP 5xx (503) → `OneCTransientError` (проверить, что `_get`
  его поднимает на 503). Ретраи не должны тормозить тест — заглуши паузы или тестируй одну попытку.

## Как мокать (рекомендация)

- Патчи `OneCConnector._get` под конкретный тест (вернуть `{"value": [...]}` постранично),
  ЛИБО `monkeypatch` на `requests.Session.get` (фейк `.status_code`/`.json()`/`.raise_for_status()`).
  Для проверки `$filter`/`$orderby`/`$skip` перехватывай переданные `params`.
- `page_size` в тесте делай маленьким (напр. 2), чтобы пагинация отработала на малых данных.
- State: реальный `StateStore(tmp_path/'state.json')` или фейк с `get/set`.

## LOOP CONTRACT

```yaml
scope:
  include:
    - tests/test_connectors_onec.py
  exclude:
    - connectors/**
    - tests/test_connectors_core.py
    - tests/test_connectors_bitrix.py
    - tests/test_connectors_gdrive.py
    - core/**
    - modules/**
    - config/**
permissions:
  repo: write-branch
  db: read-only
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 30
  max_files_changed: 1
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - acceptance_gate_red_after_3_iters
  - file_touched_outside_scope
  - connector_code_change_required
report:
  destination: coordination/conn-tests-onec-status.md
```

## Команда запуска тестов (worktree БЕЗ своего .venv — бери python ГЛАВНОГО репо)

```powershell
& "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.venv\Scripts\python.exe" -m pytest tests/test_connectors_onec.py -x -q
```
Запускать из корня СВОЕГО worktree. Зависимости — из venv главного репо (уже установлены).

## Acceptance gate

- [ ] `tests/test_connectors_onec.py` создан, мокает HTTP, источник не дёргается
- [ ] Покрыты: пагинация $top/$skip, инкремент по date_field + продвижение курсора,
      полный проход без date_field, формат source_id/payload, transient на 503
- [ ] `pytest tests/test_connectors_onec.py -x -q` → 0
- [ ] Тронут ТОЛЬКО `tests/test_connectors_onec.py`
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- Не замокан `Session.get` → тест ходит в сеть (Class E).
- Литерал даты в `$filter` зависит от версии 1С — тестируй ФАКТ подстановки строки фильтра,
  не конкретную семантику платформы.
- Захотелось править `connectors/onec.py` → СТОП, NEEDS-ORCHESTRATOR-ANSWER.
