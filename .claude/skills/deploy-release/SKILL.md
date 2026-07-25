---
name: deploy-release
description: Релиз/деплой как отдельная фаза высшего риска (CRM/ERP, трогает main+прод). Сборка релиза → Verify-before-deploy (один head Alembic · lane_check · gitlinks ДОСТИЖИМЫ в origin субмодулей · обратимость миграций · прод-env через override на сервере · образ собирается) → хэндофф SSH-команды ОПЕРАТОРУ → пост-смоук (РЕАЛЬНЫЙ режим контейнера + OIDC-логин) → rollback. Deploy = serial single-owner акт координатора (конкурент за main = дрейф; отдельный standing-чат НЕ нужен). Используй когда оператор говорит «релизим», «выкатить на сервер», «deploy», «собрать релиз», «задеплоить». НЕ для локального коммита/PR без выката (это обычный git-канон) и НЕ для онбординга полосы (это lane-onboard).
---

# deploy-release — релиз как фаза, не как кнопка

⛔ Этот скилл НЕ переводить в `context: fork` / фоновый режим: поток построен на живом диалоге
с оператором (выдача SSH-команд и разбор его вывода).

Деплой — фаза №1 по риску: трогает общий `main` И прод (приоритеты 1)деньги 2)безопасность). Поэтому deploy **serial, single-owner** — выполняет ОДИН координатор, не параллелит. Отдельный постоянный «деплой-чат» НЕ заводим: лишний писатель в `main` = дрейф HEAD. Claude **только готовит релиз и формирует команды** — сам SSH НЕ выполняет: guard блокит `tailscale ssh`/prod-IP во ВСЕХ сессиях → все серверные команды (деплой, смоук, rollback) запускает ОПЕРАТОР вручную, а Claude интерпретирует присланный вывод.

**Когда применять:** выкат собранной линии на сервер `/opt/cmr-erp`; bump указателей субмодулей в прод; смена прод-env.
**Когда НЕ применять:** локальный коммит/PR без выката, правка одного файла — там это оверкилл (лестница лени), хватает обычного git-канона + `lane_check`.

## Поток (5 этапов, исполняемый чек-лист — `coordination/RELEASE.md`)
```
Сборка релиза → VERIFY-гейты → ЗАФИКСИРОВАТЬ ОТКАТ (истина С СЕРВЕРА) → хэндофф оператору (SSH) → пост-смоук → [rollback при провале]
```
Каждый пропущенный гейт = битый gitlink / multiple-heads / необратимая миграция / небезопасный-но-«зелёный» прод-режим. Один владелец = HEAD не дрейфует под тобой.

## 1. Сборка релиза (НИКАКОГО amend/reset/rebase на общей ветке)
- [ ] Cherry-pick СВОИХ коммитов на чистую ветку от `origin/main` (worktree `deploy-consolidation`), не утаскивая чужие.
- [ ] Каждый затронутый субмодуль: коммит в его origin (`CRM.git`/`ZAK-3`/…) → **push** → только потом bump указателя в супер-проекте. Иначе серверный `pull --recurse-submodules` достанет битый gitlink.
- [ ] После cherry-pick сверить gitlink в собранной ветке: `git ls-tree HEAD modules/<name>` == твой ЗАПУШЕННЫЙ SHA субмодуля (не подобранный из локального дерева чужой/локальный bump).
- [ ] Пушить именно собранную ветку: `git push origin deploy-consolidation:main` (НЕ `git checkout main && merge` — локальный `main` обгоняет origin чужими коммитами).

## 2. Verify-before-deploy (гейты — без зелёного не выкатываем)
- [ ] Alembic — ОДИН head на ФИНАЛЬНОЙ ветке (после cherry-pick + bump субмодулей): `python scripts/next_migration.py --peek` → ровно один head (≥2 = дробление → `upgrade` упадёт в проде). `--peek` смотрит ТОЛЬКО `migrations/versions` супер-проекта — повторный head проверяем уже на сервере (см. §5).
- [ ] **Обратимость миграций:** каждая новая миграция имеет рабочий `downgrade()` (НЕ `pass`/`raise`), прогнан `alembic upgrade head && downgrade -1 && upgrade head` на dev-БД. Необратимую (DROP с данными) пометить в §3 + план forward-fix.
- [ ] `python scripts/lane_check.py <lane> --strict` → `GATE: PASS` (ruff → tsc → import main → pytest).
- [ ] **Gitlinks ДОСТИЖИМЫ в origin** (НЕ `git submodule status` — он смотрит ТОЛЬКО локальные объекты и битый незапушенный gitlink пропустит): для каждого субмодуля `cd modules/<name> && git fetch origin -q && git branch -r --contains <gitlink_SHA> | grep origin`. Пусто = коммит не запушен → СТОП. Отдельным блоком — `procurement` (известный рассинхрон ZAK-3, см. §1).
- [ ] **Образ собирается с нуля:** `docker build -t aios-app-test .` проходит (новые pip-зависимости типа `PyJWT[crypto]` реально ставятся на python:3.12-slim, без отсутствующих build-deps). Наличие в `requirements.txt` НЕ гарантирует сборку.
- [ ] **Прод-режим контейнера задан на СЕРВЕРЕ** (НЕ в коммитнутом `docker-compose.yml` — он жёстко даёт `AIOS_ENVIRONMENT=dev` + `aios:aios@`). Источник прод-env — серверный `docker-compose.override.yml`/`.env`/`env_file` (untracked, `git pull` его НЕ принесёт — создать на сервере ОДИН раз). Проверить итоговые значения: `docker compose config | grep -E 'AIOS_ENVIRONMENT|AIOS_DATABASE_URL|AIOS_AUTH_MODE|AIOS_KEYCLOAK'` → `environment=prod`, реальные креды БД, `auth_mode=oidc`, issuer/audience. ⚠️ Гард `_no_dev_defaults_in_prod` срабатывает ТОЛЬКО при `environment=prod`; при `dev` он молча КОРОТИТ — app поднимется в небезопасном header-trust режиме (вход без пароля). Realm в Keycloak заведён, issuer-URL достижим из app-контейнера (JWKS отдаётся).
- [ ] DoD пройден (`coordination/DoD.md`): ЯВНО запустить `/code-review` (сам он с 2.1.215 не стартует; идёт фоновым сабагентом — дождаться вердикта) → `/simplify`, миграция через `next_migration.py` (НЕ руками), деньги — `Decimal`/BYN, роуты под `require_permission`.
- [ ] **(опц.) Глубокий whole-system аудит** — только крупный релиз (много полос / схема / деньги / межмодульные контракты): один адверсариальный проход по всей линии ищет баги на **швах модулей** (что per-lane `lane_check` не видит) + **перемудрение** (мёртвые абстракции против лестницы лени). Дефолт Opus 5 (`claude-opus-5`; 1M контекста — вся линия влезает в один проход, effort high/xhigh); Fable 5 ($10/$50) — только post-калибровка (Opus vs Fable, если не нашёл сверх — остаётся Opus). Мелкий релиз — пропустить (гейты выше покрывают). Деталь — `RELEASE.md §2`.

