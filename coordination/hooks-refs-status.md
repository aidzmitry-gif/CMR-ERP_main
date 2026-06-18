# hooks-refs — Status

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-hooks-refs
Branch: hooks-refs
Spawned at: 2026-06-18T21:09:22.321075+00:00

---

## Loop iteration 1

- **Think:** Props named `ref` in `RefIcon` and `CatalogEntry` + map variable `ref` in `SpravAi`
  conflict with React 19's forwarded-ref mechanism. ESLint `react-hooks/refs` treats every
  property access on a variable/prop named `ref` as "reading ref.current during render".
  Fix: rename data-prop `ref → reference` in both sub-components; map variable `ref → item`.
  No behavior change — purely a rename. No other files need touching.
- **Test:** Baseline — `npx eslint src/components/erp/spravochniki/sprav-ai.tsx` → 11 errors confirmed.
- **Validate:** After edits — ESLint EXIT:0 (0 errors), `npx tsc --noEmit` EXIT:0 (0 errors).
- **Wire:** 3 surgical edits in `frontend/src/components/erp/spravochniki/sprav-ai.tsx`:
  1. `RefIcon` prop `ref → reference` + body references
  2. `CatalogEntry` prop `ref → reference` + body references (incl. `<RefIcon reference={reference} />`)
  3. Map variable `ref → item` + `ref={ref}` → `reference={item}` at call site
- **Review:** All acceptance-gate GREEN → DONE (single iteration)

---

## Six-layer (коммит 820f494)

```
SYMPTOM:    11 react-hooks/refs errors in sprav-ai.tsx (ESLint exit 1)
DISEASE:    props named `ref` in RefIcon/CatalogEntry + map variable `ref` in SpravAi
ROOT CAUSE: Class C — architecture drift; React 19 made `ref` a special forwarded-ref prop,
            so any prop/variable named `ref` triggers the linter on every property access
EVIDENCE:   sprav-ai.tsx:14 RefIcon({ ref }), :20 CatalogEntry({ ref }), :142 map((ref) =>)
PATTERN:    Prop-name collision with React 19 forwarded-ref mechanism
SOLUTION:   Rename data-prop ref→reference in RefIcon+CatalogEntry; map var ref→item in SpravAi
UX IMPACT:  No visible change — AI-справочник screen works identically
```

---

## Acceptance gate

- [x] `npx eslint src/components/erp/spravochniki/sprav-ai.tsx` → EXIT:0 (0 errors)
- [x] `npx tsc --noEmit` → EXIT:0 (0 errors)
- [x] Поведение экрана не изменилось (только переименование пропов)
- [x] `// eslint-disable` не использован
- [x] Six-layer в теле коммита
- [x] Тронут ровно 1 файл (в рамках скоупа)
- [x] Нет `git add -A`

---

## Deliverables

- [x] `frontend/src/components/erp/spravochniki/sprav-ai.tsx` — 14 строк изменено, 0 ошибок eslint/tsc
- [x] Коммит `820f494` на ветке `hooks-refs`

---

## Out-of-scope findings

Нет.

---

## PITFALLS-DISCOVERED

- **СИМПТОМ: хук CLAUDE.md напомнил `/code-review` → `/simplify` постфактум (уже после `git commit`)** — причина: hook срабатывает на первый Bash-вызов после git-операции, коммит уже создан. → **ЛЕЧЕНИЕ:** для чисто-rename правок без логики это приемлемо; для нетривиальных изменений запускать review на staged-diff ДО `git commit`.

---

================================================================
STATE: COMPLETE
================================================================
