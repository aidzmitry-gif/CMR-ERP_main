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


## Ответ оркестратора (2026-06-15T15:04Z)
Стандарты и задание не пришли телом — прочитай их сам с диска (ты в своём worktree, файлы есть): 1) coordination/worker-engineering-standards.md (стандарты), 2) coordination/sprav-fe-common.md (общий контракт фронта справочников), 3) coordination/sprav-catalog-scope.md (твой LOOP CONTRACT + acceptance gate), 4) coordination/first-msgs/sprav-catalog.md (само задание). Затем выполняй задачу экрана 1 (каталог справочников + дерево отделов + хаб) по этим файлам. Не задавай вопросов вживую; блокер пиши в coordination/sprav-catalog-status.md.

Продолжи с того места, где остановился: прочитай свой coordination/sprav-catalog-status.md, учти ответ выше и доведи задачу до STATE: COMPLETE.
