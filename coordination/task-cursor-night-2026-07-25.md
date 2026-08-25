# Задание Cursor — ночь 2026-07-25

> **Заменяет фактическую часть `task-cursor-leads-sales-working.md`.** Там протухло: «голова
> миграций 0105» (верно, но см. §0.3 — брать номер всё равно нельзя), «planning.py у координатора,
> 15 тестов» (верно, отдаю — см. §7), статус L1–L6/S1–S6 (устарел: половина уже сделана тобой же).
> Цели, швы и дисциплина выката из старого ТЗ остаются в силе.
>
> Приоритеты платформы: 1) деньги собственнику → 2) безопасность → 3) функциональность → 4) эстетика.

## §0. Точка истины (сверено с origin, а не с чьим-то рабочим деревом)

| Что | Значение |
|---|---|
| Суперпроект `origin/main` | `13672d1` |
| gitlink `modules/sales` (CRM.git) | **`2dddd8b`** |
| gitlink `modules/leads` (CRM-LID1.1.git) | **`165a5fc`** |
| Голова Alembic в `origin/main` | **`0105`** (`0105_office_doc_deal_id`) |
| Экран `/crm/leads/planning` | не существует (есть только спека + мокап) |

**0.1. Работай от `origin/main`, не от локальных чекаутов.** Перед стартом:
`git fetch --recurse-submodules` → `git submodule update --init --recursive` → убедись, что
`modules/sales` стоит на `2dddd8b`, `modules/leads` на `165a5fc`.

**0.2. Гард против отката.** У координатора в дереве субмодули стояли на `f612f3a` (sales) и
`8b22eda` (leads) — оба **предки** актуальных gitlink-ов. Коммит поверх них + bump = откат
переноса КП при конвертации, идемпотентности денежного пути, FIFO-оплаты, счёта с НДС и
XSS-фикса договора. Перед каждым пушем субмодуля:
`git -C modules/sales merge-base --is-ancestor 2dddd8b HEAD` (и то же с `165a5fc` для leads) →
должно быть true.

**0.3. 🔴 МИГРАЦИЙ ЭТОЙ НОЧЬЮ НЕ БЕРЁМ.** В рабочем дереве координатора лежит **untracked**
`migrations/versions/0106_finance_bank_transaction.py` (`revision=0106`, `down=0105`) — полоса
финансов, файла нет **ни в одной ветке**. Поэтому:
- `down_revision="0106"` → на проде `alembic` упадёт «Can't locate revision 0106» при старте app;
- `down_revision="0105"` → как только финансы запушат свой 0106, получим две головы и падение выката.

**`scripts/next_migration.py` сейчас врёт** (`_head()` при непустом файле резервов возвращает max
резерва `0090` вместо реального head) — номер по нему не бери. Координатор чинит скрипт и требует
у полосы финансов запушить или удалить 0106. Номер миграции получишь **парой явным текстом**
(`revision` + `down_revision`) и только после того, как 0106 окажется в `origin/main`.

## §1. Готовое — НЕ переоткрывать

**Лиды:** L1 приём (`/integrations/web/lead`, `/email/inbound` → `intake.lead.received`),
L2 скоринг+SLA рабочими часами, L3 разбор+маршрутизация (`express-bulk`), **L4 конвертация**
(`165a5fc` — `convert` возвращает `deal_id`, позиции КП переносятся), L6 RBAC.

**Продажи:** S1 доска, S2 движение/`POST /win`, S3 документы (счёт+договор+факсимиле+пакет),
S5 `/crm/deals/planning`, S6 оплата→офис (шов `office_doc.deal_id`, мигр. 0105).

**Отдельно не трогать (свежие деньги/безопасность в `origin/main`):**
- `0354c65` — сумма счёта **с НДС** (грандтотал), чтобы дебиторка = что платит клиент;
- `3183e08` — экранирование значений в шаблоне договора (stored-XSS на денежном пути);
- `0a1ec50` — идемпотентность денежного пути, FIFO-оплата, счёт с ценами;
- роль `sales_manager` — есть в `modules/sales/permissions.py:29`, `modules/leads/permissions.py:28`
  и в `config/access.py:34` (`ACCESS_MATRIX`). Связка рабочая целиком, не «чинить»;
- реквизиты продавца (`AIOS_SELLER_*`, БИК `ALFABY2X`) — оператор подтвердил, не откатывать;
- **наполнитель `price_cost` уже влит**: `modules/integrations/module.py:35` — `if cfg.onec_base_url:`
  → `StockPriceCostSource()`. Заново не писать, слот `core/services/__init__.py` тоже уже есть.

## §2. Зоны

**Твоё:** `modules/sales/**`, `modules/leads/**`, `frontend/src/app/crm/{leads,deals}/**`,
`frontend/src/components/{leads,kanban}/**`, `frontend/src/lib/lead-*`, `tests/**` по leads/sales,
`migrations/versions/**` — только с номером, выданным координатором.

