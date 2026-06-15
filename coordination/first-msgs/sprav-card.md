# Задание: sprav-card (экран 5 «Карточка эталона контрагента — golden record»)

Портируешь **экран 5** вкладки «Справочники»: карточка одного контрагента-эталона —
реквизиты + источники (alias 1С/Bitrix/merge) + слитые дубли + контакты + аудит.
Гэп A закрыт — это **LIVE**-экран.

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-card-scope.md`.
Визуальный эталон — `spravochniki-card-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/counterparty/[id]/page.tsx` (async server). ⚠️ Next 15: `params` — async,
   используй `const { id } = await params;`. Затем `currentRole()` → `fetchCounterpartyCard(Number(id), role)`
   → `AppShell(crumbs=["ERP","Справочники","Контрагент"])` + клиент. `null` → состояние «не найдено».
2. `components/erp/spravochniki/sprav-card.tsx` (`"use client"`): секции — реквизиты (name/unp/
   is_active), источники `aliases` (source/external_ref), слитые дубли `merged_duplicates`,
   контакты `contacts`, аудит `audit`. Пустой аудит → «Истории изменений пока нет» (НЕ «демо»).
3. Чистая логика (если есть, напр. группировка алиасов по source) — `lib/spravochniki-card.ts` + vitest.
   Не трогай `reference-data.ts`.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-card-status.md`, завершайся.
