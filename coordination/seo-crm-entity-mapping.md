# SEO ↔ CRM Entity Mapping (MAR-8)

> **Статус:** черновик для интеграции подмодуля SEO/GEO Growth Platform в модуль Marketing (MAR-8).  
> **SEO-платформа:** `d:\6 Проекты\SEO Сервис\`  
> **CRM/ERP:** `d:\6 Проекты\CRM ERP\Сlaude CRM - проект\`  
> **Дата:** 2026-07-01

---

## 1. Назначение и принцип интеграции

**Цель:** связать SEO/GEO Growth Platform с Marketing OS CRM так, чтобы маркетолог видел SEO-метрики и задачи в кокпите, а SEO-команда работала в специализированном сервисе.

**Принцип — bounded service, не слияние монолита:**

| Аспект | Решение |
|--------|---------|
| Система-истина по SEO-данным | SEO-сервис (`Project`, `Keyword`, `Cluster`, `SeoTask`, `Competitor`, позиции) |
| Система-истина по клиентам и воронке | CRM ядро (`Counterparty`, `Contact`, `Lead`, `Deal`) |
| Связь | `SyncLink` / alias + события outbox (`core.event_bus`), без прямых JOIN между схемами |
| UI | Виджеты и deep-link в MAR-8; полный SEO UI остаётся в SEO-приложении |
| Деплой | Независимые репозитории и БД; общий Keycloak (целевое состояние) |

Формула SEO-платформы **Positions → Competitors → Reasons → Tasks → Growth** встраивается в Marketing OS как канал «Контент/SEO» (агент #3 в `marketing-prototype/КОНЦЕПЦИЯ.md`), питающий ROMI и pipeline, а не как дублирование rank-tracker внутри CRM.

---

## 2. Таблица сопоставления сущностей

| SEO entity | CRM entity | Relationship | Notes |
|------------|------------|--------------|-------|
| **Project** | `marketing.seo_project` (new) + `Counterparty` | N:1 client, 1:1 optional `Campaign` | `Project.domain` → `marketing.site.domain`. Для агентств: один `Counterparty` — много проектов. `SyncLink(entity_type="seo_project", system="seo_platform")` хранит внешний `project.id` (UUID). |
| **Project** (агентство) | `Campaign` | optional 1:1 | Кампания типа `channel=seo` группирует бюджет/цели; не заменяет `seo_project`. |
| **Keyword** | — (SEO-only) | ref by `seo_project_id` + external id | В CRM не денормализуем тысячи ключей. Сводка: `keyword_count`, `top10_count` в `marketing.seo_snapshot`. |
| **Cluster** | — (SEO-only) | ref in events/tasks | Статусы (`no_landing`, `cannibalization`, …) остаются в SEO. В CRM — только агрегаты и ссылки на кластер в payload событий. |
| **SeoTask** | `marketing.seo_task` (new) + `Approval` (optional) | mirror + handoff | SEO — источник задачи; CRM хранит `external_task_id`, `status`, `priority`, `assigned_to` (`User`), HITL через `Approval` для публикаций. |
| **SeoTask** (commercial / landing) | `Lead` (indirect) | via landing URL + UTM | Задачи на лендинги привязываются к `Campaign.utm_*`; конверсии в лиды — через существующий `intake.lead.received`. |
| **Competitor** | `marketing.competitor_intel` (new, snapshot) | N per `seo_project` | Домен конкурента не `Counterparty` (это клиенты/поставщики). Разведка для агента #7; overlap/visibility — снимки, не golden record. |
| **Visibility metrics** (`visibility`, `VisibilityPoint`, positions) | `marketing.seo_snapshot` (new) | time-series per project | Дневной/недельный снимок для кокпита MAR-8 и ROMI-дашборда. Детальные позиции — только в SEO API. |
| **QuickWin** (derived) | event `marketing.seo.quick_win.detected` | ephemeral → widget | Не отдельная таблица; триггер уведомления SEO- и маркетинг-менеджеру. |
| **User** (SEO operator) | `User` (`app_user`) | map by `username` / Keycloak `sub` | Единый SSO; роли не копируются автоматически — см. §6. |
| **Client contact** | `Contact` | via `Counterparty` | При онбординге проекта: выбор существующего контрагента или создание из SEO «client name». |

**Существующие CRM-сущности без прямого SEO-аналога:**

- `Lead` / `Deal` — downstream от SEO-канала (трафик → заявка), не зеркало `Keyword`.
- `Campaign` — программный уровень атрибуции (`marketing-prototype` §4); SEO-проект — тактический уровень.

---

## 3. Предлагаемые дополнения схемы CRM (`marketing.*`)

Минимальный набор для Phase B–C (миграции в submodule MAR-8):

```sql
-- Сайт клиента (может быть без SEO-проекта)
marketing.site (
  id, counterparty_id FK → public.counterparty,
  domain VARCHAR(255) UNIQUE,
  region VARCHAR(64),
  is_primary BOOLEAN,
  created_at
)

