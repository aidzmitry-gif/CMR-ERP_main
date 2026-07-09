# Готовность проекта (snapshot)

> **Обновлено:** 2026-06-28 (грунтованная переоценка после кругов 1–3 + реконсиляция origin; 12 агентов читали реальный код)
> **Как обновить метрики:** `python scripts/readiness.py` → перенести объективные цифры сюда.
> **% — субъективная оценка** (учитывает зрелость UI, AI-мок, наличие миграций); правится вручную при реальном сдвиге блока, не каждую сессию.
> Этот файл **не грузится автоматически** в контекст — читать по запросу «сколько готово».

## Средняя готовность платформы: **~57%** (диапазон 55–60; было ~42–45 до кругов 1–3)

> 📌 **Канонический источник % — `coordination/readiness.json`** (ведётся ИНКРЕМЕНТАЛЬНО: лейн в `КООРД: DONE` даёт `[%: NN]` → координатор правит одну строку json). `readiness.py` рендерит их в авто-блок ниже при каждом прогоне (PreCompact + вручную) — пере-замер агентами НЕ нужен. Эта таблица — читаемый снимок с колонкой «тормоз»; цифры держать в синхроне с json.

> Money-критичное ядро (Продажи/Справочники/Логистика/Финансы/Закупки/Склад/Производство + Ядро) — **68–85%**; тонкие модули (Офис-бандл/HR/Маркетинг/Сервис) **15–34%** тянут среднее вниз. % = курируемая оценка по доказательствам (глубина бэка, миграции/ORM, зрелость фронта, доля реальных данных vs demo, тесты; AI-mock по дизайну).

| Модуль | % | Бэк/Фронт/Данные | UI | Главный тормоз до выше |
|---|---|---|---|---|
| **CRM / Продажи** (эталон) | **85** | 90/85/70 | bespoke | AI-mock по дизайну; маржа/цена ← фасад procurement + нет методики ценообразования; данные seeded, не боевая 1С |
| **Ядро-платформа** | **82** | 85/—/75 | — | Temporal-воркер, реальный LLM-вызов, шлюзы 1С/склад (Protocol) — заглушки (отложено); безопасность ~2.5/5 |
| **Справочники / MDM** | **78** | 88/75/62 | bespoke | мост 1С→MDM (~4109 контрагентов) откачен (только dry-run); часть фронта demo |
| **Логистика** | **72** | 82/78/45 | bespoke | данные seeded (нет live-перевозчиков/1С); уведомления тендера + AI-инсайты — заглушки |
| **Финансы** | **72** | 82/80/45 | bespoke | нет seed (honest-empty на чистой БД); 1С-сверка (`fetch_payments`) — заглушка |
| **Закупки** | **68** | 82/68/35 | FunnelBoard + bespoke | данные: засеяна лишь demo-воронка, остальное honest-empty без 1С; landed = мин.срез (Горизонт 2) |
| **Склад (WMS)** | **68** | 82/78/45 | bespoke | остаток — demo-зеркало 1С (не live pull); миграции вне checkout; тесты узкие (круг 3) |
| **Производство** | **68** | 78/72/30 | bespoke | не интегрирован (нет подписок/прав/AI); данные ~70% honest-empty/demo |
| **Юр / БЗ / Офис** | **34** | 40/33/10 | bespoke(office)/FunnelBoard | Office зрел (~55), Legal/Knowledge — заглушки; Knowledge без RAG; данные demo |
| **HR** | **22** | 25/25/15 | FunnelBoard | HR-домен (ЗП/ОКК/дисциплина/договоры) только в прототипах; данные demo |
| **Маркетинг** | **15** | 18/15/5 | ModuleBoard | агентная система/pSEO — только HTML-прототипы; нет миграции/seed |
| **Сервис** | **15** | 18/15/5 | ModuleBoard | намеренный каркас-заглушка; нет миграции/событий/логики |

Голова миграций (alembic): **0070** (реальный счётчик — в авто-блоке ниже).

