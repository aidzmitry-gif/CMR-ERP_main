# conn-tests-google — scope

## Задача (уровень 2: касаемые файлы + верификация)

Написать юнит-тесты с **замоканными Google API** на коннектор
(`connectors/gdrive.py`). Реальные Google API НЕ дёргать, реальный ключ не нужен.
Сделать `tests/test_connectors_gdrive.py` зелёным. DoD из `connectors/connectors_spec.md` §7.3.

## Что покрыть (трассировка к FR)

- **FR-32 листинг папок + пагинация**: `_fetch_folder` обходит страницы Drive через
  `nextPageToken`, пока токена нет (минимум 2 страницы).
- **FR-33 инкремент по modifiedTime**: при наличии курсора в `q` появляется
  `modifiedTime > '<cursor>'`; после прохода `gdrive_<folder>_modified` = max(modifiedTime).
- **FR-34 Google Docs**: `mimeType == DOC_MIME` → `payload.text` = экспортированный текст,
  `source="gdoc"`, `record_type="document"`.
- **FR-35 Google Sheets**: `mimeType == SHEET_MIME` → `payload.sheets` = словарь
  «лист → массив строк», `source="gsheet"`. Пустой лист → `[]` (edge case, не падать).

## Как мокать (рекомендация)

- `__init__` строит google-клиентов — обходи его: создавай объект через
  `GoogleConnector.__new__(GoogleConnector)` и руками проставляй `.drive`, `.sheets`,
  `.folder_ids`, `.state` (Mock/MagicMock + реальный StateStore на tmp_path). Так
  тестируется реальная логика `fetch/_fetch_folder/_build_record/_read_sheet`, без сети и ключа.
- Цепочки вызовов мокай через `MagicMock`: `drive.files().list().execute.return_value = {...}`.
  Для пагинации задай `execute.side_effect = [page1, page2]`.
- Для `_export_doc` (использует `MediaIoBaseDownload`): либо `monkeypatch` на
  `connectors.gdrive.MediaIoBaseDownload` (фейк, у которого `next_chunk()` сразу `(_, True)`
  и буфер уже наполнен), либо точечно патчи `GoogleConnector._export_doc`. Выбери проще.
- Sheets: `sheets.spreadsheets().get().execute()` → метаданные листов;
  `sheets.spreadsheets().values().get().execute()` → `{"values": [...]}` (или без `values` для пустого).

## LOOP CONTRACT

```yaml
scope:
  include:
    - tests/test_connectors_gdrive.py
  exclude:
    - connectors/**
    - tests/test_connectors_core.py
    - tests/test_connectors_bitrix.py
    - tests/test_connectors_onec.py
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
  destination: coordination/conn-tests-google-status.md
```

## Команда запуска тестов (worktree БЕЗ своего .venv — бери python ГЛАВНОГО репо)

```powershell
& "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.venv\Scripts\python.exe" -m pytest tests/test_connectors_gdrive.py -x -q
```
Запускать из корня СВОЕГО worktree. `google-api-python-client`/`google-auth` уже
установлены в venv главного репо, но твои тесты их вызовы должны МОКАТЬ, а не использовать.

## Acceptance gate

- [ ] `tests/test_connectors_gdrive.py` создан, Google API замоканы, сети нет, ключ не нужен
- [ ] Покрыты: пагинация pageToken, инкремент modifiedTime + курсор, экспорт Doc→text,
      чтение Sheet→sheets, пустой лист → []
- [ ] `pytest tests/test_connectors_gdrive.py -x -q` → 0
- [ ] Тронут ТОЛЬКО `tests/test_connectors_gdrive.py`
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- `__init__` пытается читать реальный JSON-ключ → обходи __init__ через __new__.
- `MediaIoBaseDownload` тянет реальный chunk → мокай модульную ссылку.
- Захотелось править `connectors/gdrive.py` → СТОП, NEEDS-ORCHESTRATOR-ANSWER.
