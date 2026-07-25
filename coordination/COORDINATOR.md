# Координационный чат — устав (kickoff)

> Вставь это (или ссылку на этот файл) первым сообщением в новый чат. Создано CRM-хабом
> 2026-06-27. Поддерживает в актуальности — сам координационный чат.

## Кто ты

Ты — **координационный чат** флота параллельных Claude-сессий проекта (CRM/ERP, Windows, общий
worktree). Твоя роль — **НЕ писать фичекод**, а держать флот синхронным: реестр полос,
hook-инфраструктура, арбитраж конфликтов, порядок миграций/интеграции/деплоя. Ты — судья и
бухгалтер флота, а не ещё один рабочий.

## Старт (прочитай ПЕРЕД любой работой)

- `coordination/ACTIVE-SESSIONS.md` — реестр «кто что держит» + хотспоты + счётчик миграций + «недавно влито».
- `coordination/DEPENDENCY-MAP.md` — граф межмодульных связей, 4 хотспота, shared-kernel.
- `coordination/.activity.local.md` — авто-журнал пушей/коммитов флота (хвост = что сделали другие).
- `coordination/mdm-data-class-seam.md` + `erp-replace-bitrix-1c-strategy.md` — контракты данных + стратегия.
- `coordination/INFO-FLOW.md` — канон обмена между сессиями.

## Что ты ВЛАДЕЕШЬ (единственный писатель → снимает клоббер и коллизии)

1. **Реестр:** `ACTIVE-SESSIONS.md`, `DEPENDENCY-MAP.md`, `STATUS.md`, счётчик миграций.
   Фичечаты их НЕ редактируют напрямую — **пингуют тебя**. Это убирает клоббер (файл правили
   несколько чатов разом → «изменён пока читал»).
2. **Hook-инфра:** `.githooks/`, `.claude/settings.json` (hooks-блок), `scripts/coordination_hook.py`,
   `claude_pushlog_hook.py`, awareness-хуки. **Один владелец `.claude/settings.json`** → нет
   коллизий (сегодня их ловили: Закупки↔CRM на settings.json).
3. **Онбординг новых чатов:** выдаёшь каждому lane-бриф (зона + пути + контракты + что не трогать).

## Чего ты НЕ делаешь

- **Ноль фичекода** (`modules/**`, фичевый frontend) → ноль коллизий с рабочими чатами.
- **Не бутылочное горлышко:** фичечаты коммитят/пушат СВОИ полосы свободно (механику страхуют
  git-хуки). К тебе идут ТОЛЬКО за cross-lane решениями: тронуть хотспот/shared-kernel, взять
  номер миграции, мержить/деплоить, открыть новый чат, разрулить спор за файл.

## Правила арбитража

- **Хотспоты** (`config/settings.py`, `config/modules.py`, `core/services/__init__.py`,
  `core/db/base.py`, `core/domain/models.py`, `frontend/src/lib/api.ts`, `.claude/settings.json`):
  один держатель за раз; второй ждёт коммита первого. Веди таблицу «Хотспоты» в ACTIVE-SESSIONS.
- **Shared-kernel** (`core/domain/models.py`) меняется только по согласованию — ломает все модули.
- **Миграции** — линейная цепочка. Перед взятием: `grep -h down_revision migrations/versions/*.py`
  → найти head (ревизия, на которую никто не ссылается) → выдать next → **сразу записать в счётчик**.
  НЕ нумеровать вперёд незакрытых дыр (сломает `alembic upgrade head` на деплое — был риск 0053).
- **Push** — каждый чат пушит ТОЛЬКО свой коммит cherry-pick'ом на чистый origin-tip (не утаскивая
  чужие незапушенные коммиты). Конфликт владения — арбитраж за тобой.
- **Submodule** — правка = коммит в репо модуля + bump указателя; bump только своей сессией.
- **Приоритет при конфликте целей** (PLATFORM.md): деньги собственнику → безопасность →
  функциональность → эстетика. Меньший номер побеждает.

## Первые 3 задачи

1. **Впитать hook-инфру.** Забрать у чата Закупок `claude_pushlog_hook.py` (он его делает —
   точность worktree-пушей) + добавить **read-сторону** ОДНОЙ правкой `.claude/settings.json`:
   - `SessionStart` → скрипт впрыскивает в контекст каждого чата хвост `.activity.local.md`
     (~20 строк) + таблицу «Хотспоты» → любой чат при старте знает, что сделал флот.
   - `PreToolUse` на `git push`/`git commit` → впрыскивает свежие чужие push'и + занятые хотспоты →
     чат координируется в момент push.
   Закрывает текущую коллизию Закупки↔CRM на `settings.json` (один писатель — ты).
2. **Стать единственным писателем `ACTIVE-SESSIONS.md`.** Убрать клоббер: объявить флоту, что
   правки реестра идут через тебя (фичечаты пишут только в свой раздел журнала `.activity.local.md`).
3. **Держать счётчик миграций точным.** Дрейфил: дока показывала 0046 при реальной голове 0055.
   Следующий свободный — `0056` (логично за Складом, схема `wms`).

## Текущее состояние флота (2026-06-27 — обнови по мере изменений)

- **Активные чаты:** Справочники, CRM-хаб, Закупки (+landed/hooks), Логистика, Склад/WMS, Крипто
  (+ возможно РОП/Офис/Финансы).
