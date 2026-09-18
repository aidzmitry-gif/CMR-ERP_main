# Тесты и оповещения

## Локальная проверка

Backend unit-тесты запускаются из корня репозитория:

```powershell
py -3 -m pytest -q tests -m unit --cov --cov-branch --cov-report=term-missing --basetemp .pytest-tmp
```

Для release-gate проверяется именно line coverage. В `pyproject.toml` включён
branch coverage, поэтому итоговый показатель `Cover` в таблице pytest-cov — это
смешанный line+branch показатель и может быть ниже line coverage. CI читает
`coverage-unit.json` и блокирует PR, если backend line coverage не превышает 91%.

Frontend:

```powershell
cd frontend
npm run test:coverage
npm run typecheck
npm run lint
```

GitHub Actions запускает те же unit-тесты с явным корнем `tests` и отдельные gates
для backend/frontend. Явный корень не даёт pytest случайно собрать служебные
скрипты из соседних каталогов. Полный backend JUnit загружается артефактом и
дублируется в `GITHUB_STEP_SUMMARY`, поэтому красный PR содержит число падений и
ссылку на детализацию, а не только общий статус job.
Coverage-файлы сохраняются как артефакты workflow; тесты не нужно запускать
«на GitHub вручную» — GitHub нужен как воспроизводимый CI-контроль каждого PR.

Операционный срез Harness хранится в
`.harness/work/CRM-QA-001.scorecard.json`. Его целостность проверяется командой:

```powershell
py -3 scripts/quality/scorecard_control.py --report .harness/work/CRM-QA-001.scorecard-gate.json
```

Проверка сверяет parent HEAD, фактическое состояние Git, размеры и SHA-256 входных
артефактов, JUnit/coverage/inventory-счётчики и не принимает статус `accepted`,
пока остаются падения, пропуски, coverage не превышает 91%, дрейф submodule-источника,
неподтверждённый Postgres или неизвестная доставка production-alerts. Proof-файлы
Postgres и webhook должны содержать проверяемые статусы, счётчики и обязательные
признаки миграции/rollback/idempotency/concurrency или фактической доставки. DORA и
production delivery остаются `unknown`, пока нет соответствующей внешней истории.

Inventory защищён принятым policy baseline в
`.harness/policy/CRM-QA-001.regression-baseline.json`. Обычный запуск
`.harness/tools/build_g03_inventory.py` только сравнивает текущие test IDs,
исходные fingerprints и классификацию с этим snapshot и завершается с ошибкой
при добавлении, удалении или изменении теста. Обновление возможно только явно
после ревью: `py -3 .harness/tools/build_g03_inventory.py --accept-baseline`.

## Проверка живости и готовности

- `GET /health` — liveness: процесс отвечает.
- `GET /ready` — readiness: выполнен `SELECT 1` в БД; при недоступной БД ответ
  `503` с `status=not_ready`.

`/ready` открыт для инфраструктурного health-check без пользовательской роли.
Его следует подключить к Docker/Kubernetes/Uptime Kuma/Prometheus probe.

## Технические инциденты

Фоновый relay/escalation loop передаёт необработанную ошибку в общий webhook-sink.
Поддерживается любой endpoint, принимающий JSON (Slack/Teams/собственный relay):

```text
AIOS_INCIDENT_WEBHOOK_URL=https://alerts.example/erp
AIOS_INCIDENT_WEBHOOK_TOKEN=<secret-in-server-secret-store>
AIOS_INCIDENT_ALERT_COOLDOWN_SECONDS=300
```

Без URL приложение не падает и пишет структурированный инцидент в лог. Повторная
ошибка одного источника подавляется на время cooldown; секретоподобные значения
рекурсивно маскируются в словарях/списках и в текстовых форматах `key=value`,
`key: value` и JSON. Уведомления не должны содержать пароли, JWT или полные
строки подключения к БД.

Важно: webhook — канал доставки, а не мониторинг сам по себе. Для оповещения
оператора нужен внешний receiver и правило для `5xx`/`not_ready`/incident. CI
дополнительно оповещает о регрессии тестов через статус GitHub Actions.
