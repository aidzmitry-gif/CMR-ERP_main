# Смена автономной оркестрации — ночь 2026-07-01 → 02

> ⚠️ ИСТОРИЧЕСКИЙ план смены 01.07.2026. Тиринг в нём УСТАРЕЛ; ошибочные назначения Fable на
> «быструю механику» исправлены на Haiku/Sonnet по месту — действующий канон:
> coordination/MODEL-TIERING.md.

> **Роль:** этот чат = ОРКЕСТРАТОР (Opus). Спавнит headless-воркеров (`spawn_workers.py`),
> ведёт их всю смену, отвечает на блокеры, гоняет гейты, интегрирует, **пушит** (не деплоит).
> Оператора нет 7–8 ч. Все решения — сам (арбитраж по PLATFORM.md), логирую в REPORTS.md с меткой ⚠REVIEW.

## Решения оператора (зафиксированы перед сменой)
- **Модель работы:** оркестратор + headless-воркеры (до 5 разом).
- **Скоуп:** (1) тонкие модули · (2) техдолг+ARB · (3) Sales-2.0 UX-хвосты · (4) Безопасность P1-2.
- **Блокеры:** арбитрирую сам по конституции (деньги→безопасность→функции→эстетика), лог в REPORTS.md + ⚠REVIEW.
- **Push/deploy:** пушу каждый интегрированный+зелёный кусок в `origin/sales-2.0-redesign`. Сервер belakb.by НЕ трогаю.
- **Тиринг моделей (жёстко):** дефолт **Sonnet**; **Opus** — деньги/безопасность/схема-миграции/архитектура/адверсариальная сверка/арбитраж; **Haiku 4.5** — быстрая механика (доки, скаффолд, переименования); **Fable 5** — вне тиринга, на механику не ставить. Канон — `coordination/MODEL-TIERING.md`. Ставится строкой `model:` в `LOOP CONTRACT` scope-файла воркера.

## Wave 0 — сетап (делаю САМ, до спавна)
1. **BASE_BRANCH.** `spawn_workers` ветвит воркеров от `BASE_BRANCH` и `integrate` требует быть на нём.
   Наша работа — на `sales-2.0-redesign`. Перед спавном: `WORKER_BASE`/конфиг = `sales-2.0-redesign`
   (или ветвлю воркеров от текущего tip и мержу обратно в `sales-2.0-redesign` вручную). Проверить в spawn_workers, каким флагом/env задаётся база; если нет — интегрирую руками (merge ветки воркера → sales-2.0-redesign + smoke).
2. **Голова миграций = 0082.** Единый писатель номеров — Я. Резерв на смену:
   `service=0083`, `scd2-partial-unique=0084`, `legal=0085`, `knowledge=0086` (беру через `scripts/next_migration.py` по факту).
3. **DEPENDENCY-MAP §2** — обновляю САМ (реестр — моя зона): рёбра `reference→procurement`,
   `marketing.seo.*`, `production← sales.deal.handoff/procurement.order.received` (уже влито f53222d).

## Гейт приёмки каждой полосы (DoD воркера)
`STATE: COMPLETE` только когда: `pytest` (или `scripts/lane_check.py <lane>`) зелёный · `ruff check` чисто ·
для фронта `npx tsc --noEmit` чисто · импорт `main` ок · миграция (если есть) в линейной цепочке (один head).
Воркер упёрся → пишет `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/<name>-status.md` и завершается → я отвечаю через `spawn_workers.py respond` или правлю scope и переспавниваю.

## Волны (файлы НЕ пересекаются между воркерами одной волны)

### Wave A (спавн сразу, 5 воркеров)
| worker | полоса | суть | модель | миграция | гейт-оракул |
|---|---|---|---|---|---|
| `hr-payroll-ui` | HR 55→65 | payroll list/detail UI + экран ОКК по FunnelBoard-паттерну; бэк /hr/payroll уже есть | **sonnet** | нет | tsc + рендер SSR /erp/hr |
| `marketing-phase-e` | Marketing 15→35 | UTM-отчёт + live campaign board на существующий MAR-8 connector | **sonnet** | нет | pytest marketing + tsc |
| `service-intake` | Service 15→35 | заявки сервиса: модель+роуты+доска + подписка `sales.deal.won`→онбординг | **sonnet** | 0083 | lane_check service + миграция |
| `finance-money-str` | Техдолг ARB | вариант A: деньги float→str в finance API + фронт (закрыть NEEDS-ARB) | **opus** | нет | pytest finance + tsc фронт |
| `sales-ux-nextstep` | Sales-2.0 UX | datetime «Следующий шаг» + мокап подбора Gate 1 | **sonnet** | нет | tsc + рендер /crm/deals |

Между A и B: интегрирую готовые (merge→sales-2.0-redesign, submodule bump где нужно), пушу, обновляю readiness.json + DEPENDENCY-MAP, чиню NEEDS-ANSWER.