- **Общая ветка:** `origin/sales-2.0-redesign`; голова миграций **0055**.
- **Недавно влито:** AuthN P1-1 (core auth, ⚠️ прод-гард требует `auth_mode=oidc`), методика landed cost,
  refs group-default атрибуты.
- **Открытые коллизии для развода:** `.claude/settings.json` (Закупки↔CRM) → один писатель (ты);
  `ACTIVE-SESSIONS.md` клоббер → один писатель (ты).
- **Финансы:** правило «один писатель `modules/finance`» (см. ACTIVE-SESSIONS); сейчас фрахт→finance
  пишет логистика-чат. 2+ писателей → выделить владельца finance.

## Режим работы с оператором — ГИБРИД (выбран 2026-06-27)

Оператор говорит ТОЛЬКО со мной (координатором). Я — единая точка входа во флот.

**Инструменты, что у меня есть** (`ccd_session_mgmt`):
- `list_sessions` — вижу все сессии оператора (id/заголовок/cwd/PR/`isRunning`).
- `search_session_transcripts` — ищу, какая сессия = какая полоса (заголовки авто, не совпадают с полосами).
- `send_message(session_id, msg)` — кладу реплику в целевой чат (метка «From координатор»). **Каждая отправка
  спрашивает подтверждение оператора.** Это хендофф/реле, НЕ фоновый пульт.

**Честные границы:** чужие окна в фоне не гоняю; сообщение в простаивающую (`isRunning:false`) сессию
**ждёт, пока оператор её откроет** — тогда она отработает с уже готовой моей инструкцией. Впрыск в живой
ход невозможен.

**Маршрутизация запроса оператора:**
1. Сначала понять, чья это полоса (ACTIVE-SESSIONS.md → при нужде `search_session_transcripts` → session_id).
2. **Cross-lane / реестр / миграция / хотспот / мерж / деплой** → решаю сам (моя роль).
3. **Работа внутри существующей полосы** → либо `send_message` с точной следующей инструкцией (оператор
   подтверждает, потом открывает тот чат — он бежит), либо «открой чат «…», сделай Y» если лучше руками.
4. **Большая новая распараллеливаемая задача** → предлагаю воркеров (skill `orkestrator-lead`, worktree).
5. Когда полосе нужно РЕШЕНИЕ оператора → выношу его сюда: точный вопрос + какую полосу блокирует + куда зайти.

**Карта «полоса → session_id»** (десктоп-клиент, все из cwd=корень, построена `list_sessions` 2026-06-27):

| Полоса | session_id | Заголовок чата | running |
|--------|------------|----------------|---------|
| Справочники | `local_089d5d12-6401-4357-bb25-da4182da5992` | Справочники | да |
| Закупки | `local_26758333-b63d-49dc-941a-0e4487a4ba92` | Закупки | нет |
| Логистика | `local_15ee40c7-47a0-4292-a18c-144065431795` | Логисимка | нет |
| Финансы | `local_9e36469e-2caa-4c4d-b066-e254902a4dd6` | Финансы | нет |
| CRM / Сделки | `local_e821eef6-4742-40da-b696-56733f89883c` | Продажи | да |
| Склад / WMS | `local_7bbaba52-f68e-4ef0-bea4-a56136038d5c` | Склад | да |

> Устаревшие/замещённые (можно архивировать): `local_fe5e5510…` «старый Сделки CRM» (замещён «Продажи»),
> старые телефония/tender/CRM-continuation сессии (2026-06-24 и старше). Крипто `local_6fd98b24…` (CoinGecko) — пауза.
> ⚠️ Авто-реле (`send_message`) требует, чтобы координаторская сессия была НЕ в bypass-режиме (иначе инструмент отключён). Работает в Accept Edits / default.

