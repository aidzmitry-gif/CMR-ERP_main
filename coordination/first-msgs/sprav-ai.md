# Задание: sprav-ai (экран 4 «AI-каталог + структурный запрос reference.query»)

Портируешь **экран 4** вкладки «Справочники»: узкий AI-каталог (`ai_exposed`) + интерактивный
структурный запрос `reference.query` (точное значение с историчностью).

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-ai-scope.md`.
Визуальный эталон — `spravochniki-ai-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/ai/page.tsx` (async server): `currentRole()` → `fetchAiCatalog(role)` →
   `AppShell(crumbs=["ERP","Справочники","AI-доступ"])` + клиент.
2. `components/erp/spravochniki/sprav-ai.tsx` (`"use client"`): список AI-видимых справочников
   (поля/эндпоинты/tool-описание) + форма запроса (ref/key/as_of/name/limit) → `runReferenceQuery`,
   вывод результата.
3. Чистая логика (если есть) — `lib/spravochniki-ai.ts` + vitest. Не трогай `reference-data.ts`.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-ai-status.md`, завершайся.
