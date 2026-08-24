# Задание: юнит-тесты коннектора 1С OData (замоканный HTTP)

Ты пишешь ОДИН файл — `tests/test_connectors_onec.py` — и делаешь его зелёным.
Код `connectors/onec.py` уже на `main` и менять его НЕЛЬЗЯ.

**Goal-Driven**: мок-тесты на `OneCConnector` (пагинация $top/$skip, инкремент по
date_field и продвижение курсора, полный проход без даты, устойчивость к 5xx) →
`pytest tests/test_connectors_onec.py -x -q` = 0.

**Читай первым** свой скоуп: `coordination/conn-tests-onec-scope.md` — трассировка к
FR-21..FR-23, рекомендации по мокам, команда запуска pytest, acceptance gate.
Затем `connectors/connectors_spec.md` §7.2 и сам `connectors/onec.py`.

Жёстко: HTTP только замоканный (никакой реальной 1С). Тест не медленный. Не трогай
другие тест-файлы и `connectors/*`. Нужна правка кода коннектора для зелёного — СТОП,
`NEEDS-ORCHESTRATOR-ANSWER`.