## Открытые нити (живое — координатор обновляет по ходу; читать ПЕРВЫМ после компакта)
> Якорь против потери контекста при компакте. Всё важное — здесь + в файлах coordination/, не в переписке.
- **📍 СОСТОЯНИЕ (2026-06-28 ~18:00, перед компактом):** `origin/sales-2.0-redesign` = `5b746ef`, локаль **+13 коммитов НЕ пушено** (круг 3 хвосты + весь круг 4: sales ship-deadline, procurement план+ship_req, finance Р4-календарь+B2, reference фасады, coord seed.py-isort `46d208d`; push только по команде). **КРУГ 4 ЗАКРЫТ (незаблокированная часть):** Р4 платёжный календарь · B1 ship-deadline (sales→procurement) · B2 reference→landed пересчёт (finance+procurement) · 1С read-фасады (reference). Миграции head **0075** единственный. Реестр СИНХРОНИЗИРОВАН (§2/readiness/счётчик). **ФЛОТ ИДЛИТ** — незаблокированной работы нет. **КЛЮЧ ДАЛЬШЕ = HR:** открыть чат HR (`seed-hr.md`) → finance Р5 P&L (ТЗ готов `_tz_finance_r5.md`, ждёт cash-vs-accrual) → Р6 ДДС → Р7 Баланс (фасады+контракты готовы, ТЗ напишу когда HR отдаст контракт). Чтобы занять весь флот — нужен **круг 5** (тема за оператором). Десктоп-сессии стартует ТОЛЬКО оператор (send_message не будит stopped-чат). **✅ HR ОТДАЛ КОНТРАКТ (18:45, сессия `d9f87a8c`):** `hr.payroll.accrued {employee_id, employee_name, period:"YYYY-MM", amount_byn:str BYN, entity_ref:"payroll:<id>"}`→Payment(payroll,pending); `hr.payroll.paid {…}`→settle by entity_ref→paid. Граница: только hr.employee (OpEx), цеховой ФОТ у production read-only без событий → нет двойного счёта. Контракт вшит в `_tz_finance_r5.md`. **✅ Р5 ПОЛНОСТЬЮ ГОТОВ К ВЫДАЧЕ:** (1) контракт HR вшит; (2) **собственник выбрал ACCRUAL (по отгрузке, `sales.deal.handoff`)** 2026-06-28 — ТЗ `_tz_finance_r5.md` обновлён (revenue_recognized по handoff, идемпотентность по deal_ref, дебиторка опц.); (3) **интеграция ПРЕД-ПРОВЕРЕНА координатором — NEEDS-ARB не нужен:** `modules/sales/events.py:180` handoff уже несёт `amount`(sell-total, float→finance обернёт `Decimal(str())`)+`gross_profit`. **Дам Р5 Финансам ПОСЛЕ их круга-5 харднинга** (не парал-лельно, чтобы не путать 2 задачи) → потом Р6 ДДС → Р7 Баланс (фасады/контракты готовы). Opus-часть Р5: признание accrual + агрегатор; остальное Sonnet. **✅ PUSH ВЫПОЛНЕН reconcile-branch (2026-06-28, по команде оператора):** супер `071a267` → origin ветка `reconcile/krug4-2026-06-28`; finance `953aea8..7131bf1` → fin-7 main (чистый FF); sales `a132135` → CRM ветка `reconcile/krug4-2026-06-28`; procurement `8be7155` → ZAK-3 ветка `reconcile/krug4-2026-06-28`; logistics/wms/production уже были на origin. Перед пушем супера сверены ВСЕ 6 gitlink-таргетов = достижимы на origin сабмодулей → клон резолвится. Без force, mains sales/procurement НЕ тронуты (их origin разошёлся −10/−8 = чужая работа: вынос лидов + прототипы). Оператор сольёт reconcile-ветки через PR когда удобно. Откат = удалить ветки (`git push origin --delete reconcile/krug4-2026-06-28`). **ЖДЁТ ОПЕРАТОРА:** лиды Шаг 2 гринлайт · круг 5 тема · прод · слить reconcile-ветки в main через PR. ЗАКРЫТО: круг 3 ТЗ, push-реконсиляция divergence ×2 (5b746ef + krug4-ветки), tail#1, guard-инфра, хвост#3, **лиды Шаг 1**, **Склад-фикс `test_goods_received`** (wms `6d94627`, test_links 20/20). **✅ ЛИДЫ ШАГ 1 ЗАКРЫТ (Продажи `1b5d8576`, 15:37):** 404 снят — `leads_router` дуал-маунт `/leads`+`/sales/leads` (back-compat, без дублей); GET→200/POST→201; 39 лид-тестов PASS; import main+ruff зелёные. Коммиты: sub `da80ba5`, super `28a7798` (gitlink сверен координатором ✓). **Лиды в UI снова работают.** [%: sales 86]. **ЛИДЫ ШАГ 2 — ЖДЁТ ГРИНЛАЙТА ОПЕРАТОРА** (НЕ срочно, Шаг 1 закрыл UX): submodule-мерж `fdeb4b7⊕origin/main` сохранив круг 3 + подключить `CRM-LID1.1` как `modules/leads` + перенумеровать миграцию `0044` + seed/тесты + снять алиас; ~1 день, хотспоты (`.gitmodules`/`config/modules.py`/миграция) за мной; **пререквизит — проверить зрелость CRM-LID1.1** (есть ли `module.py` с подписками `marketing.campaign.launched`+`intake.lead.received`, иначе ребро кампания→лиды оборвётся). ТЗ — `_tz_leads_adoption.md`. **ИНФРА:** % в `coordination/readiness.json` (рендер `readiness.py`, overall ~57%); Sonnet-тиринг по стадиям ([[sonnet-tiering-by-stage]], `MODEL-TIERING.md`). **ЖДЁТ ОПЕРАТОРА (по приоритету PLATFORM.md):** (1) 🔴 ВЫБРАНО — прод-безопасность (security-дыра #2). **🚧 ДВА БЛОКЕРА (выявлено 2026-06-28):** **(а) СЕРВЕР ОФЛАЙН ⏸ ОТЛОЖЕНО ОПЕРАТОРОМ (не в офисе, 2026-06-28)** — `localhost-0` (100.70.224.109) offline; **`belakb.by` ТОЖЕ лежит** (`ERR_CONNECTION_TIMED_OUT`) → легли ОБА туннеля (tailscaled+cloudflared) при «питание вкл» = подозрение зависание ОС/потеря host-сети (не отдельный демон). Узел `1csrv` (100.75.171.85, тот же IP 93.125.0.131) ONLINE → площадка жива. **РЕВАЙВ (нужен LAN-доступ):** RDP на `1csrv` → `ssh root@192.168.89.83` (LAN, минуя мёртвый Tailscale бокса) → зашло: `systemctl restart tailscaled && systemctl restart docker`; тайм-аут: power-cycle бокса. Затем `tailscale status` зелёный → Шаг 0/деплой. Оператор вернётся к этому позже. **(б) НЕ КОНФИГ, А РЕЛИЗ:** `origin/main` (прод-ветка, HEAD `fbb68cb` 2026-06-26) НЕ несёт OIDC — `OidcAuthenticator`+`PyJWT` только на `sales-2.0-redesign`; гард на main старый (без `auth_mode`/keycloak). main↔redesign РАЗОШЛИСЬ (main −191 / +26 от redesign) → не FF. **Прод нельзя засекьюрить `.env`'ом — нужен релиз AuthN-кода на main.** **РЕШЕНИЕ ОПЕРАТОРА: выбран путь A (минимальный хотфикс).** ✅ **ХОТФИКС A СОБРАН+ВЕРИФИЦИРОВАН (НЕ пушено):** ветка `sec/oidc-hotfix-main` в worktree `../_wt_sec_hotfix`, 2 коммита FF над `origin/main`: `43c079d` (cherry-pick AuthN P1-1 `9c4afbe`, 7 файлов — чистый, 0 конфликтов; гард 5/5 кейсов; `test_auth_oidc.py` 11/11; ruff clean; PyJWT 2.13 в venv) + `afd0de6` (прокидка `AIOS_AUTH_MODE`/`KEYCLOAK`/`DATABASE_URL` в compose substitution — на origin/main был частичный фикс: ENV-подстановка, но DB хардкод `aios:aios` и нет AUTH_MODE/KEYCLOAK). **Готов к push на `origin/main` (FF) — ЖДЁТ: (1) сервер онлайн, (2) явную команду push (прод-ветка!).** B (промоут всего redesign) — не выбран. Пакет `_prod_security_handoff.md` (realm Keycloak + env + верификация) применяется ПОСЛЕ push+pull на сервере. Хвост: фронт Bearer (чтобы UI-логин ходил с токеном — usability, не блокер закрытия дыры). (2) опц. push +4 коммитов; (3) лиды Шаг 2 либо круг 4.
- **🆕 КРУГ 5 РОЗДАН (2026-06-28, тема оператора = тест-харднинг + edge-cases, 1-2ч/полоса):** ТЗ `coordination/_tz_round5_hardening.md` — по секции на полосу с КОНКРЕТНЫМИ edge-кейсами из их же докладов (НЕ generic «добавьте тестов»). Разослано 6 полосам через send_message (sales/procurement/finance/logistics/wms/reference; чаты остановлены — оператор открывает). **Модель: ВЕСЬ Sonnet под гейтом `lane_check.py <полоса>`+pytest; Opus только эскалация если тест вскрыл реальный деньго/секьюрити-баг с нетривиальным фиксом → NEEDS-ARB.** Миграций НЕ ожидается (NEEDS-MIG ко мне если что). DoD: новые тесты ДОЛЖНЫ падать на старом коде (доказать реальность кейса), коммит локально не push, найденные-непочиненные баги — списком в докладе. finance НЕ заблокирован Р5 (харднинг календаря/B2/reconcile отдельно от P&L). Жду доклады `КООРД: DONE <полоса> — круг5 …`. **⚙️ ИСПОЛНЕНИЕ (2026-06-28): десктоп-чаты не будятся программно (send_message не запускает stopped-сессию) → Продажи+Закупки идут в своих окнах (оператор открыл), а 4 простаивающие (reference/finance/wms/logistics) ВЕДУ Я фоновыми Sonnet-агентами** (agentId ae89e03c/ab04b92b/ac319630/a545b490). Файлы разведены: onec.py→reference, test_links.py→wms, finance тестит reconcile через фасад. Агенты НЕ коммитят — соберу гейты и закоммичу по полосам сам. **⚠️ 1-Й ЗАПУСК АГЕНТОВ УПАЛ НА AUTH (организация отключала доступ ~19:00, оператор пополнил) — перезапущены.** **ИТОГ КРУГА 5 (2026-06-28, закоммичено координатором/чатами):** ✅ wms `038f1fd` (QC-гейт/low-stock/RBAC/цикл-каунт регресс-локи, зелёный); ✅ reference `2c26bd0` (21 passed; RBAC-дыры НЕТ — гейты refs.view на месте; 4 «фейла» были UnicodeEncodeError кириллица-в-заголовке, не дыра); ✅ finance `8d274c3` (десктоп-чат, К5-1: **3 РЕАЛЬНЫХ бага в reconcile.py** — дубль ref/без-counterparty схлопывались, '100,00' РФ-локаль роняла reconcile; money→str вынесен в отд. NEEDS-ARB); ⏳ logistics — агент `add3ab1f` работает; sales/procurement — в своих чатах. **НАХОДКА (заведена задача task_7407b7b0):** `config/access.py` SUPER_ROLES кириллица "Админ" → нельзя передать X-User-Roles заголовком (UnicodeEncodeError), ломает dev-авторизацию админа → заменить на ASCII "admin".
- **🆕 КРУГ 4 (2026-06-28, «пакет + открыть HR/Синк») — ⚡ ФЛОТ ОБОГНАЛ ТЗ:** пока писал ТЗ, полосы САМИ сделали пакет из roadmap+карты: **✅ Р4 платёжный календарь** — finance `fc6dea3` (мигр.0075 bank_account + UI Календарь + тесты); **✅ B1 замкнуть ship_deadline** — procurement `76a293c` (мигр.0074, `module.py:22` subscribe→`on_ship_deadline_set`→`ShipRequirement`→план машины; ребро §2 теперь ЖИВОЕ). **Круг 4 B2/фасады — БОЛЬШЕЙ ЧАСТЬЮ DONE (17:43-17:46):** ✅ finance B2 (`7131bf1`: reference.*.changed→outbox recompute+дедуп+каскад-тест, 48 тестов) · ✅ reference 1С read-фасады (`f2d48c8`: fetch_payments реализован + bank_balance/balance_sheet, READ-ONLY); ✅ **procurement B2 done** (`module.py:25-26` подписка `on_reference_changed`) → **круг 4 B2/фасады ПОЛНОСТЬЮ закрыты обеими полосами**. Хотспот `onec.py` тронули обе (finance+reference) — сверено координатором: дублей нет, import OK. **Р5 P&L — STAGED** (`_tz_finance_r5.md` готов, ждёт открытия HR + B2-финиша + подтверждения **cash-vs-accrual** оператором). Инфра: seed.py isort починен координатором (`46d208d`, разблокировал общий гейт); wms-гейт-фейл `test_goods_received` сроутен Складу. **Онбординг/раздача:** **HR** — засев `coordination/seed-hr.md` ГОТОВ (сверен по коду), ждёт открытия чата оператором; задача `hr.payroll.accrued/paid`→Р5 (⚠ развести с `production.payroll`; salary ₽→BYN). **Синк — РЕШЕНО (оператор): НЕ открываем, 1С read-фасады отданы Справочникам** (они владеют `integrations/client.py` по `mdm-seam §2`) — ТЗ `_tz_reference_r4.md` (`fetch_bank_balance`/`fetch_balance_sheet` + реализовать отсутствующий `fetch_payments` stub; READ-ONLY, аддитивно к `core/services/onec.py`-Protocol; формат согласовать с finance). Эти фасады → Финансы Р6/Р7. Р5→Р7 — ТЗ ПОСЛЕ HR + фасадов. Вопрос **cash-vs-accrual P&L** (finance → NEEDS-ARB). ⛔ вне круга: S&OP (нет методики цены), прод-деплой (сервер офлайн).
- **✅ ПРОД-ДЫРА — КОД-ФИКС ЗАПУШЕН (2026-06-28, `d096b19` в мерже `5b746ef`):** `docker-compose.yml` больше НЕ хардкодит `dev` — security-критичные переменные через env-substitution (`${AIOS_ENVIRONMENT:-dev}` и т.д.). Локаль (env не задан) → дефолт dev как раньше; серверный `.env`/override теперь РЕАЛЬНО применяется → прод-гард `_no_dev_defaults_in_prod` fail-closed срабатывает. **ОСТАЁТСЯ серверная ops-часть (SSH у оператора, guard блокит у Claude):** на сервере создать untracked `.env` рядом с compose: `AIOS_ENVIRONMENT=prod`, `AIOS_AUTH_MODE=oidc`, `AIOS_KEYCLOAK_ISSUER=…`, `AIOS_KEYCLOAK_AUDIENCE=…`, реальные `AIOS_DATABASE_URL` (не aios:aios) → `git pull && docker compose up -d --build`. ⚠ committed `docker-compose.override.yml` ремапит порты 5433/8001 — на сервере не использовать (или переопределить). Чек-лист — `RELEASE.md` §2.
- **✅ Скилл `deploy-release` + `coordination/RELEASE.md` собраны** (Workflow + adversarial-verify: 22 замечания, 11 блокирующих вшиты). Деплой = serial single-owner координатора; SSH жмёт оператор (guard). Зарегистрирован в §Инфраструктура.
- **✅ ОБА БУРСТА ТЗ ЗАКРЫТЫ (2026-06-28):** все 6 полос закрыли и 1-2ч, и 2-4ч ТЗ. Финансы (проводки/факт-маржа/ДДС-lite), Склад (операц.ядро+приёмка QC/put-away/pick/pack/цикл-каунт/дашборд), Справочники (витрина+SCD2 UI+дерево категорий+групп-атрибуты+data-quality+AI-query), Продажи (Сделки2.0+мульти-воронки+pipeline-аналитика+встречный план РОП+won→office), Закупки (landed+PO/ETA+поставщики+RFQ/award+претензии+4 экрана), Логистика (тендер-флоу из UI+карточка рейса/трекинг+аудит фрахта+info-подписка procurement.received). ~320+ тестов (по докладам). ВСЁ локально, НЕ пушено. Многие полосы сами гоняли adversarial-ревью.
- **Финал миграций:** цепочка `0055→…→0075` ЛИНЕЙНА, head **0075**, next **0076** (0071 proc-r3 · 0072 proc-ship-plan · 0073 sales-ship-deadline · 0074 proc-ship_requirement · 0075 finance-bank_account/Р4 — сверено `next_migration.py --peek` + `alembic heads`=0075 единственный 2026-06-28). Аллокатор выдержал параллельные взятия без форка. Номер — ТОЛЬКО через аллокатор.
- **🖥️ Живой dev-стенд ПОДНЯТ (2026-06-28 ~05:30):** backend `:8000` (bg, с `AIOS_AUTH_MODE=dev`+`AIOS_ENVIRONMENT=dev` override) + frontend `:3003` (bg). **`dev.db` ПЕРЕСОЗДАНА** (67→84 табл) + пересеяна: иначе таблиц новых миграций (wms/sales) не было → 500. Сняты скрины всех 6 модулей — UI рендерится, honest-empty где нет данных.
- **✅ Продажи funnels/chats ПОЧИНЕНЫ (2026-06-28 08:40):** submodule `a949ed0` (try/except `OperationalError|ProgrammingError` → `[]` + rollback при старой dev.db), bump `4ad5fb0`; 21/21 PASS. `DealHandoffOut` объявлен (`e24e510`), app грузится. Правильное лечение пользователю — пересоздать dev.db (`rm dev.db; python scripts/seed.py`), graceful — страховка. Склад тем же reseed уже починен.
- **🆕 КРУГ 3 ТЗ РОЗДАН (2026-06-28, через Workflow `fleet-tz-round3` — 6 черновиков + сверка контрактов high-effort):** тема «Сквозная сборка под деньги» — реальная маржа end-to-end (procurement landed → sales прогноз → finance факт, числа сходятся), реактивный MRP-lite (`wms.stock.low → Закупки → черновик заявки`), подписка висящих событий. Файлы — `coordination/_tz_<полоса>_r3.md` (sales/procurement/finance/logistics/wms/reference). Контракт-фриз — ниже.
- **⚠️ `.env AIOS_AUTH_MODE=oidc` — корень фантомных api-фейлов флота** («чужой .env oidc», валил api-тесты у всех). Локально гонять с `AIOS_AUTH_MODE=dev`. Сам `.env` править НЕЛЬЗЯ (guard блокит секреты) — только override в команде.
- **Коммит-делегация:** оператор делегировал координатору отмашку на ЛОКАЛЬНЫЙ коммит DONE+DoD-зелёных; push в origin — ТОЛЬКО явная команда. Все коммитят локально.
- **✅ PUSH ВЫПОЛНЕН (2026-06-28) — реконсиляция divergence:** `origin/sales-2.0-redesign` обогнал локаль на **41 коммит** (параллельная cherry-pick линия: AuthN P1-1, методика landed, справочники M2-M5, маржа из 1С). Force запрещён → сделал **мерж-реконсиляцию в изолированном worktree**: 22 конфликта (домен справочников/маржа/сделки) разрешены union'ом (Workflow, ничего не выкинуто). Верификация ЗЕЛЁНАЯ: `import main` (351 роут), ruff clean, **119 pytest** (refs/landed/auth/sales), `tsc --noEmit` 0. Запушено: суперпроект `e0f9c6f..5b746ef → origin/sales-2.0-redesign` (FF, `AIOS_ALLOW_PUSH=1`); субмодули finance/logistics/wms → origin/main (FF), sales/procurement → origin ветка `reconcile/sales-2.0-20260628` (их main разошёлся). Worktree вычищен.
- **⚠️ ХВОСТЫ ПОСЛЕ ПУША (важно):**
  1. **✅ ЗАКРЫТО (2026-06-28):** локаль `sales-2.0-redesign` подтянута к origin `5b746ef` (FF, behind=0) — divergence-рецидив снят. Dirty разобраны (Sonnet): 5 STALE-блокеров + 2 untracked-коллизии (в origin) отпущены/удалены; UNIQUE-правки **ЗАКОММИЧЕНЫ координатором**: guard-инфра `87c5c6f`, frontend (playwright-auth+error/loaded доски) `154ab02` (tsc✓), litellm call_script/objection `09fae97` (ruff✓). Локаль +3 коммита от origin (FF-able, не пушено). Merged-дерево `import main` OK (351 роут).
  2. **🟡 sales: вынос лидов — Шаг 1 ЗАКРЫТ, Шаг 2 ждёт гринлайта.** **✅ Шаг 1 (404 снят, 15:37):** `leads_router` дуал-маунт `/leads`+`/sales/leads`, 39 лид-тестов PASS, sub `da80ba5`/super `28a7798`. Лиды в UI работают. **Шаг 2 (НЕ начат, ждёт оператора):** submodule-МЕРЖ `fdeb4b7⊕origin/main` сохранив круг 3 + подключить `CRM-LID1.1` (`modules/leads`) + перенумеровать миграцию `0044` (next через `next_migration.py`) + seed/тесты + снять алиас Шага 1. Существует репо `CRM-LID1.1.git` (был добавлен как `modules/leads` коммитом b18b72c, НЕ влит в эту ветку). Ребро `marketing.campaign.launched→sales` оборвётся при выносе, пока CRM-LID1.1 не подключён с подписками. **Пререквизит перед гринлайтом — проверить зрелость CRM-LID1.1** (`module.py` с подписками `marketing.campaign.launched`+`intake.lead.received`, `leads.py`, миграция, тесты). Зона Продаж; хотспоты через меня. ТЗ — `coordination/_tz_leads_adoption.md`. **НЕ срочно — Шаг 1 закрыл user-facing UX.**
  3. **✅ ЗАКРЫТО (2026-06-28):** procurement-прототипы на ZAK-3 origin/main — **устаревшие дубли** (Sonnet-сравнение): корень супера = строгий надмножество (8 файлов новее + 3 экрана `zak-claims/cost-calc/machine-editor` только в корне). Уникальной работы нет → **игнорировать**, не пуллить в работу; канон прототипов — корень супера. Опц. позже почистить `prototypes/` в ZAK-3.
  4. sales/procurement тип-коммиты — на ветке `reconcile/sales-2.0-20260628` их репо (не main); main этих субмодулей остаётся с параллельной линией.
