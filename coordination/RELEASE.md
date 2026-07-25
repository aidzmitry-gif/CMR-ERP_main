---
Исполняемый чек-лист релиза/деплоя. Идти СТРОГО по порядку. Deploy = serial single-owner акт координатора.
Скилл-обёртка: .claude/skills/deploy-release/SKILL.md. Приоритеты: 1)деньги 2)безопасность 3)функциональность 4)эстетика.
SSH на сервер заблокирован во ВСЕХ Claude-сессиях (guard) → ВСЕ серверные команды (деплой §4, смоук §5, rollback §6) запускает ОПЕРАТОР вручную; Claude только формирует команды и интерпретирует присланный вывод.
---

# RELEASE — чек-лист выката на сервер (/opt/cmr-erp)

> Заполняй inline: дату, SHA, кто координатор. Не пропускай гейты — каждый ловит реальный класс аварии (битый/незапушенный gitlink, multiple-heads, необратимая миграция, небезопасный-но-«зелёный» прод-режим, не поднявшийся app).

## 0. Контекст релиза
- [ ] Дата: `__________` · координатор (single-owner): `__________`
- [ ] Что выкатываем (линия/полосы): `__________`
- [ ] Сверился с `coordination/ACTIVE-SESSIONS.md` (§Деплой-состояние — кто последний деплоил, текущий `origin/main` SHA).
- [ ] Фронт в этом релизе: НЕ меняется ☐ / меняется ☐ (если меняется — фронт деплоится/откатывается ОТДЕЛЬНЫМ процессом, см. процедуру фронта :3100/Caddy; этот runbook покрывает бэкенд-стек app/postgres/redis/keycloak).

## 1. СБОРКА релиза (на чистой ветке от origin/main)
> 🔴 НИКАКОГО `git commit --amend` / `reset` / `rebase` на общей ветке (`main`, `sales-2.0-redesign`, `theme/dark-mode-cd`). Только НОВЫЙ коммит / cherry-pick.
- [ ] `git fetch origin` → создал чистый worktree от `origin/main`: `git worktree add ../_deploy_wt -b deploy-consolidation origin/main`
- [ ] Cherry-pick ТОЛЬКО своих коммитов (не утаскивая чужие незапушенные из локального `main`).
- [ ] Для КАЖДОГО затронутого субмодуля (`sales`→CRM.git, `procurement`→ZAK-3, `production`→PRO-4, `wms`→SKL-5, `logistics`→LOG-6, `finance`→fin-7, `marketing`→MAR-8, `service`→SER-POD-9, `hr`→HR-10):
  - [ ] коммит в репозитории субмодуля;
  - [ ] **`git push` коммита субмодуля в его origin** (без этого серверный `pull --recurse-submodules` достанет битый gitlink → деплой сломается);
  - [ ] только ПОСЛЕ push — bump указателя (`git add modules/<name>`) в супер-проекте;
  - [ ] **сверить собранный gitlink:** `git ls-tree HEAD modules/<name>` → SHA == твой только что запушенный коммит субмодуля (НЕ случайный/чужой bump, подобранный из локального дерева). Если cherry-pick подтянул чужой gitlink того же субмодуля — отбросить и пересобрать.
- [ ] В `main` влита ТОЛЬКО нужная линия релиза (`git add` по именам, НЕ `add .`).
- [ ] ⚠️ Известный хвост: `procurement` gitlink (`deploy-pin`) расходится с ZAK-3 `main` — реконсилировать с владельцем ДО bump (см. блокирующий гейт в §2), иначе выкатишь рассинхрон.