> **Сквозные тормоза (тянут вниз ВСЕХ):** данные — seeded/demo, не живой фид 1С (data-измерение почти у всех 30–62%); AI-слой — mock по дизайну (`AIOS_AI_ENABLED` off); прод не флипнут в secure-режим (AuthN P1-1 в коде, ждёт realm Keycloak); методика ценообразования не реализована.
> Примечание: у sales/logistics/wms `page.tsx` тонкий, потому что делегирует в богатый bespoke-воркспейс — это зрелый UI, а не отсутствие фронта.

## Сквозные факторы (тянут вниз ВСЕХ)
- **AI-слой — «Итерация-1»**: моки/ghost-плейсхолдеры по дизайну, реальных агентов нет.
- **Прод-БД не наполнена** (нет seed) → живые доски/таблицы на belakb.by пустые.
- **KPI-числа — статичные demo** (`FUNNEL_EXTRAS`), а не из БД.
- **Безопасность — зрелость ~2/5** (P0 почти закрыт, 2026-06-24): fail-closed (роль «Гость»),
  мутации `/system/*` под `system.write`, `.dockerignore`, прод-дефолты `debug=False`/прод-гард,
  Telegram-webhook secret-token (fail-closed в проде), БД/Redis published-порты на loopback.
  456 тестов зелёные. Осталось в P0: SOPS + ротация секретов, P0-0 (проверить экспозицию прода),
  bind app/keycloak на loopback (зависит от топологии прокси — ops). Полноценная AuthN/AuthZ
  (Keycloak/RBAC) — P1. План и модель угроз — `SECURITY.md`. Цель: P0+P1 → твёрдая 3/5.

## Тип UI — что значит
- **bespoke** — кастомный воркспейс (живые данные + богатый UI). Самый зрелый.
- **FunnelBoard** — канбан+KPI; доска живая, KPI-числа demo.
- **ModuleBoard** — простая generic-таблица (CRUD-каркас).

<!-- READINESS:AUTO — авто-блок scripts/readiness.py --write, не редактируй вручную -->
### Объективные метрики (авто, обновлено 2026-07-04)

Свежие цифры из кода: loc (без миграций) · роуты · миграции модуля · тип фронта.
Таблица с **%** выше — курируемая вручную; сверяй её с этими числами.

| пакет | loc | роуты | мигр | ui |
|---|---:|---:|---:|---|
| `sales` | 5548 | 68 | 22 | bespoke (92 loc) |
| `procurement` | 2564 | 32 | 6 | FunnelBoard |
| `production` | 1303 | 30 | 5 | FunnelBoard |
| `wms` | 2479 | 42 | 6 | bespoke (15 loc) |
| `logistics` | 3340 | 51 | 5 | bespoke (10 loc) |
| `finance` | 2485 | 19 | 5 | bespoke (10 loc) |
| `marketing` | 1134 | 14 | 2 | ModuleBoard |
| `service` | 218 | 6 | 1 | ModuleBoard |
| `hr` | 488 | 14 | 3 | FunnelBoard |
| **всего миграций** | | | **91** | |

<!-- /READINESS:AUTO -->

<!-- COORD:AUTO — снимок координации флота, scripts/readiness.py --write -->
### Координация флота (авто, 2026-06-30 00:14)

- Ветка `sales-2.0-redesign` · HEAD `0d0d798 feat(sales-rop-plan): РОП план/факт — вкладка + компонент + тесты` · впереди origin **51** · незакоммичено **520**
- Голова миграций (alembic): **0080**

