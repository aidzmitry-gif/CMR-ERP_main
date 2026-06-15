# Задание: sprav-merge (экран 3 «Дедупликация / MDM — слияние дублей контрагентов»)

Портируешь **экран 3** вкладки «Справочники»: MDM-дедуп контрагентов по УНП — кластеры дублей,
слияние в эталон (survivorship) и обратная расклейка.

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-merge-scope.md`.
Визуальный эталон — `spravochniki-merge-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/merge/page.tsx` (async server): `currentRole()` →
   `fetchDuplicateClusters(role)` → `AppShell(crumbs=["ERP","Справочники","Дедупликация"])` + клиент.
2. `components/erp/spravochniki/sprav-merge.tsx` (`"use client"`): список кластеров дублей по УНП,
   счётчик `totalDuplicates`, на каждом дубле кнопки «Слить в эталон» (`mergeCounterparties`) и
   «Расклеить» (`unmergeCounterparty`); после мутации — обнови список.
3. Чистая логика (если есть) — `lib/spravochniki-merge.ts` + vitest. Не трогай `reference-data.ts`.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-merge-status.md`, завершайся.