**`frontend/src/lib/api.ts` — на эту ночь целиком твой**, координатор в него не пишет. Разрешено
**только добавление** новых экспортов; правка/удаление существующих — нет.

**Не твоё:**
- `coordination/**` (пишет координатор; строку в `§Деплой-состояние` **присылаешь**, не пишешь сам);
- `config/access.py`, `config/settings.py`, `config/modules.py`, `core/services/__init__.py` — хотспоты;
- `modules/integrations/{module,routes}.py` + untracked `alfa.py` — у полосы банка висит незапушенная
  правка того же `register()` (`AlfaBankClient`);
- незавершённый OIDC-набор во фронте: `frontend/src/app/api/[...path]/route.ts` +
  untracked `frontend/src/lib/api-proxy-headers.ts` + `TOKEN_COOKIE` в `frontend/src/lib/access.ts` —
  коммитится только целиком, владелец не определён.

## §3. Задачи

### P1 — Прод-смоук денежного пути под OIDC 🔴 только у тебя есть SSH
Внутри контейнера, не снаружи:
```
docker exec <app> printenv | grep -E 'AIOS_ENVIRONMENT|AIOS_AUTH_MODE|AIOS_DEMO_PRICE_COST|AIOS_ONEC'
```
**Приёмка:** `AIOS_AUTH_MODE=oidc`; `AIOS_DEMO_PRICE_COST` **отсутствует** (иначе на проде живут
демо-деньги: `_register_dev_fixtures` включается при `environment=dev`); `alembic heads` — ровно одна
строка; негативный тест «`X-User-Roles` без валидного Bearer → 401/403»; живой OIDC-логин ролью
`sales_manager` → `GET /sales/deals` и `GET /leads` = **200**.
Результат — строкой координатору (SHA, режим, head), он внесёт в реестр.

### P2 — S4: маржа на живой 1С
Фасад поднимается только при `onec_base_url`. Проверить на реальных данных: провенанс «из 1С»
в карточке сделки; при пустом источнике `cost` = **`None`, не `0`**.

🔴 **Тип денег.** `ItemPriceCost.cost_byn/price_byn` аннотированы `float | None`, а
`_deal_margin` (`modules/sales/routes.py:1306,1323,1333,1335`) считает `float(r.qty)`,
`unit_cost * qty`, `price * qty` и мешает с landed через `float(...)`. OData отдаёт суммы
строкой/Decimal → `Decimal * float` = TypeError и **500 на `GET /deals/{id}/margin`**.
**Приёмка:** конвертация и округление до 2 знаков — на границе адаптера; тест, где мок OData
возвращает `Decimal("123.45")` и `"123.45"`, а `GET /deals/{id}/margin` отдаёт 200 с верной маржой.

### P3 — L5 «План лидоруба», ТОЛЬКО stateless-слайс
Единственный незакрытый пункт DoD. Ночью делаем калькулятор, **без персистентности**:
- `POST /leads/planning/reverse` → `reverse_funnel` (из отданного `planning.py`);
- `POST /leads/planning/capacity` → `capacity_check`;
- экран `/crm/leads/planning` — **read-only**, разметку портируй дословно из
  `leads-planning-preview.html` (он в `origin/main`), блоки: якорь цели из `plan_item`,
  живой калькулятор реверса, ёмкость vs потребность.

**Чего НЕ делаем ночью:** миграции, таблиц `lead_plan_*`, статус-машины draft→submitted→approved,
таба «Согласование», кнопок «Отправить РОПу»/«Утвердить». Это ≥1 отдельная смена и человеческий
гейт (РОП ночью недоступен).

**Права:** оба роута под `leads.lead.read`. Честно: осмысленной пары 403/200 среди sales-ролей нет —
`leads.lead.read` есть у всех четырёх. Роль вне модуля режет `AccessControlMiddleware` до
`require_permission`, такой тест проверяет middleware, а не роут — так и запиши в отчёте, слагов
не изобретай. (Пара появится, когда добавим подачу плана: `leads.lead.route` есть у всех, кроме
`sales_cli` — `modules/leads/permissions.py:29`.)

**Расхождения макета со спекой не додумывай** — списком в отчёт для РОПа утром.
Перед сдачей — `/ui-crawl` экрана (директива оператора 2026-07-04, обязательна).

### P4 — Мёртвый `leads_router` (полностью автономный пункт, зависимостей нет)
В `modules/sales/routes.py` объявлен `leads_router = APIRouter(tags=["leads"])` с **0 роутов**, и
`modules/sales/module.py:47-48` монтирует его дважды — на `/leads` и `/sales/leads`. `sales`
регистрируется раньше `leads` в `ENABLED_MODULES` → как только в него что-то допишут, он затенит
реальный модуль лидов. Удалить объявление и оба `include_router`.

