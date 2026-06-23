# Задание: sprav-import (экран 6 «Импорт из 1С — синк LIVE, маппинг/предпросмотр ДЕМО»)

Портируешь **экран 6** вкладки «Справочники»: адаптер 1С. Смешанный статус — синк реальный,
маппинг/предпросмотр конфликтов — демо (гэп C, бэкенда нет).

**Сначала прочитай:** `coordination/sprav-fe-common.md` + `coordination/sprav-import-scope.md`.
Визуальный эталон — `spravochniki-import-1c-preview.html`.

**Цель (Goal-Driven):**
1. `app/erp/spravochniki/import/page.tsx` (server) → `AppShell(crumbs=["ERP","Справочники","Импорт из 1С"])`
   + клиент. (SSR-данных тут немного — можно тонкую страницу.)
2. `components/erp/spravochniki/sprav-import.tsx` (`"use client"`):
   - **LIVE:** кнопка «Синхронизировать» → `fetch("/api/integrations/1c/sync", {method:"POST"})`,
     рендер summary `{counterparties,new_counterparties,counterparty_aliases,stock}`.
   - **ДЕМО:** шаги маппинг полей → предпросмотр конфликтов → импорт из макета, **с плашкой «демо»**.
3. Чистая логика (если есть, напр. формат summary) — `lib/spravochniki-import.ts` + vitest.
   Не трогай `reference-data.ts`. НЕ дорисовывай бэкенд маппинга.

**Гейт:** `cd frontend && npx tsc --noEmit` чисто; vitest зелено; вид как в макете. Только файлы scope.
Мелкие коммиты, six-layer, **без push**.

Блокер → `STATE: NEEDS-ORCHESTRATOR-ANSWER` в `coordination/sprav-import-status.md`, завершайся.


## Ответ оркестратора (2026-06-15T19:36Z)
Твой процесс оборвался в середине /code-review (last: CLAUDE none). Прочитай свой coordination/sprav-import-status.md (если есть) и git log --oneline main..HEAD в своём worktree — пойми, что уже закоммичено. Доведи задачу экрана 6 (импорт 1С: маппинг/предпросмотр/конфликты, демо до backend-фазы) до конца: заверши /code-review → /simplify по своим файлам, гейт (cd frontend && npx tsc --noEmit чисто; vitest если есть логика), мелкие коммиты без push, и поставь STATE: COMPLETE в coordination/sprav-import-status.md. Не задавай вопросов вживую.

Продолжи с того места, где остановился: прочитай свой coordination/sprav-import-status.md, учти ответ выше и доведи задачу до STATE: COMPLETE.