## 2. VERIFY-before-deploy (без зелёного — СТОП)
- [ ] **Один head Alembic (на ФИНАЛЬНОЙ ветке):** перегнать `python scripts/next_migration.py --peek` ПОСЛЕ cherry-pick и bump субмодулей → строка `alembic head(ы): …` содержит РОВНО ОДИН head (актуальный номер — из `--peek` в момент релиза, не хардкодить). ⚠️ `--peek` сканирует ТОЛЬКО `migrations/versions` супер-проекта; миграция в субмодуле/чужом коммите может дать dual-head на сервере после `--recurse-submodules` — обязательная повторная проверка на сервере в §5.
- [ ] **Обратимость миграций:** каждая новая миграция релиза имеет рабочий `downgrade()` (НЕ `pass`, НЕ `raise`), проверенный локально: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` на dev-БД проходит. Если миграция деструктивна и downgrade невозможен (DROP COLUMN с данными) — пометить в §3 как НЕОБРАТИМУЮ и согласовать forward-fix план с оператором ДО деплоя.
- [ ] **lane_check зелёный:** `python scripts/lane_check.py <lane> --strict` → `GATE: PASS` (ruff → tsc --noEmit → import main → pytest по скоупу).
- [ ] **Все gitlinks ДОСТИЖИМЫ в origin** (НЕ через `git submodule status` — он смотрит ТОЛЬКО локальные объекты `.git`, незапушенный gitlink пропускает; именно тогда серверный `pull --recurse-submodules` падает `fatal: reference is not a tree`):
  ```
  git submodule foreach 'git fetch origin -q && sha=$(git rev-parse HEAD); git branch -r --contains $sha 2>/dev/null | grep -q origin || echo "UNPUSHED: $name $sha"'
  ```
  → НЕТ строк `UNPUSHED`. Любая такая строка = битый gitlink → СТОП, запушить субмодуль.
- [ ] **procurement (отдельный блокирующий гейт):** `cd modules/procurement && git fetch origin && git branch -r --contains <gitlink_SHA> | grep origin` → непусто. Если gitlink супер-проекта расходится с ZAK-3/`main` — СТОП, реконсилировать с владельцем (см. §1). Без зелёного деплой ЗАПРЕЩЁН.
- [ ] **Образ собирается с нуля:** `docker build -t aios-app-test .` проходит (а не только наличие пакета в `requirements.txt`). Гарантия, что новые pip-зависимости (напр. `PyJWT[crypto]` → cryptography) ставятся на python:3.12-slim без отсутствующих системных build-deps. Провал ловим ДО хэндоффа, не на проде.
- [ ] **Прод-режим контейнера — РЕАЛЬНЫЙ, проверен на СЕРВЕРЕ** (коммитнутый `docker-compose.yml` жёстко задаёт `AIOS_ENVIRONMENT: dev` + `AIOS_DATABASE_URL: …aios:aios@…` — гард `_no_dev_defaults_in_prod` при `dev` КОРОТИТ и OIDC-проверка НЕ срабатывает → app поднимется в небезопасном header-trust режиме = вход суперпользователем без пароля на публичном belakb.by):
  - [ ] **Источник прод-env на сервере определён и присутствует** (untracked, `git pull` его НЕ принесёт — создать на сервере ОДИН раз): `/opt/cmr-erp/docker-compose.override.yml` ЛИБО `env_file` в compose ЛИБО `.env` рядом.
  - [ ] Проверить ИТОГОВЫЕ значения дословно: `tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && docker compose config | grep -E 'AIOS_ENVIRONMENT|AIOS_DATABASE_URL|AIOS_AUTH_MODE|AIOS_KEYCLOAK'"` →
    - [ ] `AIOS_ENVIRONMENT=prod` (НЕ dev — иначе гард молча выключен)
    - [ ] `AIOS_DATABASE_URL` БЕЗ `aios:aios@` (реальные креды)
    - [ ] `AIOS_AUTH_MODE=oidc`
    - [ ] `AIOS_KEYCLOAK_ISSUER=__________`
    - [ ] `AIOS_KEYCLOAK_AUDIENCE=__________`
  - [ ] realm в Keycloak заведён; issuer-URL достижим из app-контейнера (JWKS отдаётся); Keycloak в проде НЕ на `start-dev` без persistence.
  - [ ] На сервере НЕТ неожиданного override, перемапливающего порты в неконтролируемое состояние: `docker compose config | grep ports` (учесть: локальный override мапит app→8001, pg→5433).