-- Привязка SEO-проекта к CRM
marketing.seo_project (
  id,
  site_id FK → marketing.site,
  campaign_id FK → marketing.campaign NULL,
  external_project_id VARCHAR(36),  -- UUID из SEO-сервиса
  name VARCHAR(255),
  status VARCHAR(16),  -- active|paused|archived
  last_sync_at TIMESTAMPTZ,
  created_at
)

-- Зеркало приоритетных SEO-задач (не полный импорт)
marketing.seo_task (
  id,
  seo_project_id FK,
  external_task_id VARCHAR(36),
  title VARCHAR(255),
  type VARCHAR(32),       -- on_page|technical|landing_page|...
  priority VARCHAR(16),
  status VARCHAR(32),
  url VARCHAR(512),
  cluster_name VARCHAR(255),
  assigned_to VARCHAR(128),  -- app_user.username
  approval_id FK → public.approval NULL,
  synced_at TIMESTAMPTZ
)

-- Периодические снимки для кокпита
marketing.seo_snapshot (
  id,
  seo_project_id FK,
  snapshot_date DATE,
  visibility NUMERIC(8,2),
  total_keywords INT,
  top10_count INT,
  critical_tasks INT,
  quick_wins INT,
  payload JSONB  -- опционально: top clusters, competitor delta
)

