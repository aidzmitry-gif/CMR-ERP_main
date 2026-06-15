# Задание: sprav-catalog (экран 1 «Справочники — каталог + дерево отделов + хаб»)

Ты портируешь **экран 1** вкладки «Справочники» в Next.js. Это корень `/erp/spravochniki`
и хаб со ссылками на остальные 6 экранов.

**Сначала прочитай:** `coordination/sprav-fe-common.md` (общий контракт, паттерн страницы,
развязка файлов, приёмка) и `coordination/sprav-catalog-scope.md` (твой LOOP CONTRACT и
acceptance gate). Визуальный эталон — `spravochniki-preview.html` и хаб `spravochniki-preview-index.html`.

**Цель (Goal-Driven):**
1. Серверная страница `app/erp/spravochniki/page.tsx` (async): `currentRole()` →
   `fetchReferenceCatalog(role)` → `AppShell(crumbs=["ERP","Справочники","Каталог"])` + клиентский компонент.
2. Клиентский компонент `components/erp/spravochniki/sprav-catalog.tsx` (`"use client"`):
   слева дерево по отделам (departments из каталога), справа таблица строк выбранного
   справочника — подгружай строки через `fetchRefRowsByEndpoint(endpoint, role)` (endpoint берётся
   из метаданных справочника). Вверху — хаб-ссылки на 6 маршрутов: `/erp/spravochniki/rates`,
   `/erp/spravochniki/merge`, `/erp/spravochniki/ai`, `/erp/spravochniki/counterparty`,
   `/erp/spravochniki/import`, `/erp/spravochniki/categories`.
3. Если нужна чистая логика (группировка/сортировка дерева) — `lib/spravochniki-catalog.ts`
   + co-located vitest. Не трогай `reference-data.ts`.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest (если есть логика) зелено; вид как в макете.
Тронь только файлы своего scope. Коммить мелко, six-layer в теле, **без push**.

Упёрся в неоднозначность продукта или чужой файл — пиши `STATE: NEEDS-ORCHESTRATOR-ANSWER`
в `coordination/sprav-catalog-status.md` и завершайся. Не задавай вопросов вживую.
