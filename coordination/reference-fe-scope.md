# Scope: фронт-вкладка «Справочники» (Ф4) — порт 7 макетов в Next.js

**Кому:** Sonnet-флот (1 воркер = 1 экран). **От кого:** сессия «Справочники» (Opus).
**Статус подготовки (Opus):** ГОТОВО — типизированный API-клиент `frontend/src/lib/reference-data.ts`
(+ `reference-data.test.ts`, vitest 6/6, `tsc --noEmit` чисто). Бэкенд-эндпоинты реальны и
проверены тестами (см. ниже). Воркерам остаётся **только UI**: страницы + клиентские компоненты.

> Принцип: **бэкенд НЕ трогаем** (заморожен), пишем презентацию поверх готового клиента.
> Где реального эндпоинта нет — честный демо-экран с пометкой (НЕ выдавать демо за live).

## Что уже есть (бери, не переписывай)

`frontend/src/lib/reference-data.ts` — единственная точка доступа к бэкенду вкладки:
- **Каталог (SSR):** `fetchReferenceCatalog(roles)` → дерево по отделам; `fetchAiCatalog(roles)`.
- **Строки справочника:** `fetchSimpleRef(table, {archived,roles})`, `fetchRefRowsByEndpoint(endpoint, roles)`
  (generic — по `endpoint` из метаданных), CRUD: `createSimpleRef/patchSimpleRef/archiveSimpleRef`.
- **Версионные SCD2:** `fetchCurrencyRates(key,roles)`, `fetchVatRates(key,roles)`,
  `currencyRateAsOf(key,on)`, `addRateVersion(table,payload)`.
- **MDM:** `fetchDuplicateClusters(roles)`, `mergeCounterparties(survivor,dup)`, `unmergeCounterparty(dup)`.
- **AI:** `runReferenceQuery({ref,key,as_of,name,limit})`.
- **Чистые хелперы (тестируемы):** `flattenCatalog`, `isCurrentVersion`, `sortVersionsDesc`, `totalDuplicates`.

Конвенция как в `api.ts`: SSR-чтения на `${BASE}` с `X-User-Roles`; клиентские мутации — через
прокси `/api/*`; всё в try/catch с безопасным fallback. **Новые эндпоинты НЕ нужны** — если
кажется, что нужен, это backend-gap (см. §«Гэпы» — флажок оркестратору, не чини сам).

## Структура страницы (эталон — `app/erp/settings/access/page.tsx`)

- Тонкая **серверная** страница: `app/erp/spravochniki/**/page.tsx` → `AppShell` (crumbs) +
  клиентский компонент. SSR-данные тянет через клиент с `currentRole()` (`@/lib/role-server`).
- **Клиентские** компоненты — `components/erp/spravochniki/*` (интерактив, мутации через `/api`).
- Дизайн-токены ровно как в макетах: `canvas/ink/muted/brand` + `shadow-card`, `rounded-2xl`,
  деньги — **BYN**. Иконки — `lucide-react`. Никаких новых глобальных стилей.
- Чистую логику (фильтры/группировки) — в `lib/`, тестировать co-located `*.test.ts` (vitest).

## 7 экранов → маршруты, данные, статус