## 3. Зафиксировать откат (истина — С СЕРВЕРА, не из локального дрейфующего main)
- [ ] Снять точку отката С СЕРВЕРА ДО pull (команда оператора): `git rev-parse HEAD` + `git submodule status` + alembic head на сервере. Записать в `RELEASE.md`.
- [ ] Подтвердить, что прежние SHA субмодулей ДОСТИЖИМЫ в origin (`git ls-remote <submodule-origin> | grep <SHA>`) — иначе rollback не подтянет. На окно релиза — НИКАКИХ force-push в origin субмодулей.
- [ ] Обратимость миграций релиза: обратима / НЕОБРАТИМА (если да — план forward-fix).

## 4. Хэндофф оператору + пост-смоук
- Выдать оператору ТОЧНУЮ команду из `RELEASE.md`. Деплой детерминированно обновляет и субмодули: `git pull --recurse-submodules && git submodule update --init --recursive` (один `pull` НЕ гарантирует переключение рабочих деревьев — особенно для новых субмодулей). Миграции применяются на старте app (`alembic upgrade head`) — отдельно не гнать.
- ПЕРЕД pull оператор проверяет чистоту сервера (`git status --short`, субмодули без `+`/`-`, ветка = main) — грязное дерево клобберит/фейлит pull на середине.
- После выката собрать смоук и записать результат в `ACTIVE-SESSIONS.md` § «Деплой-состояние».

## 5. Пост-смоук (РЕАЛЬНЫЙ режим, не только /health)
- Узнать опубликованный порт (`docker compose ps app` — override может перемапить 8000→8001), затем `/health`, контейнеры Up, логи без `Multiple head revisions`/`FAILED`, alembic head на сервере = ожидаемому.
- **Доказать безопасность (приоритет #2):** `docker exec aios-app-1 printenv | grep -E 'AIOS_ENVIRONMENT|AIOS_AUTH_MODE'` → `prod`/`oidc`. РЕАЛЬНЫЙ OIDC-логин: токен у Keycloak → защищённый роут = 200; запрос с `X-User-Roles` БЕЗ валидного Bearer = 401/403. Это единственное доказательство, что header-trust выключен.
- Фронт деплоится/откатывается ОТДЕЛЬНЫМ процессом (этот runbook = бэкенд-стек). Если фронт в релизе не меняется — отметить явно; если меняется — см. отдельную процедуру фронта.

## 6. Rollback
- Откат супер-проекта оператором: `git fetch origin` → `git reset --hard <SHA из §3>` → `git submodule update --init --recursive --recurse-submodules` → `docker compose up -d --build`. `reset` допустим — прод-хост single-owner, не разделяемая dev-ветка; untracked override/.env уцелеют.
- ⚠️ Если `submodule update` падает (битый gitlink) — вручную `cd modules/<name> && git checkout <SHA из §3>`.
- ⚠️ **БД-миграции необратимы автоматически** — откат кода ≠ откат схемы. Деструктивную миграцию чинить forward-fix или проверенным `downgrade`; `reset` БД вслепую = потеря данных = нарушение приоритета №1.

## Канон-ссылки
- Исполняемый чек-лист: `coordination/RELEASE.md` (идти по пунктам `[ ]`).
- `coordination/DoD.md`, `ACTIVE-SESSIONS.md` (§Деплой-состояние, счётчик миграций), `COORDINATOR.md`, `DEPENDENCY-MAP.md`.
- Скрипты: `scripts/next_migration.py` (head/резерв), `scripts/lane_check.py` (eval-гейт).