- [ ] **DoD** (`coordination/DoD.md`): `/code-review` → `/simplify`; миграция пронумерована через `next_migration.py` (НЕ руками); деньги — `Decimal(str(...))`/BYN; новые роуты под `Depends(require_permission(...))`; затронут auth/RBAC/деньги → обновлён `SECURITY.md`.
- [ ] **(опц.) Глубокий whole-system аудит** — ТОЛЬКО для крупного релиза (несколько полос / схема-миграция / деньги / межмодульные контракты событий). Один адверсариальный проход по собранной линии + контрактам событий + диффу релиза, ищет разом: (1) баги на **швах модулей**, которые per-lane `lane_check` по скоупу НЕ видит (инвариант shared-kernel, потерянный/переименованный контракт события, IDOR на стыке); (2) **перемудрение** — мёртвые абстракции, спекулятивные конфиги/фабрики против «лестницы лени». Модель: **Opus 5** (`claude-opus-5`) по умолчанию; **Fable 5** — только на самых крупных релизах и только ПОСЛЕ разовой калибровки (тот же аудит на Opus и Fable, сверка находок; Fable не нашёл сверх Opus → остаётся Opus, Fable — резерв). `/fast` на этом прогоне НЕ включать — $10/$50, это цена Fable. Мелкий релиз (1 полоса, без схемы/денег) — **ПРОПУСТИТЬ** (лестница лени: гейты выше уже покрывают).

## 3. ЗАФИКСИРОВАТЬ ОТКАТ (истина — С СЕРВЕРА, до деплоя!)
> Снимать точку отката С СЕРВЕРА, а НЕ из локального дерева координатора — локальный `main` дрейфует на чужие коммиты. Команда оператора (SSH под guard).
- [ ] С сервера ДО pull: `tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && git rev-parse HEAD && git submodule status && docker exec aios-app-1 alembic current"` → записать ниже.
- [ ] Прежний серверный HEAD (супер-проект): `__________`
- [ ] SHA субмодулей ДО деплоя (из `git submodule status` на сервере): sales `____` · procurement `____` · production `____` · wms `____` · logistics `____` · finance `____` · marketing `____` · service `____` · hr `____`
- [ ] **Прежние SHA субмодулей ПОДТВЕРЖДЕНЫ существующими в origin** каждого субмодуля (`git ls-remote <submodule-origin> | grep <SHA>`) — иначе rollback не сможет их подтянуть.
- [ ] Прежний alembic head на сервере: `__________`
- [ ] Обратимость миграций релиза: обратима ☐ / НЕОБРАТИМА ☐ (если НЕОБРАТИМА — план forward-fix: `__________`).
- [ ] На окно релиза — НИКАКИХ force-push в origin субмодулей (иначе откат супер-проекта на прежний gitlink не воспроизводится).
- [ ] `git push origin deploy-consolidation:main` релизной линии (ТОЛЬКО по явной просьбе оператора; НЕ `checkout main && merge` — локальный main обгоняет origin).

## 4. ХЭНДОФФ оператору (SSH — выполняет ОПЕРАТОР вручную)
> Claude НЕ выполняет SSH (guard). Выдать оператору команды дословно.
- [ ] **Pre-pull: чистота сервера** (грязное дерево клобберит/фейлит pull на середине → частично обновлённый прод опаснее не обновлённого):
  ```
  tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && git status --short && git submodule status"
  ```
  → дерево ЧИСТОЕ, субмодули без `+`/`-`, ветка = `main`. Грязно — СТОП, разобраться, не делать pull вслепую.
- [ ] **Деплой** (детерминированное обновление субмодулей — один `pull` НЕ гарантирует переключение рабочих деревьев, особенно для новых субмодулей):
  ```
  tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && git fetch origin && git pull --recurse-submodules && git submodule update --init --recursive && docker compose up -d --build"
  ```
- [ ] Напомнить: миграции применяются НА СТАРТЕ app сами (`alembic upgrade head`, `set -e` в `docker/app-entrypoint.sh`) — отдельно не гнать.
- [ ] Напомнить: если прод-режим без OIDC-env (§2) и при этом `environment=prod` — app не поднимется (by design); если `environment=dev` — поднимется НЕБЕЗОПАСНО (гард выключен). Проверка режима — §5.