- «service is busy» в чатах = транзиент API-перегрузки, переждать.
- **Окупаемость + плагин:** проверка 2026-07-01 (scheduled `plugin-packaging-payoff-check`); заполнять `METRICS.md` на ближайших задачах; решение об упаковке kit в плагин — по итогам.
- **Очередь полос:** Офис / HR / Маркетинг (через скилл `lane-onboard`, желательно сразу worktree).
- **Модель:** Sonnet 5 дефолт под гейтом; Opus 5 — деньги/безопасность/схема-миграции/арбитраж/судья;
  Haiku 4.5 — механика (канон — `coordination/MODEL-TIERING.md`).

## Контракт-фриз круга 3 (координатор зафиксировал ДО старта — единый источник)
> Reconcile-агент нашёл 5 несовпадений payload + 2 конфликта за хотспоты. Решения ниже вшиты в каждый `_tz_*_r3.md`. Полоса сверяется с этим разделом перед кодом.
1. **`wms.stock.low`** (НОВОЕ; эмитит **WMS**, подписывает **Закупки**) — канонический **ПЛОСКИЙ** payload, ОДНО событие на нарушенный порог: `{sku_code, sku_title, warehouse, free_qty, min_qty, deficit, reorder_qty, severity:'out_of_stock'|'below_min', source:'wms.threshold', entity_ref:'threshold:<id>'}`. Закупки: `PurchaseRequest.item := sku_title` (fallback sku_code). Ветку `{rows:[...]}` НЕ делать.
2. **`procurement.landed_cost.calculated` НЕ несёт `deal_id`** (PO обслуживает много сделок) → сверка маржи (sales S3-4, finance FIN-A1) на уровне **sku/агрегата**, НЕ по сделке; delta агрегатная. `deal_id` НЕ добавлять.
3. **`procurement.claim.resolved` = `amount_byn` (str, УЖЕ BYN) + `supplier_id`** (нет currency/counterparty_ref) → finance FIN-C1 **НЕ конвертирует** (double-convert = порча денег). P6 добавляет опц. `order_id`.
4. **`procurement` P4: `stage` 'estimated'→'actual'** в payload, что finance УЖЕ потребляет → приземлять ПОСЛЕ клиренса finance (грепнуть `on_landed_cost` на использование `stage`; по грауну читает qty+total).
5. **`logistics.freight.cost` импорт-плечо:** `leg:'import'`, `ref:'import:<id>'`, **БЕЗ `deal_id`** → finance `on_freight_cost` терпит отсутствие deal_id (проекция на уровне po/cost-center). `leg` аддитивно.
6. **🔗 БОНУС-связка:** procurement P7 эмитит **`procurement.po.drafted`** `{po_ref, supplier_id, planned_amount:str(BYN), currency:'BYN', eta_date|null, deal_id:null}` → finance FIN-B1 получает реальный апстрим прогноза кэша (был honest-empty).
7. **Кнопка `frontend/src/components/erp/wms-alerts.tsx` — ВЛАДЕЛЕЦ WMS** (R3-2: кнопка→`POST /wms/alerts/emit`→событие→Закупки подписаны). **Закупочный P3 СНЯТ** (двойная реализация в обход границы). Закупочный P1 (`/requests/from-deficit`) — только внутренний helper подписки P2.
8. **`coordination/DEPENDENCY-MAP.md` правит ТОЛЬКО координатор.** Закупки P9 и Справочники REF3-7 (и все) — НЕ редактируют файл, отдают текст рёбер строкой `КООРД`.
9. **Миграции:** Закупки — **ОДНА** ревизия (`purchase_request.origin` + `purchase_order.received_at`), номер через `scripts/next_migration.py` в момент работы (head=0070). Справочники SCD2 partial-unique индекс — **ОТЛОЖЕН** (общие таблицы, blast radius). Прочие — без миграций.
10. **`sales.demand.requirement` (S3-2/S3-7) — ОТЛОЖЕНО в круг 4** (нет потребителя; forward-demand требует нетто остатка+in-transit ETA = S&OP). Ось B круга 3 = реактивная петля wms→закупки.
11. **`core/services/__init__.py`** трогают reference (REF3-1 `sku_master`) и рядом finance (`onec.py`) — строго **аддитивно**, без переписи класса `Services`. REF3-1 фасад приземлять РАНО (апстрим).
12. **Любая правка `modules/sales`: `python -c "import main"` перед коммитом** (прошлый `DealHandoffOut` NameError ронял api-фикстуры чужих полос).