### Wave B (после интеграции A)
| worker | полоса | суть | модель | миграция | оракул |
|---|---|---|---|---|---|
| `legal-knowledge` | Legal/Knowledge 34→50 | legal-претензии CRUD + учёт курсов knowledge по office-паттерну | **sonnet** | 0085/0086 | lane_check + tsc |
| `security-p1-2-rbac` | Безопасность P1-2 | RBAC-матрица на write-эндпоинты по модулям + 403-свипы | **opus** | нет | pytest 403-sweep зелёный |
| `landed-duty-fact` | Техдолг деньги | пошлина в факт landed (task_fc401241), план↔факт сходится | **sonnet**¹ | нет | Я пишу failing план↔факт тест = оракул → воркер зелёнит |
| `scd2-partial-unique` | Техдолг схема | partial-unique индекс SCD2 (end_date IS NULL) на общих таблицах | **opus** | 0084 | миграция + тест гонки |
| `sales-e2e-board` | Sales-2.0 UX | e2e Playwright доски сделок (перетаскивание/фильтры/воронки) | **sonnet** | нет | `npm run e2e` зелёный |

¹ landed-duty-fact — Sonnet ТОЛЬКО потому что я даю тест-оракул; без оракула эскалировать до Opus (деньги).

### Wave C (резерв, если время/бюджет остались) — добиваю хвосты
- `dark-theme-audit` (**haiku**) — прогон `_theme_audit.py`, фикс парных токенов tone-soft/tone-ink.
- `chat-rail-polish` (**sonnet**) — единый компонент чат-рейки: вынести ChatRows в переиспользуемый, применить и к глобальному ChatsPanel (убрать дубль).
- `funnel-patch-offboard` (**sonnet**) — funnel-only PATCH оставляет чужую стадию → off-board (sales R5 INFO).
- `service-won-onboarding-test`, `marketing-utm-attribution-test` — добить покрытие.

---

## Расширение смены: волны D · E · F
> Добавлены по просьбе оператора (02.07) — runway, чтобы флот не простаивал все 8 ч.
> Пакеты (first-msg+scope) авторю **just-in-time** перед спавном каждой волны (как для A) через сабагентов,
> заземляя в реальном коде. Волны идут ПОСЛЕ интеграции предыдущей. Файлы внутри волны не пересекаются.
> Тиринг тот же: sonnet дефолт · opus деньги/безопасность/схема · haiku механика.

### Wave D — глубина модулей (порт прототипов/фронты)
| worker | полоса | суть | модель | миграция | оракул |
|---|---|---|---|---|---|
| `zak-cost-calc-ui` | Procurement | калькулятор себес. Китай → предв. себес позиции в сделке (прототип `zak-cost-calc-preview.html`, методика ТН ВЭД+пошлина+буфер курса) | sonnet | нет | tsc + рендер |
| `wms-inventory-ui` | WMS 75→85 | остатки/движения UI (scope `wms-fe-inv` уже есть — освежить); склад=1С, WMS дублирует движения | sonnet | нет | lane_check wms + tsc |
| `logistics-frontend` | Logistics 72→82 | доска/трекинг перевозок (scope `logistics-frontend` есть — освежить) | sonnet | нет | lane_check logistics + tsc |
| `production-planning-ui` | Production 72→82 | экран планирования цеха (scope `prod-fe-planning` есть — освежить) | sonnet | нет | lane_check production + tsc |
| `hr-okk` | HR 65→75 | ОКК-баллы сотрудников (scope `hr-okk` есть); спавнить ПОСЛЕ интеграции `hr-payroll-ui` (общий modules/hr) | sonnet | **0087** | pytest test_hr_okk + tsc |

### Wave E — качество · интеграция · покрытие
| worker | полоса | суть | модель | миграция | оракул |
|---|---|---|---|---|---|
| `dark-theme-audit` | UI кросс | прогон `_theme_audit.py`, фикс парных токенов tone-soft/tone-ink по отчёту | **haiku** | нет | _theme_audit.py чисто |
| `funnel-patch-offboard` | Sales R5 | funnel-only PATCH оставляет чужую стадию → off-board правило | sonnet | нет | pytest funnel + tsc |
| `reference-crud-tail` | Справочники | CRUD-хвост витрины (scope `reference-crud-tail` есть — освежить) | sonnet | нет | lane_check + tsc |
| `coverage-service-marketing` | Тесты | добить `service.deal.won`-онбординг + marketing UTM-атрибуция тесты (после A/D) | **sonnet** | нет | pytest зелёный |
| `analytics-kpi-dashboard` | Owner | кросс-модульный KPI-дашборд владельца (деньги строкой, BYN) | sonnet | нет | tsc + рендер /crm/owner |

