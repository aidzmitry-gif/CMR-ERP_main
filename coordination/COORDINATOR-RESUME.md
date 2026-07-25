# RESUME — координатор флота

> Читается сразу после компакта.

## 🟢 СОСТОЯНИЕ 2026-07-16 (сессия `0a661d5a`, оператор на связи; подготовлено к `/compact`)

**Роль подтверждена оператором явно: «ты и есть координатор»** — не передавать долги мифическому
координатору, они мои. Полоса продаж+координация ведётся из ЭТОГО чата.

### Git (сверено, не по памяти)
- `origin/sales-2.0-redesign` = **`caca243`** (2026-07-16, FF `d1b0c2c→caca243`, пуш из worktree
  `_wt_office_seam` ветка `office-payment-seam`). **Непушеного НЕТ**.
- 🚀 **РЕЛИЗ ГОТОВИТСЯ (промоут redesign→main).** ⚠ Промоут-ветку **`4deccc4`** НАДО ПЕРЕСОБРАТЬ:
  она мержила `origin/main` в `d1b0c2c` и фикса `caca243` (шов оплата→офис) НЕ содержит. При выкате —
  заново `git merge origin/main` в `caca243` (дерево==caca243, main FF без force). Ждёт: (1) secure-env
  прода на сервере (`AIOS_ENVIRONMENT=prod`+oidc+realm — иначе вход без пароля), (2) команды оператора
  на push→main + деплой. Релиз-гейт зелёный (gitlinks, head — см. `scripts/next_migration.py --peek`
  (инвариант: ровно один head), ruff, import main, **1386** pytest).
