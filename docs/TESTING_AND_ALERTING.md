# Тесты и оповещения

## Локальная проверка

Backend unit-тесты запускаются из корня репозитория:

```powershell
py -3 -m pytest -q -m unit --cov --cov-branch --cov-report=term-missing --basetemp .pytest-tmp
```

Для release-gate проверяется именно line coverage. В `pyproject.toml` включён
branch coverage, поэтому итоговый показатель `Cover` в таблице pytest-cov — это
смешанный line+branch показатель и может быть ниже line coverage. CI читает
`coverage-unit.json` и блокирует PR, если backend line coverage ниже 91%.

Frontend:

```powershell
cd frontend
npm run test:coverage
npm run typecheck
npm run lint
```

GitHub Actions запускает те же unit-тесты и отдельные gates для backend/frontend.
Coverage-файлы сохраняются как артефакты workflow; тесты не нужно запускать
«на GitHub вручную» — GitHub нужен как воспроизводимый CI-контроль каждого PR.

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
маскируются до отправки. Уведомления не должны содержать пароли, JWT или полные
строки подключения к БД.

Важно: webhook — канал доставки, а не мониторинг сам по себе. Для оповещения
оператора нужен внешний receiver и правило для `5xx`/`not_ready`/incident. CI
дополнительно оповещает о регрессии тестов через статус GitHub Actions.
