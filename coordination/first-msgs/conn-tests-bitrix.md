# Задание: юнит-тесты коннектора Bitrix24 (замоканный HTTP)

Ты пишешь ОДИН файл — `tests/test_connectors_bitrix.py` — и делаешь его зелёным.
Код коннектора `connectors/bitrix.py` уже на `main` и менять его НЕЛЬЗЯ.

**Goal-Driven**: напиши мок-тесты на `BitrixConnector` (пагинация, курсор,
скачивание записи с фолбэком, устойчивость к лимитам) → `pytest tests/test_connectors_bitrix.py -x -q` = 0.

**Читай первым** свой скоуп: `coordination/conn-tests-bitrix-scope.md` — там трассировка
к FR-11..FR-16, рекомендации по мокам, точная команда запуска pytest и acceptance gate.
Затем `connectors/connectors_spec.md` §7.1 и сам `connectors/bitrix.py`.

Жёстко: HTTP только замоканный (никаких реальных порталов Bitrix). Тест не должен быть
медленным (заглуши паузы ретраев). Не трогай другие тест-файлы и `connectors/*`.
Если для зелёного теста понадобится править код коннектора — это сигнал бага: СТОП,
пиши `NEEDS-ORCHESTRATOR-ANSWER` в status с описанием.