-- Снимки конкурентов (разведка)
marketing.competitor_intel (
  id,
  seo_project_id FK,
  competitor_domain VARCHAR(255),
  visibility_score NUMERIC(8,2),
  keywords_overlap INT,
  captured_at TIMESTAMPTZ
)
```

**Переиспользование ядра:**

- `public.sync_link` — `entity_type IN ('seo_project', 'site')`, `system='seo_platform'`, `external_ref=<uuid>`.
- `public.counterparty_alias` — при импорте клиента из внешней CRM агентства (`source='seo'`).

Расширение существующей `marketing.campaign` (Phase C+): `channel` значение `seo`, поля `utm_source`, `utm_medium`, `goal`, `kpi_json` — по `marketing-prototype/КОНЦЕПЦИЯ.md` §6.

---

## 4. Интеграция через шину событий

Паттерн как у `marketing.campaign.launched` → `sales.on_campaign_launched`: transactional outbox, подписчики в других модулях.

### SEO → CRM (webhook или polling-коннектор → `emit`)

| Event | Payload (ключевые поля) | Subscriber | Действие |
|-------|-------------------------|------------|----------|
| `marketing.seo.project.linked` | `seo_project_id`, `external_project_id`, `counterparty_id`, `domain` | marketing | upsert `seo_project`, `SyncLink` |
| `marketing.seo.snapshot.updated` | `external_project_id`, `visibility`, `top10_count`, `critical_tasks`, `date` | marketing | insert `seo_snapshot`, обновить виджет |
| `marketing.seo.task.created` | `external_task_id`, `project_id`, `title`, `type`, `priority`, `url`, `cluster` | marketing | insert `seo_task`; critical → Telegram |
| `marketing.seo.task.status_changed` | `external_task_id`, `status`, `actor` | marketing | sync status; `implemented` → опционально `Approval` resolve |
| `marketing.seo.quick_win.detected` | `project_id`, `keyword`, `position`, `frequency`, `url` | marketing | виджет «требует внимания» |
| `marketing.seo.visibility.alert` | `project_id`, `metric`, `delta`, `threshold` | marketing, sales (opt) | алерт при падении visibility > N% |

### CRM → SEO

| Event | Payload | Subscriber | Действие |
|-------|---------|------------|----------|
| `marketing.campaign.launched` | `name`, `channel`, `leads` | seo-connector (если channel=seo) | тег UTM в SEO metadata проекта |
| `sales.lead.received` | `lead_id`, `source`, `utm_*` | seo-connector | атрибуция конверсии к landing/cluster (Phase D) |
| `core.counterparty.merged` | `golden_id`, `merged_ids` | seo-connector | перепривязка `site.counterparty_id` |

**Версионирование:** `version: 1` в payload; breaking changes → новый `event_type` суффикс `.v2`.

---

## 5. Граница API

### CRM (коннектор / MAR-8) — inbound для SEO и UI CRM

| Method | Endpoint | Назначение |
|--------|----------|------------|
| `POST` | `/marketing/seo/projects/link` | привязать `external_project_id` к `counterparty` + `site` |
| `GET` | `/marketing/seo/projects` | список связанных проектов (сводка из `seo_snapshot`) |
| `GET` | `/marketing/seo/projects/{id}/tasks` | зеркало `marketing.seo_task` |
| `POST` | `/marketing/seo/webhook` | приём событий от SEO-сервиса (HMAC) |
| `GET` | `/marketing/seo/projects/{id}/deep-link` | URL в SEO UI с SSO token |

### SEO-сервис — system of record

| Method | Endpoint | Назначение |
|--------|----------|------------|
| `GET/POST` | `/api/v1/projects` | CRUD проектов |
| `GET` | `/api/v1/projects/{id}/keywords` | ключи (пагинация) |
| `GET` | `/api/v1/projects/{id}/clusters` | кластеры |
| `GET/PATCH` | `/api/v1/projects/{id}/tasks` | SEO-задачи |
| `GET` | `/api/v1/projects/{id}/competitors` | конкуренты |
| `GET` | `/api/v1/projects/{id}/metrics/visibility` | временной ряд |
| `POST` | `/api/v1/integrations/crm/register` | регистрация webhook URL + secret |

**Правило:** CRM не вызывает SEO API из UI напрямую с браузера (CORS/secrets). Прокси через CRM BFF или server-side connector.

---

## 6. Auth / RBAC

| Контекст | Механизм | Маппинг |
|----------|----------|---------|
| CRM | `core.services.auth`: dev headers / Keycloak OIDC | Модуль MAR-8 объявляет роли: `marketing_viewer`, `marketing_manager`, `marketing_seo` |
| SEO | JWT / API keys per org (TBD) | Service account `crm-connector` для webhook |

**Предлагаемые permissions (CRM):**

| Permission | Роли | Доступ |
|------------|------|--------|
| `marketing.campaigns.read` | viewer+ | кампании |
| `marketing.seo.read` | viewer+, marketing_seo | снимки, задачи, deep-link |
| `marketing.seo.manage` | marketing_manager | link/unlink проектов |
| `marketing.seo.tasks.assign` | marketing_seo | назначение `assigned_to` |

Пользователь с `marketing_seo` в CRM получает scoped access в SEO (claim `crm_project_ids[]` или org-wide для in-house).

---

## 7. Поэтапный rollout (Phase A–D)

| Phase | Scope | DoD |
|-------|-------|-----|
| **A — Registry** | `marketing.site`, `marketing.seo_project`, `SyncLink`, SSO, deep-link | Маркетолог видит список привязанных сайтов/проектов в виджете MAR-8 |
| **B — Metrics feed** | `seo_snapshot`, webhook `snapshot.updated`, виджет KPI | Кокпит показывает visibility, top10, critical tasks без импорта keywords |
| **C — Task handoff** | `seo_task`, события task.*, `Approval` для публикаций | Критические SEO-задачи в «требует внимания»; статусы синхронизируются |
| **D — Attribution** | UTM на `Campaign`, `sales.lead.received` → SEO, ROMI | Связь SEO-лендингов с лидами и pipeline; оценка вклага канала SEO |

Зависимости: Phase B требует работающий SEO API (сейчас MVP на mock); Phase D — зрелая атрибуция из `marketing-prototype` §4.

---

## 8. Открытые вопросы / решения

| # | Вопрос | Варианты | Рекомендация |
|---|--------|----------|--------------|
| 1 | Один SEO tenant на всех клиентов ERP или multi-tenant? | single org / per counterparty | In-house: single; агентство: org per agency |
| 2 | Где хранить полный список keywords? | только SEO / реплика в CRM DWH | только SEO + snapshot в CRM |
| 3 | `SeoTask` → создавать `Lead` при commercial intent? | да / нет | нет автоматически; только human HITL |
| 4 | Submodule MAR-8 vs `connectors/seo.py` в ядре | submodule / core connector | connector в ядре для webhook + тонкий UI в MAR-8 |
| 5 | Частота sync visibility | realtime / daily | daily batch Phase B; alerts realtime |
| 6 | Вынос `Lead` в `modules/leads` (CRM-LID1.1) | влияет на `sales.lead.received` | согласовать подписки до Phase D |
| 7 | Конкурент как `Counterparty`? | да / нет | **нет** — отдельная `competitor_intel` |
| 8 | i18n: SEO UI RU, CRM RU — общий glossary task types? | shared enum / mapping table | shared enum в контракте webhook v1 |

---

## Ссылки

- SEO data model: `SEO Сервис/docs/architecture/data-model.md`
- CRM Marketing stub: `modules/marketing/models.py` (`Campaign`)
- Event pattern: `modules/marketing/routes.py` → `marketing.campaign.launched` → `modules/sales/events.py`
- Marketing OS vision: `marketing-prototype/КОНЦЕПЦИЯ.md`
- SEO-side summary: `SEO Сервис/docs/architecture/crm-integration.md`