**Открытые доклады полос (REPORTS.md):**
- - `2026-06-28 17:46` · сессия `73bd6c8c` · **КООРД:** DONE reference — круг 4: 1С read-only фасады для финотчётов. `fetch_payments` РЕАЛИЗОВАН в OneCClient (был только в Protocol → finance ловил AttributeError); `fetch_bank_balance(account_code)→dict|None` + `fetch_balance_sheet(on_date)→dict|None` добавлены (mock + TODO реального OData GET при base_url; post_document не тронут; READ-ONLY). Контракт `fetch_payments` совпал с УЖЕ существующим потребителем `finance.reconcile` (ключ `ref`+`counterparty_ref`+`amount`) — проверено тестом через реальный `reconcile_with_onec` (3 платежа различимы). Гейт: `import main` PASS, 5 тестов PASS, ruff чисто по файлам полосы. Коммит f2d48c8 локально, НЕ пушено. ⚠ `core/services/onec.py` (хотспот) в круге 4 правили ОБЕ полосы — reference и finance (5b71649): сигнатуры идентичны, клоббера нет, но учти двойное касание. [DoD: ✓import-main ✓tests(5) ✓lint(свои файлы) ✓commit ✗push(правило) ⚠lane_check-foreign-fail] [%: 90]
- - `2026-06-28 17:46` · сессия `73bd6c8c` · **КООРД:** INFO reference — (1) Контракт для finance Р6/Р7 на подтверждение: `fetch_bank_balance(account_code) → {account_code, name, bank, balance:float, currency, as_of}|None`; `fetch_balance_sheet(on_date) → {on_date, currency, assets:[{code,name,amount}], liabilities:[{code,name,amount}], total_assets, total_liabilities}|None` (актив==пассив). `fetch_payments` строка: `{ref, counterparty_ref, amount, id, doc_number, date, currency, direction:in|out, account_code, bank, counterparty, unp, purpose}`. (2) `scripts/lane_check.py reference` падает на ЧУЖОМ: ruff I-rule в `scripts/seed.py` + `tests/test_links.py::test_goods_received` (wms `on_goods_received` в `modules/wms/events.py` не создаёт StockMovement) — оба вне зоны reference, маршрутизируй владельцам (блокируют общий lane-гейт).
- - `2026-06-28 18:02` · сессия `bfb82d3b` · **КООРД:** DONE wms — общий lane_check разблокирован: `test_links::test_goods_received` приведён к QC-гейту приёмки (Receipt pending_qc без движения; зеркало StockMovement — при QC-accept по факту). Поведение менялось намеренно (круг 2, _tz_wms.md), хендлер не трогал. test_links 20/20. Коммит super 6d94627, не пушено. [%: 72] (круг 3 закрыл интеграцию: модуль публикует wms.stock.low→procurement и wms.shipment.completed→office + оценка остатка в деньгах; backend≈85, frontend≈80).**
- - `2026-06-28 18:02` · сессия `2270ceed` · **КООРД:** DONE procurement — круг 4 **B2**: подписка `reference.ref_tnved.changed`+`reference.sku.changed` → дебаунс-пересчёт плановой (estimated) landed через готовый фасад `sku_master.landed_inputs`+`allocate_landed_cost`; факт важнее оценки в фасаде. Миграции НЕТ. **§2 DEPENDENCY-MAP (за тобой) — новое ребро `reference → procurement` (потребитель `reference.ref_tnved.changed`/`reference.sku.changed` `{action,ref_key,entity_ref,value_hint,actor}`; шина без wildcard — по конкретным типам).** НДС/курс оставил Финансам (НДС возвратный/PO в BYN). Локально: ZAK-3 `8be7155`, super `071a267`, НЕ пушено. **Сиблинг-шум гейта (не мой):** seed.py ruff, prod-guard import-main (security), WMS test_links (`4e09c6a` сменил `on_goods_received`). [DoD: ✓review(code-reviewer, 0 issues) ✓tests(9 нов.+184 pytest) ✓lint(мои файлы ruff) ✓no-migration ✓commit(локально по именам+gitlink) ✗push(правило)] [%: 70]
- - `2026-06-28 18:45` · сессия `d9f87a8c` · **КООРД:** INFO hr — контракт hr.payroll.* зафиксирован: accrued{employee_id, employee_name, period:"YYYY-MM", amount_byn:str(BYN), entity_ref:"payroll:<id>"}→Payment(payroll,pending); paid{employee_id, period, amount_byn:str(BYN), entity_ref:"payroll:<id>"}→settle by entity_ref→paid. Граница: только hr.employee (OpEx), цеховой ФОТ у production read-only без событий — двойного счёта нет. finance Р5 можно размораживать.**
- - `2026-06-28 18:48` · сессия `ce567d7c` · **КООРД:** DONE finance — Круг 5 харднинг (commits 8d274c3 в fin-7, 8ec3cbd в super); 3 реальных бага в reconcile_with_onec починены (дубли ref+cp / Payment без УНП / float() на '100,00'); +7 тестов (К5-1..К5-3 PASS) + 1 xfail (К5-4 money-str scan); 54 pytest PASS. NEEDS-ARB: money-выходы в API остаются float — приоритет №1 PLATFORM.md, переход на str ломает фронт; жду решения по вариантам A/B/C (моя рекомендация A с правкой фронта 2-3ч). Баги списком: reconcile-dup-collapse, reconcile-no-cp-collapse, reconcile-comma-crash — все починены [%: 100]
- - `2026-06-28 18:49` · сессия `c3a71f5f` · **КООРД:** DONE logistics — круг5 харднинг (4/4): R5-1 outbox-helper изолирован • R5-2 _looks_like_import таблица 31 кейс (РФ внутр., CN/UA/PL/DE/TR импорт, FOB/CIF/EXW/DAP, ISO2/ISO3/кириллица/латиница, пробелы/None/регистр) • R5-3 bid_risk медиана из 1/равные/выброс + защита от /0 на price=0 и all-zero + граница 25.0% и 24.9% • R5-4 import.received + freight.cost без подписчиков relay_once не падает, processed_at+AuditLog проставляются. DoD: ✓ `lane_check.py logistics GATE PASS` ✓ `import main` ✓ ruff clean ✓ pytest 101 PASS (+18 новых). Submodule logistics не трогал → bump НЕ требуется; коммит `c532ecc` локальный, не push. Без миграций. [%: 95]**
- - `2026-06-28 18:51` · сессия `2270ceed` · **КООРД:** DONE procurement — круг5 харднинг: 5 edge-тестов (дедуп MRP-lite пост-commit / обратный waterfall при недостижимом сроке / estimated не перетирает actual / reference-дебаунс идемпотентность между батчами / claim.resolved без дубль-эмита). Все 5 закрепляют существующие гарды (кругов 3-4), каждый **падал бы при снятии гарда** (доказано по конструкции). 203 procurement/landed PASS, ruff чисто, tests-only (без правок submodule → без gitlink). Локально `a6f1552`, НЕ пушено. **Багов НЕ найдено — все гарды на месте.** [DoD: ✓gate(pytest 203) ✓non-tautology(каждый тест пинит named-гард) ✓ruff ✓commit(локально по имени) ✗push(правило) ✗submodule(не трогал)] [%: 70]
- - `2026-06-28 18:51` · сессия `2270ceed` · **КООРД:** INFO procurement — потенциальный, НЕ почивший (для трекинга, не баг): после приёмки плановая `estimated`-строка SKU остаётся stale в таблице (фасад её не отдаёт — `_ACTUAL_FIRST`, безвредно), не чистится. И известный Горизонт-2 разрыв: факт (`_fixate_landed_cost`) опускает пошлину, оценка её включает → число «падает» при приёмке. Под обоими — spawn_task `task_fc401241` (внести пошлину в факт, чтобы план↔факт сошлись).
- - `2026-06-28 18:51` · сессия `bfb82d3b` · **КООРД:** DONE wms — круг5 харднинг: +5 edge-тестов (QC-гейт/идемпотентность accept, oversell-кламп+дедуп low-stock, RBAC воронки 403, сверка не перетирает 1С, цикл-каунт adjustment+деньги). lane_check wms GATE PASS (51 passed). Багов 0 — фиксы кругов 2-3 держатся, NEEDS-ARB не нужен. Коммит super 49c7c83, не пушено. [%: 73] (закрыт хвост «тесты узкие» из readiness-ноты wms).**
- - `2026-06-28 19:01` · сессия `73bd6c8c` · **КООРД:** DONE reference — круг5 харднинг: SCD2-инварианты (новая закрывает старую, ровно одна открытая, отказ не-возр. start, as_of-границы) + refs.view RBAC sweep (все query/MDM-reads→403, снятие гейта=красный) + reference.sku.changed (правка→1 событие entity_ref+value_hint; ФИКС: no-op PATCH больше НЕ эмитит/не плодит версию — доказанно красный на старом коде) + 1С read-only инвариант (base_url=None/недостижимый OData→mock/None без throw; нет write-методов). 109 reference-тестов PASS, ruff чисто, import main OK. Коммит 602ebf4 локально, НЕ push. БАГИ: [1] FIXED no-op эмит reference.sku.changed; [2] INFO — partial-unique индекс SCD2 (end_date IS NULL) на общих таблицах всё ещё отсутствует, гонка двойной открытой версии не защищена БД (отложено кругом 2, нужна координированная миграция). Граф §2 не меняю (reference.sku.changed уже сообщён кругом 3, новых рёбер нет). [DoD: ✓tests(109) ✓import-main ✓lint ✓red-on-old-code ✓commit ✗push] [%: 92]
- - `2026-06-28 19:06` · сессия `1b5d8576` · **КООРД:** DONE sales — круг5 харднинг 5/5: 2 реальных бага найдено+починено (R5-3 чужая стадия воронки→422; R5-4 ДЕНЬГО — margin при слепом landed-фасаде отдавал gross=0 вместо honest-null, теперь priced==0→None + forecast gross_weighted=None), оба падали на старом коде; R5-1/R5-2/R5-5 — guard-тесты (границы штрафа/дата-edge/идемпотентность handoff). lane_check sales=GATE PASS (1001 passed). Коммиты локально: sub a396a0e, super 0c01360 (bump gitlink), НЕ пушено. INFO найдено-непочинено: (1) funnel-only PATCH оставляет чужую стадию → off-board (существующий ponytail, не регрессия, кандидат на фикс); (2) ship_deadline str→date в будущем сломает falsy-guard очистки. [%: 88]