### Wave F — бэкенд/схема/безопасность глубина (opus-тяж)
| worker | полоса | суть | модель | миграция | оракул |
|---|---|---|---|---|---|
| `security-p1-3-hardening` | Безопасность | хвост после P1-2: audit-log покрытие на write + rate-limit/CSRF на state-changing | **opus** | 0088¹ | pytest security-sweep |
| `procurement-po-lifecycle-tail` | Procurement | добить lifecycle PO (статусы/claims-связка), sales/finance-подписки на landed | sonnet | 0089¹ | lane_check procurement |
| `production-otk-depth` | Production | углубить ОТК/выработку (Блок 2) — расчёт ЗП/брак | sonnet | нет | lane_check production |
| `sop-demand-forecast-spec` | S&OP | ⚠БЛОКЕР (нужны история 1С+WMS+методика цены) → только СПЕЦ+скелет+тесты-заглушки, НЕ живой прогон | **opus** | нет | import main + spec-doc |
| `onec-mdm-read-bridge` | MDM/1С | ⚠РИСК: активировать READ-ONLY импорт 1С→MDM (`sync_1c`, ~4109 контрагентов); 1С-ЗАПИСЬ НЕ включать; координировать со Справочниками | **opus** | нет | pytest bridge (mock 1С) |

¹ Миграцию брать по факту через `scripts/next_migration.py` — резерв ориентировочный, единый писатель = Я.

**Резерв миграций (обновлён):** 0083 service · 0084 scd2 · 0085 legal · 0086 knowledge · 0087 hr-okk · 0088 security-audit · 0089 procurement-po. Голова была 0082.

**Стоп-флаги расширения:** `onec-mdm-read-bridge` и `sop-demand-forecast-spec` — только чтение/спека; при любом намёке на 1С-запись или деплой — СТОП, в REPORTS.md ⚠REVIEW, эскалация утром. `security-p1-3` не флипает прод в secure.

### Wave G — HR: учёт рабочего времени + Табель (НОВОЕ, оператор 02.07) — HTML-FIRST
> Спека: `coordination/spec-hr-worktime-tabel.md` (заземлена в присланном xlsx-табеле T-13 + `config/access.USERS`).
> **Метод html-first:** сперва мокап → Gate 1 (оператор одобряет UX) → Gate 2 → реализация. Бэкенд/схему/миграцию
> НЕ трогаем до одобрения (это НОВАЯ UX, конституция + skill html-first). 5 открытых вопросов — в спеке (Gate 1).
| worker | суть | модель | миграция | гейт |
|---|---|---|---|---|
| `hr-worktime-mockup` | кликабельный HTML-мокап: кнопка старт/стоп+счётчик · доска «кто онлайн/офлайн» · грид табеля с подсветкой переработки + попап согласования доп.часов; 2 темы, все окна/связи | sonnet | нет | мокап открывается, все окна кликаются (ui-crawl); Gate 1 — оператор |
| _(после Gate 1)_ `hr-worktime-backend` | work_session (clock-in/out+heartbeat) · work_norm · timesheet_cell; согласование переработки через core approvals; события шины hr.workday.* | sonnet→opus если деньги/ЗП-связка | ДА (по факту через next_migration) | lane_check hr + миграция |
| _(после Gate 1)_ `hr-worktime-frontend` | порт мокапа на Next.js: /erp/hr/presence + /erp/hr/tabel; виджет присутствия; напоминания (фон + Telegram-мост) | sonnet | нет | tsc + рендер |

**Резерв миграций (обновлён):** 0083 service · 0084 scd2(DONE) · 0085 legal(DONE) · 0086 knowledge(DONE) · 0087 hr-okk · 0088 security-audit · 0089 procurement-po · **0090 hr-worktime** (ориентир, брать по факту). Голова сейчас 0086.

## Что делаю Я (не отдаю воркерам)
- Реестр: ACTIVE-SESSIONS / DEPENDENCY-MAP / STATUS / readiness.json / REPORTS.md.
- Номера миграций (single-writer), арбитраж блокеров, интеграция веток, пуш, обновление % готовности.
- Опасная механика на общей ветке (bump gitlink, merge). Воркеры пушат в СВОИ submodule-репо; супер-гитлинк бампаю я.

## Ритм смены (я на /loop, self-paced ScheduleWakeup)
Каждый заход: `spawn_workers.py status` → интегрировать COMPLETE → ответить NEEDS-ANSWER →
досыпать волну до 5 занятых слотов → пуш зелёного → лог в REPORTS.md. Интервал сна ~20–30 мин
(воркеры длинные; будит и авто-нотификация о завершении). Бюджет токенов — Sonnet-дефолт бережёт.

## Стоп-условия / безопасность
- Не деплою на сервер. Не трогаю 1С-запись. Не флипаю прод в secure (отложено оператором).
- amend/reset/rebase на общей ветке ЗАПРЕЩЕНЫ — только новые коммиты.
- Каждое своё арбитражное решение → REPORTS.md с меткой ⚠REVIEW для утреннего ревью оператора.
- Утром: сводка сделанного + список ⚠REVIEW + что осталось.