## 5. ПОСТ-СМОУК (после выката — все команды выполняет ОПЕРАТОР, Claude интерпретирует вывод)
- [ ] Опубликованный порт app: `tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && docker compose ps app"` (override может перемапить 8000→8001 — все curl ниже на `<порт_из_ps>`).
- [ ] Контейнеры Up: `docker compose ps` → `aios-app-1`, `aios-postgres-1`, `aios-redis-1`, `aios-keycloak-1` все `Up`.
- [ ] `/health`: `tailscale ssh root@100.70.224.109 "curl -fsS http://localhost:<порт_из_ps>/health"` → 200.
- [ ] Логи без фатала: `tailscale ssh root@100.70.224.109 "docker logs --tail 100 aios-app-1"` — нет traceback, нет `Multiple head revisions`, нет `alembic … FAILED`.
- [ ] **Один head НА СЕРВЕРЕ:** `tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && docker compose exec -T app alembic heads"` → ровно одна строка. ≥2 = dual-head проскочил локальный peek (субмодуль/конкурентная миграция) → НЕМЕДЛЕННЫЙ rollback по §6.
- [ ] Alembic head на сервере = ожидаемому (`__________`).
- [ ] **РЕАЛЬНЫЙ режим контейнера (приоритет #2, безопасность):** `tailscale ssh root@100.70.224.109 "docker exec aios-app-1 printenv | grep -E 'AIOS_ENVIRONMENT|AIOS_AUTH_MODE'"` → `AIOS_ENVIRONMENT=prod`, `AIOS_AUTH_MODE=oidc`. Если `dev`/не-`oidc` — гард выключен, app доверяет `X-User-Roles` = вход без пароля → деплой НЕБЕЗОПАСЕН, rollback.
- [ ] **РЕАЛЬНЫЙ OIDC-логин end-to-end:** получить токен у Keycloak realm → дёрнуть защищённый роут под `require_permission` = 200; тот же роут с заголовком `X-User-Roles` БЕЗ валидного `Bearer` = 401/403. Единственное доказательство, что header-trust выключен в рантайме.
- [ ] Фронт открывается (роут `/login` → дашборд). Если фронт менялся в релизе — проверять его отдельной процедурой; рассинхрон API (старый бэк + новый фронт или наоборот) = красный.
- [ ] **Координатору прислать:** новый `origin/main` SHA · SHA всех субмодулей (с сервера) · alembic head на сервере · вывод `docker compose ps` · `printenv` режим · итог `/health` и OIDC-логина.

## 6. ROLLBACK (если смоук красный — все команды выполняет ОПЕРАТОР)
- [ ] Откатить указатель супер-проекта (оператор на прод-хосте; `reset` допустим — single-owner прод-хост, не разделяемая dev-ветка; untracked override/.env уцелеют):
  ```
  cd /opt/cmr-erp && git fetch origin && git cat-file -e <SHA из §3> && git reset --hard <SHA из §3> && git submodule update --init --recursive --recurse-submodules && docker compose up -d --build
  ```
- [ ] Сверить фактические SHA субмодулей с зафиксированными в §3. Если `git submodule update` падает (битый gitlink — ровно класс аварии из §1) — вручную для каждого: `cd modules/<name> && git checkout <SHA из §3>`. Если SHA нет в origin субмодуля — восстановить нечем (см. подтверждение в §3).
- [ ] ⚠️ `reset --hard` сотрёт незакоммиченные серверные правки (кроме untracked) — при сомнении снять `git stash`/копию ДО reset.
- [ ] ⚠️ **БД-миграции необратимы:** откат кода НЕ откатывает уже применённую схему (`alembic upgrade head` отыграл на старте, `set -e`). Если релиз добавил/изменил таблицы — forward-fix миграцией ЛИБО ручной `alembic downgrade <rev>` (только если downgrade написан и проверен — см. §2/§3). Не делать `reset`/drop БД вслепую — потеря данных = нарушение приоритета №1.
- [ ] После отката — повторный смоук (§5) + запись инцидента координатору.

## 7. Запись результата
- [ ] Обновить `coordination/ACTIVE-SESSIONS.md` § «Деплой-состояние»: дата, новый `origin/main` SHA (ЗАДЕПЛОЕНО), SHA субмодулей, alembic head на сервере, подтверждённый режим (`environment=prod`/`auth_mode=oidc`), статус контейнеров, открытые хвосты (follow-up).