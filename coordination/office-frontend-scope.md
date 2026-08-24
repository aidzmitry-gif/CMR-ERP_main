# office-frontend — scope

## Задача (уровень 2: касаемые файлы + верификация)

Доработать `erp/office`: секция доставки с трекингом + модалка «Заявка перевозчику»
(гард ≥300 кг) + BYN вместо ₽. Проверка: `npx vitest run src/lib/office-*.test.ts`
зелёный + `npm run lint` чистый по тронутым файлам. Подробное ТЗ — в first-msg.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/office/**
    - frontend/src/components/erp/office-*.tsx
    - frontend/src/lib/office-*.ts
  exclude:
    - frontend/src/lib/api.ts
    - frontend/src/lib/types.ts
    - frontend/src/lib/format.ts          # читать можно; менять нельзя (общий)
    - frontend/src/lib/funnel-configs.ts
    - frontend/src/components/funnel/**    # общий FunnelBoard — не трогать
    - frontend/src/components/sidebar.tsx
    - frontend/src/app/erp/logistics/**    # чужой воркер
    - frontend/src/app/erp/crypto/**       # ломает build
    - modules/**
    - migrations/**
    - "**/*.py"
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 5
  max_runtime_minutes: 35
  max_files_changed: 8
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - need_to_modify_shared_file        # FunnelBoard/format.ts/api.ts → NEEDS-ORCHESTRATOR-ANSWER
  - product_behavior_ambiguous
report:
  destination: coordination/office-frontend-status.md
```

## Acceptance gate

- [ ] Чистая логика в `lib/office-*.ts` (парс веса, гард ≥300 кг, классификация трекинга)
      покрыта co-located vitest, был RED до реализации (TDD)
- [ ] `npx vitest run src/lib/office-*.test.ts` → 0 фейлов
- [ ] `npm run lint` — нет новых ошибок в тронутых файлах
- [ ] `erp/office`: секция доставки с трекингом + модалка заявки + гард ≥300 кг + BYN;
      при пустом/лежащем backend не падает
- [ ] Лейбл «Сумма, ₽» в office/page.tsx заменён на BYN; деньги в панели — `formatByn`
- [ ] НЕ запускался `npm run build` (сломан вне скоупа); проверка vitest+lint
- [ ] Общий `FunnelBoard`/`format.ts`/`api.ts` не тронуты
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- Соблазн кастомизировать карточку общего `FunnelBoard` (трекинг/кнопка на карточке) —
  это shared-файл: вместо этого строй отдельную office-секцию `components/erp/office-*`.
  Если правда нужен общий компонент — STOP, `NEEDS-ORCHESTRATOR-ANSWER`.
- Глобальная замена ₽→BYN в `format.ts`/`formatMoney` — НЕ твой скоуп (общий форматтер,
  затрагивает другие модули). Делает оркестратор. Ты меняешь только лейбл office-страницы
  и используешь `formatByn` в своей панели.
- `npm run build` падает на `crypto/page.tsx` (чужой файл) — не гейтись на build.