- ✅ 🔴💰 **Шов «оплата → офис» ОЖИВЛЁН+ЗАПУШЕН (`d1b0c2c→caca243`, последняя находка аудита).**
  Корень: office хранил `sales_ref`=НОМЕР сделки (строка), а `finance.payment.received` несёт `deal_id`
  (int) — строкой не совпадали → оплата не двигала документ в «Оплачено», просрочка капала по
  оплаченному. Тест был зелен на синтетическом `{finance_ref}` (ключа нет в событии). Фикс: мигр. 0105
  `office_doc.deal_id` (общий ключ) + `on_deal_won` пишет deal_id + `on_payment_received` матчит по
  deal_id и УВАЖАЕТ частичную оплату (outstanding>0 → не закрывать, PLATFORM #1) + гард `stage==paid`
  в лестнице эскалации. Гейты: 1386 pytest · ruff · голова — из `scripts/next_migration.py --peek`
  (инвариант: ровно один head). **Открытых находок аудита больше нет.**
- 🔴→✅ **Whole-system аудит перед промоутом поймал 2 прод-блокера (per-lane 1385 тестов не видели),
  оба ПОЧИНЕНЫ+ЗАПУШЕНЫ** (`cb63330→d1b0c2c`, супер `d1b0c2c` + fin-7 `a7de3ef`):
  1. 💰 finance `on_claim_resolved` сверял по `resolution` вместо `status` → компенсация поставщика
     молча выпадала из кассы/маржи (PLATFORM #1). Тест был на неверном контракте — приведён к реальному.
  2. 🔒 `GET /integrations/1c/stock` отдавал себес/цены анонимно + `POST /1c/sync` мутация без права →
     `require_permission` (sales.deal.read / integrations.sync) + тест 403/200.
  Не-блокер finance→office шов оплаты — **ТОЖЕ ЗАКРЫТ** (`caca243`, см. Git-блок). Миграции/оверинж — чисто.
- ✅ 360°-история касаний ВКЛЮЧЕНА (`1fa30b1→7216fad`): субмодуль sales `aaf899c` (`SalesTouchHistory`
  наполняет `core.services.touch_history` — звонки/сообщения/сделки; push FF в CRM.git
  `reconcile/sales-2.0-fleet-merge`) + супер bump gitlink + 2 теста. Карточка контрагента отдаёт
  реальную историю. Гейты: import main · 8 тестов (изоляция/graceful/порядок) · ruff.
- ✅ Хардининг 1С (`7216fad→cb63330`): warning на старте при http+логин (Basic-auth открытым текстом);
  https не форсим (LAN-1С без TLS). Закрыл low-хвост адверс-ревью влития 1С.
- 🔴💰 Живая 1С ВЛИТА+ЗАПУШЕНА (`2e9c42d→1fa30b1`, 2026-07-16, команда «влить сейчас»): cherry-pick
  `8aa5da7` → `2c2051e` (PriceCostGateway `StockPriceCostSource` из `StockItem`, source=onec) +
  `1fa30b1` мой фикс прод-блокера. **Адверсариальная проверка (3 линзы) поймала CRIT**: top-level
  `import requests` в `integrations/client.py` на пути старта, а `requests` НЕТ в requirements
  (только httpx) → прод-образ упал бы `ModuleNotFoundError` при create_app; локально маскировал
  requests в dev-venv. Порт на httpx. Гейты: import main OK · 14 тестов · ruff · миграций нет.
  Реквизиты `seller_*` целы (сверено), креды 1С пустые дефолты (в git секретов нет).
- Дедуп доски ВЛИТ+ЗАПУШЕН (`9e1e46b→2e9c42d`, 2026-07-16, по команде «свести и запушить»):
  `a588900` baseExtras (cardExtras/combinedCardExtras) · `2e9c42d` patchStages/nextStepFields (`board.ts`).
  Совмещённые гейты tsc0/vitest **883** зелёные; чистый worktree от origin-tip, инвариант `onLose` сверен.
- Три ревью-фикса ЗАПУШЕНЫ ранее (`f85f932→9e1e46b`): `44aa6de` 🔴ДЕНЬГИ (БИК `ALFABY2X` + убран код
  чужого банка — верные реквизиты теперь в origin, сверено `git show origin:config/settings.py`) ·
  `08801d7` слепота индикатора «горит» (crit по полной очереди) · `9e1e46b` /simplify (−5 строк).
- Локально HEAD `0daffe5` отстаёт от origin (дедуп пушился из temp-worktree) + «ahead/behind» ДУБЛИ
  старых хешей после cherry-pick, НЕ потеря (git cherry=0).
  `reset --hard` НЕ делать (общая ветка + снесёт чужое незакоммиченное). Сведение — мерж-union отдельно.
- Субмодуль `modules/sales` = `f612f3a`, запушен в CRM.git — gitlink достижим.
- Голова миграций: см. `scripts/next_migration.py --peek` (инвариант: ровно один head, форка нет).

### ✅ ДВЕ ФОНОВЫЕ СЕССИИ ДЕДУПА — ВЛИТЫ И ЗАПУШЕНЫ (2026-07-16)
- `cardExtras` (сессия `local_766d8a70`, worktree `elastic-brattain-7453ba`) → коммит `a588900`.
- `patchStages` (сессия `local_003c8e9a`, worktree `magical-cannon-cda87a`) → коммит `2e9c42d`.
- Обе стартовали от `0daffe5` (мой crit-фикс в базе — не откачен, сверено). Два патча к
  `deals-workspace.tsx` слились ЧИСТО (последовательный dry-run), собраны в чистом worktree от
  origin-tip, гейты tsc0/vitest 883. Их worktree/ветки (`claudeSalim/compassionate-sanderson-e2ccfd`,
  `claudeSalim/magical-cannon-cda87a`) держат теперь ИЗБЫТОЧНЫЙ незакоммиченный дифф (уже в origin) —
  **можно ретайрить** (worktree remove --force + branch -D), но это чужие idle-сессии → по решению оператора.

### 🔴 Незакоммичено в дереве — только ЧУЖОЕ, НЕ трогать
- Все МОИ правки этой сессии ЗАКОММИЧЕНЫ (3 коммита выше, ждут пуша). Дерево по моим файлам чисто.
- **ЧУЖОЕ — НЕ коммитить, НЕ откатывать:** `.claude/launch.json` ·
  `frontend/src/components/erp/logistics-scorecard.tsx` ·
  `frontend/src/components/kanban/catalog-picker-modal.tsx`.
  ⚠️ Часть числится `M` из-за нормализации CRLF→LF, а не содержимого — сверяй `git diff`, не `git status`.
- `coordination/{ACTIVE-SESSIONS,COORDINATOR-RESUME}.md` — untracked **by design** (не коммитятся).
- Коммит/пуш — ТОЛЬКО по явной команде оператора; `git add` по именам; перед коммитом
  `git diff --cached --name-only` (общий индекс флота!).

### Решения — ВСЕ ЗАКРЫТЫ (2026-07-16, команда оператора «не должно быть хвостов»)
1. ✅ **`price_cost` — РЕШЕНО (влито).** `sales-1c-live` в origin (`2c2051e`+`1fa30b1`). Живой источник
   включается только при `onec_base_url` → в проде (1С не поднята) деградация честная. Хвост low
   Basic-auth/TLS — закрыт хардинг-warning (`cb63330`), https не форсим (LAN-1С без TLS).
2. ✅ **`touch_history` — РЕШЕНО (реализован).** `SalesTouchHistory` в sales (`aaf899c`) наполняет
   фасад, супер `7216fad`. 360°-досье с реальной историей. 8 тестов.
3. ✅ **Ветки/worktree — ретайрены.** `sales-1c-live` + 2 дедуп-сессии (`compassionate-sanderson`,
   `magical-cannon`) — worktree remove + branch -D (работа вся в origin).
4. 🟢 **Дивергенция локального `sales-2.0-redesign` (0daffe5 vs origin cb63330) — НЕ трогать.**
   `git cherry=0` → моего непушеного НЕТ, потеря исключена (артефакт cherry-pick-пушей).
   `reset --hard` НЕЛЬЗЯ: в дереве ЧУЖИЕ незакоммиченные сдвиги гитлинков `modules/{finance,
   marketing,procurement}` + правки launch.json/logistics-scorecard/catalog-picker — сброс снёс бы
   чужие полосы. Сведётся само при обычном `git pull` оператора. Это косметика, не долг.

### Сделано этой сессией
ЗАПУШЕНО ВСЁ (`08ad79a→cb63330`): реквизиты · фокус · скорборд · фикс фокуса · экран лидов ·
инфра координации (`a84e0c5`+`f85f932`) · ревью-фиксы (`44aa6de` деньги + `08801d7` слепота +
`9e1e46b` /simplify) · **дедуп доски (`a588900`+`2e9c42d`, из 2 фоновых сессий)** ·
**живая 1С price_cost (`2c2051e`+`1fa30b1`, влитие sales-1c-live + фикс прод-блокера)** ·
**360°-история касаний (sales `aaf899c`+супер `7216fad`)** · **хардининг 1С-http (`cb63330`)**. Непушеного нет.
Ревью гонялось ЧЕТЫРЕЖДЫ, каждый раз ловило реальный дефект: (1) ключ focusQueue по `STAGE_PROBABILITY`
работал на 1 воронке из 3 → позиция стадии; (2) `dirty` врал «0» при упавшем git → `_git` str|None;
(3) /code-review→/simplify — неверный банк в счёте + слепота индикатора «горит»; (4) влитие 1С —
top-level `import requests` уронил бы прод-образ (requests вне requirements) → порт на httpx.
Урок: адверсариальное ревью ДО пуша окупается каждый раз — особенно на деньгах/проде.

### ⚠️ Починена инфраструктура видимости (важно знать)
`COORD:AUTO` в `STATUS.md` был **СИРОТОЙ с 2026-06-30**: маркеры лежали, а писать их было НЕКОМУ
(`readiness.py` рендерил только `READINESS:AUTO`; grep по репо = 0 писателей). Экран 2 недели врал
(HEAD `0d0d798`, ahead 51, голова 0080) и при этом скрипт рапортовал «обновлено».
**Теперь блок рендерится в `readiness.py`** (git + голова миграций + детект форка; хвосты
REPORTS/PUSH-LOG/.activity убраны — дубль SessionStart-хука) + фикс кракозябр (`encoding="utf-8"`,
иначе git-сообщения идут через cp1251-локаль). **Урок: не верить авто-блоку по дате в шапке —
проверять, что его кто-то реально пишет.**

**Серверы:** dev backend :8000 / frontend :3210 — **погашены** (реапнуты на границе хода). Поднимать
при надобности: PowerShell `Start-Process` detached (Bash `&` реапится); скрины `/crm/*` — Playwright
(preview виснет на SSE).
**dev.db** наполнена реальными ноябрём-2024 + декабрём-2025 — не пересоздавать бездумно.

---

## (архив) СОСТОЯНИЕ 2026-07-02 вечер

`origin/main` был сломан дублем ревизии `0044` → фикс PR #12 (`e1dfd35`, renumber `0044_leads_init`
→`0087`). PR #8/#11 — superseded, ждут явной команды на закрытие. Fable 5 (`claude-fable-5`) —
доступен, $10/$50, ВНЕ тиринга: звать точечно, только если Opus 5 доказанно не тянет (канон —
MODEL-TIERING.md).

---

## (архив) RESUME ночной смены — оркестратор headless-воркеров

> Оператора нет ~7–8 ч. Ты Opus, рулишь флотом headless-воркеров.

## Немедленно
1. Прочитай **`coordination/SHIFT-PLAN-2026-07-01-night.md`** — это твой план на смену (волны, тиринг моделей, гейты, пуш-политика, арбитраж).
2. Состояние на момент компакта: **план записан, воркеры ЕЩЁ НЕ спавнены.** Следующий шаг — **Wave 0 (сетап)**, затем спавн **Wave A** (5 воркеров).
3. Тиринг моделей — ЖЁСТКО: Sonnet дефолт, Opus только деньги/безопасность/схема/арбитраж, Haiku — быстрая механика; Fable 5 — ВНЕ тиринга ($10/$50), звать точечно. Ставится строкой `model:` в scope-файле воркера (`LOOP CONTRACT`).

## Инструмент
`& ".\.venv\Scripts\python.exe" spawn_workers.py <health|spawn|status|tail|respond|integrate|cleanup>`
Скилл — `orkestrator-lead`. Под каждого воркера: `coordination/first-msgs/<name>.md` (задание) + `coordination/<name>-scope.md` (LOOP CONTRACT + `model:` + include/exclude + budget).

## Ключевые факты
- Ветка работы: **`sales-2.0-redesign`** (HEAD синхронен origin на момент компакта: b88f4b6). Воркеры ветвятся от неё (проверь BASE_BRANCH в spawn_workers — Wave 0 п.1).
- Голова миграций: **0082**. Номера раздаёшь ТЫ через `scripts/next_migration.py`. Резерв: service=0083, scd2=0084, legal=0085, knowledge=0086.
- Гейт воркера: `lane_check.py <lane>`/pytest зелёный + ruff + tsc(фронт) + import main. Только тогда `STATE: COMPLETE`.
- Пушишь зелёное в origin/sales-2.0-redesign (submodule → gitlink bump → super). Сервер НЕ трогаешь.
- Каждое арбитражное решение → `coordination/REPORTS.md` строкой `КООРД:` + метка ⚠REVIEW.

## Твой цикл (на /loop, self-paced)
status → интегрируй COMPLETE → ответь NEEDS-ORCHESTRATOR-ANSWER → досыпь волну до 5 слотов →
пуш → обнови readiness.json/DEPENDENCY-MAP/REPORTS.md → **обнови ЭТОТ файл** (§ниже) → ScheduleWakeup ~20–30 мин.

## Компакт переживаю сам (авто-компакт ВКЛючён, срабатывает без оператора)
Авто-компакт срабатывает самостоятельно у потолка контекста — оператор не нужен. Чтобы он был безопасен,
КАЖДЫЙ заход цикла обновляю блок «Состояние» ниже: текущая волна, занятые слоты (воркер→полоса→модель),
голова миграций, что интегрировано/запушено, открытые NEEDS-ANSWER. Тогда после любого компакта я читаю
этот файл и продолжаю с той же точки, ничего не теряя. PreCompact-хук уже пишет readiness перед компактом.

### Состояние (обновляю каждый тик)
- Волна: **Wave B ЗАКРЫТА — 5/5 ИНТЕГРИРОВАНЫ+ЗАПУШЕНЫ** (origin/sales-2.0-redesign до `b664b26`): scd2(0084,4cb4de4) · legal-knowledge(0085/0086,86d8376; перепин 0085.down→0084) · security-p1-2(свип runtime-fix 80922e9) · landed-duty-fact(procurement ZAK-3 282339c→wave-b-integ; оракул plan↔fact ЗЕЛЁНЫЙ; d2126ca) · sales-e2e-board(playwright deals-board b664b26). Гейты зелёные. Procurement 76→78. Слоты очищены (active=1).
- **Wave G ФРОНТ ГОТОВ+ЗАПУШЕН+ПОКАЗАН, «Мой день» УПЛОТНЁН по просьбе оператора (последний коммит fd1928f):** `/erp/hr/worktime` — 3 таба (Мой день/Кто онлайн/Табель T-13) в реальном AppShell. «Мой день» переделан на компактные КПЭ-карточки (число/цель+светофор-бар+«% выполнено», визуал как `components/kpi-card.tsx`/План-Факт) + полоса-сводка + компактный таймер. Коммиты: 9c622b4 (страницы) → fd1928f (компакт «Мой день»). tsc чист, показано live.
  - ⚙️ **DEV-СЕРВЕРЫ ПОДНЯТЫ для оператора:** backend uvicorn :8000 (bg) + frontend :3210 (bg, BACKEND_URL=127.0.0.1:8000). Оператор смотрит на http://127.0.0.1:3210/erp/hr/worktime (dev-login Директор). **ПОСЛЕ КОМПАКТА: спросить/выключить серверы, когда оператор досмотрит** (Stop-Process по портам 8000/3210).
  - ЖДЁТ решения оператора: (а) уплотнить так же «Кто онлайн»/«Табель», ИЛИ (б) 5 вопросов спеки → бэкенд (work_session/норма/timesheet + core approvals) + живые данные. Скрин-паттерн: http.server или dev-стек + Playwright (dev-login /login combobox Директор).
  - Хвосты: отклонённый hr-worktime.html (31c9055) в корне лишний (спросил снести); ghost-dir crm-worker-hr-worktime-mockup залочен (cruft, снести позже). Реюз: `components/kpi-card.tsx` (КПЭ-карточка), `components/erp/office-claims-view.tsx` (стиль view), `sales-board-mockup.html` (эталон шелла).
- (архив пути) Wave G мокап-подход: HTML-мокап-воркеры (mockup/mockup2) ОСТАНОВЛЕНЫ. Идёт **`hr-worktime-fe`** (frontend, live): `/erp/hr/worktime/page.tsx` (AppShell) + `components/erp/worktime-view.tsx` (3 таба: Мой день/Кто онлайн/Табель) стилем как `office-claims-view.tsx` + demo-данные + пункт сайдбара «Учёт времени» в HR. Дизайн наследуется из AppShell (не верстает шелл). DoD: tsc --noEmit чисто + рендерится.
  Как COMPLETE → интегрировать 3 файла → поднять dev (backend :8000 + frontend) → Playwright /erp/hr/worktime, скрин 3 табов (осторожно SSE-хэнг, dev-login /login combobox) → ПОКАЗАТЬ оператору → commit+push.
  Хвост: hr-worktime.html (отклонённый мокап, 31c9055) на ветке — можно удалить при интеграции или оставить. Ghost-dir crm-worker-hr-worktime-mockup(+2) залочены — cruft, снести позже. active=1.
- **security-sweep: ПОЧИНЕН и ПОДТВЕРЖДЁН В CI (8cef51d).** Backend-run 8cef51d: sweep УШЁЛ из фейлов, 1175 passed — RBAC-инвариант реально гоняется в CI. Все МОИ CI-регрессы закрыты+верифицированы (money=str · procurement-oracle · e2e-webServer · security-sweep). Остаток backend-фейлов = ровно 6 пре-существующих (rop_plan×3 time-bomb, postgres×3 integration) — в чипе task_f234cb70, НЕ мои. Ниже — как оно было (диагностика):
- (архив) security-sweep DIAG путь: CI-DIAG: `app.routes=24` (модульные роуты НЕ смонтированы на инстанс app в CI!) при populated реестре (core.routers=16, prefix_map=14) — middleware работает (403 в postgres), conftest.api монтирует, а мой app-инстанс под полным CI-прогоном — нет (build-order/shared-router; локально не воспроизв., 3× create_app=403). Фикс: перечислять write-роуты из РЕЕСТРА `core.routers` (reg.prefix+reg.router.routes) — источник как у middleware, populated в CI. + диаг per_router_route_counts на случай пустых роутеров. Локально 4 pass. **След. тик: проверить run на 8cef51d — свип зелёный ИЛИ per_router покажет пустые роутеры.** Предыдущие попытки: runtime-fix 80922e9, диаг a19aa95.
- Флот idle (active=0). Волны D/E/F в SHIFT-PLAN queued — НЕ спавнил (оператор активен, Gate 1 pending, жду DIAG). Спавнить D, если оператор тих и DIAG обработан.
- ⚠REVIEW **ЧЕЙН ALEMBIC ПОЧИНЕН** (942ad2b): миграции 0053/0076 (finance, ветка freight-finance d054ddd) лежали в рабочем дереве UNTRACKED, но committed 0054/0077 на них ссылались → committed sales-2.0-redesign чейн был битый (KeyError 0053, guard видел головы 0052/0075). Клон+alembic падал бы. Добавил 2 файла (канонические, идентичны freight-finance) → голова снова единственная. Провенанс: freight-finance; НЕ на main/origin/main тоже.
- **2/5 воркеров УПАЛИ на ConnectionRefused ~09:00** (провал интернета у оператора) — landed-duty-fact + sales-e2e-board. Интернет восстановлен → ОБА ПЕРЕ-СПАВНЕНЫ (worktree сохранил partial: sales-e2e имел uncommitted playwright.config+deals-workspace testid; landed — прогресса ~0). active=2. Проверить их следующим тиком; landed-duty оракул `tests/test_procurement_landed_duty_fact.py` (мой) на месте, фикс в preview.
- ⚠ landed-duty-fact ПРЕМИСА ИНВЕРТИРОВАНА при заземлении: факт (`_fixate_landed_cost`) пошлину УЖЕ применяет (круг4 B2); разрыв в ПРЕВЬЮ `landed_preview()` (роут GET /orders/{id}/landed-preview) — оно зовёт `_order_allocation()` без пошлины. Фикс — в ПРЕВЬЮ (не в факте), по образцу _fixate_landed_cost. Оракул `tests/test_procurement_landed_duty_fact.py::test_landed_plan_fact_reconcile` (мой, воркер не трогает). Правка в submodule procurement → bump gitlink.
- След. тик (будильник ~08:43): `status` → интегрировать COMPLETE (порядок миграций 0084→0085→0086!) → ответить NEEDS-ANSWER → пуш зелёного → readiness/REPORTS → досыпать/спавнить Wave C. Гейт как в Wave A: lane-тесты+ruff+import main+tsc(фронт). Прежде чем интегрировать submodule-коммит — синхронизировать working copy (`git -C modules/<x> checkout <sha>`), иначе тесты против старого кода.
- ⚠REVIEW АРБИТРАЖ (02.07): **security-p1-2-rbac ПЕРЕ-СКОУПЛЕН** с «per-endpoint require_permission в 8 submodule-ях» на **CORE-LEVEL** (только `tests/test_security_rbac_sweep.py` + при дыре `core/runtime/access.py`/`config/access.py`). Причина: (1) `AccessControlMiddleware` УЖЕ режет 403 по префиксу модуля для всех методов вкл. write → per-module require_permission дублирует; (2) 8-submodule blast radius столкнулся бы с незареконсиленным Wave-A submodule-состоянием (finance/marketing/service на wave-a-integ). Fine-grained per-endpoint → Wave F `security-p1-3`. Спавнить прежнюю смену турна — НЕ трогать (сделано). Скоуп/first-msg переписаны мной.
- **Миграции Wave B ПРЕ-АЛЛОЦИРОВАНЫ мной** (воркеры НЕ зовут next_migration.py, используют выданное): scd2=**0084**(↓0083) · legal=**0085**(↓0084) · knowledge=**0086**(↓0085). Голова была 0083. Цепочка линейна — ИНТЕГРИРОВАТЬ В ПОРЯДКЕ 0084→0085→0086 (если scd2 0084 не сядет, перепин down_revision 0085 на 0083).
- Wave B воркеры: legal-knowledge[sonnet,0085/0086] · security-p1-2-rbac[opus,нет] · landed-duty-fact[sonnet,оракул мой] · scd2-partial-unique[opus,0084] · sales-e2e-board[sonnet,нет].
- ⚠ ОПЕРАТОР (02.07): «не прерывай работу, делай сам» — НЕ спрашивать на границах волн, катить автономно; оператора только на неразрешимом блокере/утреннем выходе. Память [[autonomous-shift-no-stopping]].
- Wave A: origin/sales-2.0-redesign `b88f4b6..f2000c0` (7 коммитов). Гейт зелёный: ruff · 91 тест · import main · tsc.
  Полосы: hr-payroll→65 · service-intake→35 · marketing-phase-e→35 · finance-money-str[opus]→98 · sales-ux→89. Все 5 COMPLETE.
- Submodule-коммиты опубликованы на ветке **`wave-a-integ`** (НЕ main — классификатор блокит push в submodule main): hr d4d96e0(HR-10) · service 69e0f9d(SER-POD-9) · marketing 76c0f1d(MAR-8) · finance aa0f484(fin-7). Gitlink'и клон-консистентны.
- **CWD-БАГ ИСПРАВЛЕН** (`_wave-a-packet-spec.md`): воркер работает В СВОЁМ worktree; НЕ упоминать путь главного репо, НЕ `cd` туда — иначе коммит в общую ветку в обход изоляции (случилось в Wave A с hr/service/sales-ux; свёл checkout+cherry-pick). Лаунчер (spawn_workers:574) сам ставит cwd=worktree.
- Урок submodule-достижимости: объект воркера тянуть в главный store через врем. ветку (`git -C <worker-sm> branch -f _integ <sha>` → `git -C modules/<x> fetch <worker-sm-path> _integ`), затем `git -C modules/<x> checkout <sha>` (иначе тесты против старого кода — 24 finance-теста так падали).
- Push-гард общей ветки: >1 коммита блочит; обход `AIOS_ALLOW_PUSH=1` ТОЛЬКО когда origin ровно на прошлой точке (сверять `git log origin/BRANCH..HEAD` — чужих нет).
- Cap-урок: `_active_worker_count`=записи state с `spawned_at`+дир; чистить `sw._clear_worker_state(name)`.
- Модель: голая строка `model: sonnet|opus` в scope. Голова миграций: 0082 · резерв 0084 scd2/0085 legal/0086 knowledge/0087 hr-okk/0088 security/0089 procurement-po.
- PR #9 (sales-2.0-redesign→main): решение оператора — **НЕ трогать, релиз он сам**. Конфликты/CI PR не резолвлю.
- Волны в очереди: **B → C(резерв) → D → E → F**. Пакеты авторю just-in-time (спек исправлен). ⚠F: onec-mdm-read-bridge+sop-forecast — только чтение/спека.
- Следующий тик: спавнить **Wave B** (author 5 пакетов по SHIFT-PLAN: legal-knowledge, security-p1-2-rbac[opus], landed-duty-fact, scd2-partial-unique[opus], sales-e2e-board) с исправленным CWD-спеком → `WORKER_BASE_BRANCH=sales-2.0-redesign …spawn`.
- **CI PR#9 (ветка sales-2.0-redesign) — триаж 10 фейлов (06:33Z run):** ⚠ оператор релизит PR#9 сам, я НЕ трогаю мерж — но чиню СВОИ регрессы на ветке.
  - ✅ ПОЧИНЕНО+ЗАПУШЕНО (03325a4): money=str консументы test_erp::test_finance + test_links(summary ×2) — Wave A finance-money-str сделал finance_summary деньги строкой (намеренно); кросс-файловые тесты не обновили. Ассерты → str.
  - ✅ ПОЧИНЕНО+ЗАПУШЕНО (80922e9): **security sweep** — строил `_APP=create_app()` на collection-time → в CI пустой enumeration, свип 0 тестов (RBAC-инвариант тихо НЕ проверялся!). Перенёс app+роуты в **runtime module-scope фикстуры** (как conftest.api, на нём 1171 CI-тест зелёный); parametrize→цикл. Локально 4 pass. Ждёт CI-подтверждения (run на 80922e9).
  - ⏳ НЕ моё, пре-существующее (оставляю оператору для его релиза): **rop_plan ×3** — time-bomb: тест хардкодит period=2026-06, endpoint фильтрует Deal.stage_changed_at, сделка создаётся сегодня (July)→0. Фикс — семантика closed_date vs stage_changed_at (sales-lane). **test_postgres ×3** — Postgres-integration-only (403/relay), фикстура без X-User-Roles. **frontend pages.test ×5** — `<DealClient360>`/`<WmsPage>` async Client Component (Next.js). Ни один из этих файлов моим шифтом НЕ тронут (f2000c0..HEAD); мои новые office/claims+knowledge/enrollments pages — чистые sync-компоненты, не виноваты.
  - ИТОГ: все МОИ регрессы (money=str + sweep) починены+запушены. Ветка backend 10→(rop3+pg3)=6 пре-существующих (не мои); sweep -1 ждёт CI.
- Открытые NEEDS-ANSWER: —

## Компакт-дисциплина (экономия токенов — мой контекст = узкое место смены)
- Тяжёлые чтения/сканы — сабагентам (Explore) и воркерам; НЕ тащить большие файлы в свой контекст.
- Состояние — из STATUS-файлов, не пере-сканом. Ходы короткие, без пересказа сделанного.
- На границе волны (после интеграции+пуша), если контекст большой — предложить оператору `/compact`.
  Сам `/compact` вызвать не могу; в /loop харнесс суммаризирует между окнами; авто-компакт ~95% — нижняя страховка.

## Утренний выход
Сводка: что сделано по полосам (Δ% готовности) + список ⚠REVIEW-решений на утверждение + что осталось в бэклоге волн B/C.
