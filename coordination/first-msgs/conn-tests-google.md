# Задание: юнит-тесты коннектора Google Docs/Sheets (замоканные API)

Ты пишешь ОДИН файл — `tests/test_connectors_gdrive.py` — и делаешь его зелёным.
Код `connectors/gdrive.py` уже на `main` и менять его НЕЛЬЗЯ.

**Goal-Driven**: мок-тесты на `GoogleConnector` (пагинация pageToken, инкремент по
modifiedTime, экспорт Doc→text, чтение Sheet→sheets, пустой лист) →
`pytest tests/test_connectors_gdrive.py -x -q` = 0.

**Читай первым** свой скоуп: `coordination/conn-tests-google-scope.md` — трассировка к
FR-30..FR-35, рекомендация мокать через `__new__`-обход `__init__` и MagicMock-цепочки,
команда запуска pytest, acceptance gate. Затем `connectors/connectors_spec.md` §7.3 и
сам `connectors/gdrive.py`.

Жёстко: никакой реальной сети/ключа — Google-клиентов мокай. Не трогай другие тест-файлы
и `connectors/*`. Нужна правка кода коннектора для зелёного — СТОП, `NEEDS-ORCHESTRATOR-ANSWER`.