**Свежие пуши (PUSH-LOG.md):**
-   файлы: .githooks/pre-commit, .githooks/prepare-commit-msg, CLAUDE.md, scripts/coordination_hook.py
- - `2026-06-28 14:01` · сессия `c5a977e6` · ветка `sales-2.0-redesign` · **5b746ef** merge: реконсиляция origin ↔ local (sales-2.0-redesign)
-   файлы: core/services/reference_query.py, frontend/src/components/deal-metrics.tsx, frontend/src/components/source-tag.tsx, scripts/seed.py, tests/test_reference_tnved.py, zak-cost-calc-preview.html
- - `2026-06-28 18:01` · сессия `c5a977e6` · ветка `reconcile/krug4-2026-06-28` · **071a267** feat(procurement): reference→landed пересчёт (круг 4 B2) + тесты + bump gitlink
-   файлы: modules/procurement, tests/test_procurement_reference_recompute.py

**Недавняя активность (.activity.local.md):**
- - 2026-06-30 00:06 · commit · sales-2.0-redesign e19c084 · "fix(wms/fe): убрать \"\" sentinel из REASON_LABELS — чистый публичный контракт" · 2 файл(ов)
- - 2026-06-30 00:10 · commit · sales-2.0-redesign 7bcf78d · "test(wms/fe): покрыть reasonLabel('') — guard if (!reason) return '—'" · 1 файл(ов)
- - 2026-06-30 05:13 · commit · sales-2.0-redesign 0ee244f · "feat(prod-events): Production подписывается на sales.deal.handoff + procurement.order.received" · 3 файл(ов) · ⚠ миграция (сверь единственный head — §5)
- - 2026-06-30 05:13 ·   └ submodule modules/production: 0 нов. коммит(ов) · 2ff2125→6bfb7f7
- - 2026-06-30 00:11 · commit · sales-2.0-redesign 177919d · "fix(prod-events): переименовать мигр. 0041→0080 (коллизия с sales_call_log)" · 1 файл(ов) · ⚠ миграция (сверь единственный head — §5)
- - 2026-06-30 00:13 · commit · sales-2.0-redesign 0d0d798 · "feat(sales-rop-plan): РОП план/факт — вкладка + компонент + тесты" · 4 файл(ов)

<!-- /COORD:AUTO -->
