# Оркестратор: 8-часовой план (2026-07-16/17)

> Цель: закрыть хвосты после деплоя `0c585d1` — **без** ломания UI (app остаётся `dev`/`dev` до готовности фронта).  
> Модели: **composer-2.5-fast** / **cursor-grok-4.5-high-fast** (параллельные полосы).  
> Сервер: `root@100.70.224.109` `/opt/cmr-erp`. Код: `origin/main@0c585d1`.

## Исходное состояние (проверено)
- App Up, alembic `0105`, health/sales 200, режим **dev**.
- Keycloak: realm `aios`, client `aios-backend` + Audience mapper, role `director`.
- cloudflared = **ephemeral** quick tunnel → issuer нестабилен.
- 1С live: код на ветке `sales-1c-live` / локально; **не** на проде.
- OIDC-флип app **запрещён** до Bearer во фронте.

## Полосы (параллельно где можно)

| # | Полоса | Часы | DoD | Модель |
|---|--------|------|-----|--------|
| A | **Keycloak: стабильный URL** (Caddy → :8080 или named tunnel) + `KC_HOSTNAME` в untracked override | 0–2 | issuer HTTPS стабилен; openid-configuration 200 с хоста и из app-сети | fast |
| B | **Фронт: задел OIDC** — inventory login/`api/[...path]`/headers; минимальный проброс Bearer если уже есть заготовка; иначе ADR + скелет | 0–4 | документ «что менять» + PR/патч без включения oidc на бэке | fast |
| C | **1С live на сервере** — `AIOS_ONEC_*` в `.env` (без prod), сверка OData, `load-onec`/sync цен в Postgres | 1–5 | подбор SKU из 1С на проде; `source=onec` при base_url; тесты mock зелёные | fast |
| D | **Secure-env без флипа** — сильный DB pass + override `KC_DB_PASSWORD` **только если** синхронно с ALTER; иначе отложить; чеклист готовности к флипу | 4–6 | runbook заполнен плейсхолдерами; **не** ставить `AIOS_ENVIRONMENT=prod` | fast |
| E | **Смоук + реестр** — health/board/leads; ACTIVE-SESSIONS; secure-env-prep status | 6–8 | отчёт 8h; прод зелёный | fast |

## Жёсткие стопы
- ❌ `AIOS_ENVIRONMENT=prod` / `AIOS_AUTH_MODE=oidc` на app **до** зелёного фронт-Bearer.
- ❌ `git push --force` в main; force-drop таблиц.
- ❌ Ломать Caddy Basic-Auth belakb.by.
- 1С — только OData **чтение**.

## Порядок запуска
1. **T0:** A + B + C старт параллельно.  
2. **T+2h:** A DoD → обновить issuer в runbook.  
3. **T+4h:** B checkpoint; C load-onec.  
4. **T+6h:** D только если A готов и есть окно; иначе D = «чеклист».  
5. **T+8h:** E смоук + итоговый отчёт.

## Критерий успеха сессии
1. Стабильный Keycloak issuer **или** явный блокер (нужен DNS/named tunnel от оператора).  
2. Фронт: либо патч Bearer-ready, либо точный ADR с файлами.  
3. Прод: номенклатура/цены из 1С **или** задокументированный блокер сети/кредов.  
4. App всё ещё Up на `dev`; смоук 200.
