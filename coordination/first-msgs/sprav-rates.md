# Задание: sprav-rates (экран 2 «Версионные справочники SCD2 — курсы валют + НДС»)

Портируешь **экран 2** вкладки «Справочники»: версионные справочники (курсы валют, ставки НДС)
с историей версий (SCD Type 2, полуоткрытый интервал; текущая = `end_date=null`).

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-rates-scope.md`.
Визуальный эталон — `spravochniki-versioned-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/rates/page.tsx` (async server): `currentRole()` →
   `fetchCurrencyRates(undefined, role)` (+ `fetchVatRates`) → `AppShell(crumbs=["ERP","Справочники","Курсы и ставки"])`
   + клиентский компонент.
2. `components/erp/spravochniki/sprav-rates.tsx` (`"use client"`): таблица версий с выделением
   текущей (`isCurrentVersion`), сортировка `sortVersionsDesc`, форма добавления версии
   (`addRateVersion`), запрос as-of (`currencyRateAsOf`).
3. Чистая логика (если есть) — `lib/spravochniki-rates.ts` + vitest. Не трогай `reference-data.ts`.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер/неоднозначность → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-rates-status.md`, завершайся.


## Ответ оркестратора (2026-06-15T15:05Z)
Стандарты и задание не пришли телом — прочитай их сам с диска (ты в своём worktree): 1) coordination/worker-engineering-standards.md, 2) coordination/sprav-fe-common.md, 3) coordination/sprav-rates-scope.md (твой LOOP CONTRACT), 4) coordination/first-msgs/sprav-rates.md (задание). Затем выполняй экран 2 (версионные справочники SCD2 — курсы валют + НДС). Вопросов вживую не задавай; блокер — в coordination/sprav-rates-status.md.

Продолжи с того места, где остановился: прочитай свой coordination/sprav-rates-status.md, учти ответ выше и доведи задачу до STATE: COMPLETE.