| # | Макет (visual source of truth) | Маршрут (предлагаемый) | API из клиента | Данные |
|---|---|---|---|---|
| 1 | `spravochniki-preview.html` (дерево отделов + таблица) | `/erp/spravochniki` | `fetchReferenceCatalog`, `fetchRefRowsByEndpoint`/`fetchSimpleRef` | **LIVE** (каталог + строки simple-ref) |
| 2 | `spravochniki-versioned-preview.html` (курсы SCD2) | `/erp/spravochniki/rates` | `fetchCurrencyRates`, `currencyRateAsOf`, `addRateVersion`, `isCurrentVersion`, `sortVersionsDesc` | **LIVE** |
| 3 | `spravochniki-merge-preview.html` (дедуп/MDM) | `/erp/spravochniki/merge` | `fetchDuplicateClusters`, `mergeCounterparties`, `unmergeCounterparty`, `totalDuplicates` | **LIVE** |
| 4 | `spravochniki-ai-preview.html` (semantic/MCP) | `/erp/spravochniki/ai` | `fetchAiCatalog`, `runReferenceQuery` | **LIVE** |
| 5 | `spravochniki-card-preview.html` (карточка + алиасы) | `/erp/spravochniki/counterparty/[id]` | `runReferenceQuery({ref:"core.counterparties",...})` (список/поиск) | **ЧАСТИЧНО** — карточка-эталон есть по списку; **алиасы/аудит — демо** (гэп A) |
| 6 | `spravochniki-import-1c-preview.html` (адаптер 1С) | `/erp/spravochniki/import` | live-кнопка `POST /api/integrations/1c/sync` (summary) | **ЧАСТИЧНО** — синк реальный; **маппинг/предпросмотр конфликтов — демо** (гэп C) |
| 7 | `spravochniki-hierarchy-preview.html` (категории parent_id+ltree) | `/erp/spravochniki/categories` | — | **ДЕМО** — backend категорий нет (гэп B) |

Хаб `spravochniki-preview-index.html` → навигация между экранами (вкладки/ссылки внутри `/erp/spravochniki`).

## Гэпы бэкенда — ФЛАЖОК оркестратору, НЕ чинить в этой полосе

- **A. Карточка контрагента + алиасы/аудит:** нет `GET /system/mdm/counterparty/{id}` (эталон +
  `counterparty_alias` + история). Сейчас доступен только список через `reference.query`. Раздел
  «алиасы-источники / аудит» на экране 5 — демо до появления эндпоинта.
- **B. Иерархия категорий:** таблицы/эндпоинта категорий (parent_id + ltree) ещё нет — экран 7 демо.
- **C. Импорт 1С — маппинг/предпросмотр:** есть только идемпотентный `POST /integrations/1c/sync`
  (отдаёт summary `{counterparties,new_counterparties,counterparty_aliases,stock}`). Шаги
  «маппинг полей → конфликты → импорт» из макета — демо до backend-фазы адаптера.

## Координация (общий worktree main, параллельные сессии)

1. **Полоса (захватить в `coordination/ACTIVE-SESSIONS.md` перед стартом):**
   `frontend/src/app/erp/spravochniki/**`, `frontend/src/components/erp/spravochniki/**`,
   `frontend/src/lib/reference-data*` (если нужны ещё чистые хелперы — добавляй СЮДА, с тестом).
2. **НЕ трогать хотспоты:** `frontend/src/lib/api.ts` (свой клиент уже есть — `reference-data.ts`),
   `frontend/src/components/sidebar.tsx`. Пункт меню «Справочники» в сайдбаре — **одна** интеграционная
   задача: захватить `sidebar.tsx` в «Хотспоты», добавить ссылку на `/erp/spravochniki`, освободить.
3. **Бэкенд заморожен:** `core/**`, `modules/**`, миграции — не редактировать. Нужен эндпоинт →
   это гэп (§выше), пиши оркестратору, не лезь в core.
4. **Без новых зависимостей** (lucide-react/tailwind уже есть). Лесенка лени: нативное > одна строка > минимум кода.
5. Коммить мелко по экрану. **Никаких push** без явной просьбы оператора.

## Приёмка (на каждый экран)

- `npx tsc --noEmit` — чисто (lint в проекте не настроен — tsc это гейт).
- Новая чистая логика покрыта co-located vitest; `npx vitest run` зелёно.
- LIVE-экраны рендерят реальные данные при поднятом бэкенде (`BACKEND_URL=http://127.0.0.1:8000`,
  не `localhost` — IPv6-гоча SSR); при недоступном бэке — graceful degrade (клиент уже отдаёт пусто/null).
- ЧАСТИЧНО/ДЕМО-секции **визуально помечены** как демо (плашка/бейдж), не выдаются за live.
- Внешний вид соответствует соответствующему `spravochniki-*-preview.html` (токены/сетка/иконки).
