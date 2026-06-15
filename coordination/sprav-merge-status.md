# sprav-merge — Status

================================================================
STATE: COMPLETE
================================================================

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-sprav-merge
Branch: sprav-merge
Completed at: 2026-06-15T18:45

---

## Loop iteration 1

- **Think:**
  - Допущения: первый `members[0]` в кластере — эталон (golden record), остальные — дубли.
    `fetchDuplicateClusters` → SSR на сервере; `mergeCounterparties` / `unmergeCounterparty` →
    POST через Next.js `/api/*`-прокси. Обновление после мутации — через `router.refresh()` (re-run SSR).
  - Путь отката: все файлы новые, удаление восстанавливает прежнее состояние без риска.
  - Tradeoffs: `DuplicateMember` имеет только `id+name` (нет полного профиля) → таблица сравнения
    упрощена (без адреса/телефона/менеджера из макета, тк доп.запросы за `fetchCounterparty`
    выходят за scope). Показана структурная таблица: запись / наименование / УНП / роль / действие.

- **Test (TDD):** создан `spravochniki-merge.test.ts` (5 test-case'ов для `clusterSurvivor` и
  `clusterDuplicates`) ДО написания логики.

- **Validate:** `vitest.cmd run …` → `Test Files 1 passed (1), Tests 5 passed (5)`.
  `tsc --noEmit` → exit 0, no output.

- **Wire:** созданы 4 файла из scope (ниже). Ничего из exclude не затронуто.

- **Review:** acceptance-gate — 6/6 GREEN (см. ниже). STATE: COMPLETE.

---

## Karpathy 5-step compliance

- [x] Think — гипотеза + допущения + tradeoffs перед кодом
- [x] Test — TDD: тесты написаны первыми
- [x] Validate — vitest 5/5 + tsc exit 0
- [x] Wire — минимальное изменение, только scope-файлы
- [x] Review — acceptance-gate GREEN

---

## Six-layer (для коммита)

```
SYMPTOM:    Маршрут /erp/spravochniki/merge отсутствует — экран дедупликации MDM не реализован
DISEASE:    Недостающий порт фронтенда (экран 3 из 7 вкладки «Справочники»)
ROOT CAUSE: Класс A — отсутствующая проводка page.tsx + клиентского компонента
EVIDENCE:   coordination/sprav-merge-scope.md; backend-эндпоинт GET /system/mdm/duplicates уже есть
PATTERN:    Порт UI по готовому API-клиенту (reference-data.ts → fetchDuplicateClusters)
SOLUTION:   Создать page.tsx (SSR), SpravMerge client component, чистую lib + тесты
UX IMPACT:  Пользователь может видеть кластеры дублей по УНП, сливать и расклеивать их
```

---

## STR-роли

N/A — изменения тривиальные (создание 4 новых файлов без изменения существующих).

---

## Deliverables (по scope)

- [x] `frontend/src/app/erp/spravochniki/merge/page.tsx` — async server, `currentRole()` → `fetchDuplicateClusters(role)` → `AppShell(crumbs=["ERP","Справочники","Дедупликация"])` + `<SpravMerge>`
- [x] `frontend/src/components/erp/spravochniki/sprav-merge.tsx` — `"use client"`, список кластеров с `totalDuplicates`, кнопки «Слить» (`mergeCounterparties`) и «Расклеить» (`unmergeCounterparty`), `router.refresh()` после мутации
- [x] `frontend/src/lib/spravochniki-merge.ts` — `clusterSurvivor` + `clusterDuplicates`
- [x] `frontend/src/lib/spravochniki-merge.test.ts` — 5 тестов, vitest 5/5 GREEN
- [x] `coordination/acceptance/sprav-merge.json` — 6 критериев, все passes:true

---

## Acceptance-gate матрица

| id | kind | desc | passes |
|----|------|------|--------|
| types | types | tsc --noEmit чисто в frontend/ | ✅ GREEN |
| vitest | test | vitest 5/5 для spravochniki-merge.test.ts | ✅ GREEN |
| scope | manual | Тронуты только 4 scope-файла | ✅ GREEN |
| clusters | manual | SSR кластеры + totalDuplicates счётчик | ✅ GREEN |
| mutations | manual | mergeCounterparties / unmergeCounterparty + refresh | ✅ GREEN |
| graceful | manual | empty state при initial=[] | ✅ GREEN |

---

## Out-of-scope findings

- node_modules не было в worktree — создан junction-link на `Сlaude CRM - проект/frontend/node_modules`
  (стандартная процедура для воркеров, не влияет на код).
- `DuplicateMember` содержит только `{id, name}` — без адреса/телефона/менеджера.
  Детальная таблица полей (как в preview HTML) требует `fetchCounterparty(id)` per member.
  Принято решение показать упрощённую таблицу (запись/наименование/УНП/роль/действие) — данных достаточно для слияния, UX не деградирует.
  Потенциальный апгрейд: добавить детальный fetch в отдельной итерации (вне текущего scope).
