# conn-tests-bitrix — scope

## Задача (уровень 2: касаемые файлы + верификация)

Написать юнит-тесты с **замоканным HTTP** на коннектор Bitrix24
(`connectors/bitrix.py`). Источник НЕ дёргать. Сделать `tests/test_connectors_bitrix.py`
зелёным. Это пункты Definition of Done из `connectors/connectors_spec.md`
(пагинация, продвижение курсора, фолбэк скачивания записи, устойчивость к лимитам).

## Что покрыть (трассировка к FR)

- **FR-12 пагинация**: `_list()` обходит страницы через `start`/`next`, пока `next is None`
  (минимум 2 страницы в тесте).
- **FR-14 курсор resume-after-yield**: `fetch_calls()` двигает `bitrix_calls_last_id` в
  state ТОЛЬКО после yield записи; после прохода курсор = max(ID).
- **FR-15 CRM**: `fetch_crm("crm.deal.list", "deal", select=["*","UF_*"])` отдаёт RawRecord
  с `source="bitrix_deal"`, и курсор `crm.deal.list_last_id` продвигается.
- **FR-13 скачивание записи**:
  - прямой `CALL_RECORD_URL` → файл качается в `media_dir/call_<ID>.mp3`, путь в `media_path`;
  - прямой ссылки нет, но есть `RECORD_FILE_ID` → фолбэк через `disk.file.get` → `DOWNLOAD_URL`;
  - файл уже существует → повторно НЕ качаем (идемпотентность, NFR-2);
  - запись удалена/недоступна → `media_path=None`, прогон НЕ падает (NFR-3).
- **FR-16 устойчивость**: HTTP 429 / `QUERY_LIMIT_EXCEEDED` → `BitrixTransientError`
  (проверить, что `call()` поднимает его на 429). Ретраи НЕ должны делать тест медленным —
  заглуши паузы (monkeypatch `time.sleep` или tenacity-wait), либо тестируй одну попытку.

## Как мокать (рекомендация, не догма)

- Замокай нижний уровень: `monkeypatch` на `requests.Session.post`/`.get` (вернуть фейковый
  объект с `.status_code`, `.json()`, для скачивания — `.iter_content`, контекст-менеджер),
  ЛИБО патчи `BitrixConnector.call` / `_download_record` точечно под конкретный тест.
- State: можно реальный `StateStore(tmp_path/'state.json')` или простой фейк с `get/set`.
- `media_dir` — `tmp_path`. Проверяй, что `.part` не остаётся, файл переименован.

## LOOP CONTRACT

```yaml
scope:
  include:
    - tests/test_connectors_bitrix.py
  exclude:
    - connectors/**            # код коннектора НЕ менять (он уже на main)
    - tests/test_connectors_core.py
    - tests/test_connectors_onec.py
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
  - connector_code_change_required   # если для зелёного теста надо править connectors/* → СТОП, спроси оркестратора
report:
  destination: coordination/conn-tests-bitrix-status.md
```

## Команда запуска тестов (worktree БЕЗ своего .venv — бери python ГЛАВНОГО репо)

```powershell
& "d:\6 Проекты\CRM ERP\Сlaude CRM - проект\.venv\Scripts\python.exe" -m pytest tests/test_connectors_bitrix.py -x -q
```
Запускать из корня СВОЕГО worktree (cwd) — импорт `connectors` резолвится из worktree,
зависимости (pytest/requests/tenacity) берутся из venv главного репо. Деп уже установлены.

## Acceptance gate

- [ ] `tests/test_connectors_bitrix.py` создан, мокает HTTP, источник не дёргается
- [ ] Покрыты: пагинация start/next, продвижение курсора звонков и CRM, фолбэк disk.file.get,
      идемпотентный скип уже скачанного, graceful при удалённой записи, transient на 429
- [ ] `pytest tests/test_connectors_bitrix.py -x -q` → 0
- [ ] Тронут ТОЛЬКО `tests/test_connectors_bitrix.py` (connectors/* не менялся)
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- Тест случайно ходит в сеть (не замокан `Session`) → Class E. Мокай нижний слой.
- Медленный тест из-за реальных tenacity-пауз → заглуши sleep/wait.
- Для зелёного захотелось править `connectors/bitrix.py` → СТОП, это вне скоупа: NEEDS-ORCHESTRATOR-ANSWER.