**Приёмка:** 22 из 23 роутов лидов по-прежнему отдают 403 роли без `leads.lead.*` (открыт только
`GET /leads/ping`); `SLUG_TO_PACKAGE`/`ACCESS_MATRIX` **не трогать** — пакета `leads` там нет
намеренно, добавление слага `leads` выбросит 403 всем sales-ролям на весь модуль.

## §4. Гейты перед пушем

`pytest` зелёный · `ruff` · **один** `alembic heads` · фронт `tsc` + `vitest`.

**Пороги снимай на чистом чекауте `origin/main`, а не на грязном дереве.** В дереве координатора
тройка `deal-drawer-preview`/`deals-workspace`/`leads-workspace` даёт 145 кейсов, в `origin/main` —
**172**; локальные версии этих трёх файлов = откат, они выброшены и тебе не передаются.

**Порядок пуша — submodule-first:** коммит в CRM.git / CRM-LID1.1.git → **потом** bump gitlink в
суперпроекте. Наоборот — недостижимый gitlink и падение `git submodule update --init --recursive`
на сервере в момент выката.

## §5. Порядок реза, если не хватает времени

Режем сверху вниз: (1) миграция и любая персистентность L5 — она нелегальна, пока 0106 вне git;
(2) таб «Согласование» и статус-машина плана лидов; (3) P2 сверх проверки типа денег.

**Неснижаемый минимум ночи (полностью автономен):** P4 + P1 + stateless-слайс P3 с `/ui-crawl` и
четырьмя гейтами.

## §6. Заблокировано до ответа оператора — не упирайся, пиши строку и бери следующее

1. **0106 финансов** — запушить в `origin/main` или удалить. До этого миграций не берём (§0.3).
2. **Кто владелец выката.** Три версии в документах: `COORDINATOR.md` — акт координатора;
   `ACTIVE-SESSIONS.md` — серверные команды только вручную оператором; твоё старое ТЗ — дисциплина
   выката на тебе. Фактический SSH теперь только у тебя.
3. **Маршрут пуша.** Старое ТЗ требует прямой push в `origin/main`; `CLAUDE.md` и `COORDINATOR.md` —
   cherry-pick **только своего** коммита на чистую ветку от `origin/main`; pre-push guard прямой push
   заблокирует. **`AIOS_ALLOW_PUSH=1` в обход не жать** — затащишь чужие коммиты в main.
4. **Прод идёт с `AIOS_ENVIRONMENT=dev`.** Валидатор `_no_dev_defaults_in_prod`
   (`config/settings.py:115`) первой строкой делает `return self` при `environment=dev` — все
   прод-гарды молча выключены. Вопрос оператору: когда переводим на `prod`.

Все четыре вопроса отправь оператору **первым действием ночи**, а не когда упрёшься.

## §7. Активы от координатора — не переписывать

**Пакет лежит в `coordination/handoff-2026-07-25/`** — забирай оттуда, коммитишь ты.

- **`planning.py`** (138 строк) → кладётся в `modules/leads/planning.py`: `reverse_funnel` +
  `capacity_check`, чистая арифметика на `Decimal`/`float` с валидацией ставок (битый коэффициент —
  `ValueError`, а не `inf`).
- **`test_leads_planning.py`** → кладётся в `tests/unit/`. Прогнано перед передачей:
  **15 passed, ruff чист**.
- Оба файла untracked у координатора, в `origin/main` их **нет**. «Пересборка поверх `165a5fc`»
  не требуется — проверено: `planning.py` импортирует только stdlib (`math`, `dataclasses`,
  `decimal`), тест — только `modules.leads.planning`. Пересечений с изменившимся кодом лидов нет.
- **Спека и мокап:** `leads-planning-plan.md`, `leads-planning-preview.html` — уже в `origin/main`.

**Снято с передачи (проверено — уже в `origin/main`, не дублировать):**
- идемпотентность `0087_leads_init` (`if inspector.has_table("lead", schema="leads"): return`) —
  лежит в `origin/main:migrations/versions/0087_leads_init.py:21-24`; незакоммиченная копия в
  дереве координатора выброшена как дубль;
- три фронт-теста (`deal-drawer-preview` 69, `deals-workspace` 56, `leads-workspace` 47 = **172**
  кейса в `origin/main` против 145 локально) — локальные версии выброшены как откат.

## §8. Формат отчёта

Строкой оператору/координатору: что сделано · SHA коммитов (субмодуль + суперпроект) · гейты
(4 числа) · `alembic heads` · `✓ui-crawl` · открытые вопросы · что срезано и почему.
Прод-состояние (SHA/режим/head) — **присылаешь**, в `ACTIVE-SESSIONS.md` пишет координатор.