## Инфраструктура флота (инструменты координатора)

- **Снимок:** `python scripts/readiness.py --write` → `coordination/STATUS.md` (блок `COORD:AUTO`: git/ahead/dirty + реальная голова миграций + хвосты REPORTS/PUSH-LOG/.activity). Единый экран — не сканировать дерево/транскрипты.
- **Проценты готовности — ВЕДУТСЯ, не пере-замером:** канон в `coordination/readiness.json` (12 юнитов + overall). `readiness.py` читает его и рендерит колонку **%** + общий показатель в авто-блок STATUS.md при каждом прогоне (метрики loc/роуты обновляются сами, % — из json). **Цикл обновления:** лейн в `КООРД: DONE <полоса> — … [%: NN]` сообщает свой новый %, координатор правит ОДНУ строку `readiness.json` + поле `updated`. Полный пере-замер (workflow `readiness-assessment`, 12 агентов читают код) — РЕДКО, для калибровки. Не гонять агентов ради «сколько готово» — смотреть json/STATUS.
- **Доклады полос:** `coordination/REPORTS.md`. Stop-хук `claude_report_hook.py` ловит в конце хода полосы строго-форматный маркер `КООРД: <DONE|BLOCKED|NEEDS-MIG|NEEDS-ARB|INFO> <полоса> — <суть>` (работает и для десктоп-чатов). Координатор НЕ читает транскрипты — читает REPORTS.md + STATUS.md.
- **Awareness:** `claude_awareness_hook.py` — SessionStart инжектит STATUS-указатель + REPORTS + памятку о маркере; PreToolUse на push/commit — свежие пуши + хотспоты.
- **Тиринг моделей:** `coordination/MODEL-TIERING.md` (T1 Opus деньги/безопасность/схема, T2 Sonnet фича, T3 Haiku механика). Применять к своим сабагентам и рекомендовать полосам.
- **Изоляция полосы:** `python scripts/lane_worktree.py <lane>` → свой worktree `../_wt_<lane>` на ветке `sales-2.0-<lane>` от origin (HEAD не дрейфует, amend безопасен). Рекомендовать для НОВЫХ полос (Офис/HR/Маркетинг).
- **Номер миграции (атомарно, анти-dual-head):** `python scripts/next_migration.py <lane> "<описание>"` берёт номер под файл-локом + резервирует (`.migration-reservations.local`) → параллельные полосы не возьмут один номер. `--peek` — посмотреть head/next без резерва. Markdown-счётчик в ACTIVE-SESSIONS — для глаз (ведёт координатор), истина — лок+файлы.
- **Allowlist:** `.claude/settings.local.json` — безопасные read/test/lint авто-разрешены; commit/push — гейт оператора.
- **Гарды (БЛОКИРУЮЩИЕ, fail-open внутри python):** `coordination_hook.py` — pre-commit блокирует staged-миграцию при >1 alembic head (обход `AIOS_ALLOW_MULTI_HEADS=1`); pre-push блокирует прямой push в общую ветку с >1 коммита (обход `AIOS_ALLOW_PUSH=1`). Вторая линия к `next_migration.py` и правилу cherry-pick.
- **Eval-гейт:** `python scripts/lane_check.py <полоса>` — ruff→tsc→pytest по скоупу полосы, `[PASS]/[FAIL]` + GATE; `--strict` (exit 1 для CI), `--peek`, `--skip-tsc/--skip-pytest`. Advisory-команда перед мержем, не хук.
- **DoD-контракт:** `coordination/DoD.md` — единый «готово» (review/tests/lint/commit + route-добавки); awareness инжектит указатель; полоса само-сертифицируется чек-боксами в маркере `КООРД: DONE … [DoD: ✓…]`.
- **Скилл `lane-onboard`** (`.claude/skills/lane-onboard/`): повторяемый онбординг полосы (засев→сверка→правки→регистрация→карта→опц. worktree/миграция) + шаблон засева `references/seed-template.md`. Отдельно от `orkestrator-lead` (тот — автономные headless-воркеры).
- **Скилл `html-first`** (`.claude/skills/html-first/`): прототип UI до кода — HTML-мокап → Gate 1 (одобрение оператора) → Gate 2 (осуществимость+контракт данных) → реализация слайсами; + `references/honest-mockup.md` (real-vs-demo, decision-fidelity). Полоса может стартовать от одобренного мокапа.
- **Скилл `deploy-release`** (`.claude/skills/deploy-release/`): релиз/деплой как фаза высшего риска — serial single-owner акт координатора (НЕ отдельный standing-чат). Сборка→VERIFY-гейты→фиксация отката (истина С СЕРВЕРА)→хэндофф SSH оператору (guard блокит SSH у Claude)→пост-смоук (РЕАЛЬНЫЙ режим+OIDC-логин)→rollback. Исполняемый чек-лист — `coordination/RELEASE.md`. Собран через Workflow + adversarial-verify (22 замечания, 11 блокирующих вшиты). ⚠️ Вскрыл прод-дыру — см. «Открытые нити».
- Все три скилла + хуки + скрипты + шаблон COORDINATOR.md — **кандидаты в переносимый плагин** (проверка окупаемости 2026-07-01, см. METRICS.md).
- В директивы полосам ВКЛЮЧАТЬ требование строки `КООРД:` в конце хода (иначе доклад не попадёт в REPORTS.md).
