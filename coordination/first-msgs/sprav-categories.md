# Задание: sprav-categories (экран 7 «Иерархия групп номенклатуры — parent_id дерево»)

Портируешь **экран 7** вкладки «Справочники»: иерархический классификатор групп номенклатуры
(adjacency list по parent_id). Гэп B закрыт — это **LIVE**-экран.

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-categories-scope.md`.
Визуальный эталон — `spravochniki-hierarchy-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/categories/page.tsx` (async server): `currentRole()` →
   `fetchNomenclatureGroups(role)` → `AppShell(crumbs=["ERP","Справочники","Группы номенклатуры"])` + клиент.
2. `components/erp/spravochniki/sprav-categories.tsx` (`"use client"`): дерево через
   `buildCategoryTree(groups)` (хелпер из reference-data.ts — ИСПОЛЬЗУЙ, не пиши свой). CRUD:
   `createNomenclatureGroup` / `patchNomenclatureGroup` (имя/родитель) / `archiveNomenclatureGroup`;
   после мутации — обнови дерево.
3. Чистая логика (если есть, напр. вычисление глубины/отступов) — `lib/spravochniki-categories.ts` + vitest.
   Не трогай `reference-data.ts`. ltree из макета НЕ реализовывать (будущая Postgres-оптимизация).

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-categories-status.md`, завершайся.
