# Harness context

Текущий контроль качества ERP ведётся в [CRM-QA-001](work/CRM-QA-001.md).

- Паспорт: [CRM-QA-001.passport.json](work/CRM-QA-001.passport.json)
- Статус: running, Plan revision 4 подтверждён; G04 CI/control и G06 runtime-control slices приняты локально с fail-closed JUnit gates, strict registry gate зелёный после свежей нативной discovery-проверки; product regression и Postgres остаются отдельными красными gates
- Текущая граница: локальные тесты, CI и Harness-артефакты; pre-acceptance scorecard — `.harness/work/CRM-QA-001.scorecard.json`; без production/deploy/migration/push
- Модель для тестовых срезов: `gpt-5.6-luna / max`
- Текущая проверенная граница: `ruff check .` проходит; G03 собрал 4,436 unique test IDs, включая 12 integration cases, доказанные frontend sizes, case-level evidence matching и неизменяемый policy baseline, а G04 добавил fail-closed registry/aggregator, diagnostic-only flake policy, source-snapshot preflight, strict `>91%` coverage gates и lint cap 45/45. G06 локально подтвердил 19 runtime/alert/flake тестов. Unit: 897 passed, backend line coverage 93.42% (>91%), branch coverage 75.16%. Full backend остаётся красным (2,074 passed / 14 failures / 12 skips), API lane красный (1,177 passed / 14 failures), а source snapshot показывает четыре submodule worktrees, отличающиеся от parent gitlinks; фиксированная дата procurement-теста исправлена и теперь проходит. Registry layer overlap, unknown size и classification debt — 0; Postgres integration execution остаётся недоказанным.
- Методическая база: Google test sizes/pyramid, pytest strict markers/JUnit XML, Vitest JSON/coverage reporters, GitHub required checks/merge queue, DORA delivery metrics и OpenTelemetry signals.
- Ревизия 4: ERP-инварианты, CUJ-матрица, миграции/concurrency/idempotency, flake quarantine, release evidence и high-signal alerting.
- Предыдущая завершённая цель: [CRM-UNIT-001](work/CRM-UNIT-001.md)
