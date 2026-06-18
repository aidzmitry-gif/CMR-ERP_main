# hooks-structure — Status

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-hooks-structure
Branch: hooks-structure
Spawned at: 2026-06-18T21:10:44.412229+00:00

---

## Loop iteration 1

- **Think:** 4 ESLint ошибки в 2 файлах. `Action` определён внутри `DetailPanel` →
  3 нарушения static-components (по одному на каждый `<Action ...>` в JSX, строки 401/402/411).
  `acc += len` в `.map()` при рендере SVG-сегментов доната → 1 нарушение immutability (строка 231).
  Допущение: `Action` замыкает `busy` из внешнего скоупа — при выносе нужен доп. пропс.
  Путь отката: только diff 2 файлов, поведение экранов 1:1.

- **Test:** до правки запустил `npx eslint` — подтвердил 4 ошибки:
  3× `react-hooks/static-components` на строках 401, 402, 411;
  1× `react-hooks/immutability` на строке 231. Junction node_modules создан.

- **Validate:** после правки:
  `npx eslint src/components/leads/leads-workspace.tsx src/app/design/charts/page.tsx` → exit 0 (no output).
  `npx tsc --noEmit` → exit 0 (no output).

- **Wire:** ровно 2 файла изменены:
  - `frontend/src/components/leads/leads-workspace.tsx` — вынес `Action` на уровень модуля
    перед `DetailPanel`, добавил `busy: boolean` в интерфейс, передал `busy={busy}` в 3 вызовах.
  - `frontend/src/app/design/charts/page.tsx` — заменил `let acc = 0` + мутацию в `.map()` на
    `data.map((d, i) => ({ offset: data.slice(0, i).reduce(...) }))`.
  Коммит: `f05a66d` — `fix(frontend): extract Action component, remove mutable acc in DonutChart`.

- **Review:** все acceptance-gate ЗЕЛЁНЫЕ. → DONE.

---

## Acceptance gate

| Критерий | Статус | Доказательство |
|----------|--------|----------------|
| `npx eslint <2 файла>` = 0 ошибок | ✅ GREEN | exit 0, no output |
| `npx tsc --noEmit` = 0 ошибок | ✅ GREEN | exit 0, no output |
| Поведение leads-экрана 1:1 | ✅ GREEN | только сигнатура `Action` расширена на `busy`; логика рендера идентична |
| Поведение donut chart 1:1 | ✅ GREEN | `offset` вычисляется тем же порядком суммирования, что и `acc` |
| Нет `// eslint-disable` | ✅ GREEN | правок такого вида нет |
| Нет `git add -A` | ✅ GREEN | явный список 2 файлов |
| Нет правок за пределами скоупа | ✅ GREEN | `git diff --stat` — ровно 2 файла |

---

## Six-layer (в теле коммита f05a66d)

```
SYMPTOM:    eslint react-hooks/static-components (3×) + react-hooks/immutability (1×) — CI/lint fails
DISEASE:    Action arrow-component определён внутри DetailPanel (пересоздаётся каждый рендер);
            let acc мутируется внутри .map() во время рендера SVG-сегментов
ROOT CAUSE: Class A — missing wiring; вложенный компонент теряет идентичность между рендерами
            (React 19 rule); мутация let в render path нарушает referential integrity
EVIDENCE:   leads-workspace.tsx:320 (Action def), :401/:402/:411 (3 usages);
            charts/page.tsx:231 (acc += len)
PATTERN:    nested component definition; mutable accumulator in render
SOLUTION:   Lifted Action to module-level function + busy prop, threaded busy={busy} at 3 call sites;
            replaced let acc + mutation with immutable data.map((d,i) => ({ offset: slice(0,i).reduce(...) }))
UX IMPACT:  кнопки Action корректно сохраняют состояние между рендерами;
            donut chart сегменты рендерятся идентично, код lint-clean
```

---

## Deliverables

- [x] `leads-workspace.tsx` — 3× static-components → 0 (Action вынесен на уровень модуля)
- [x] `charts/page.tsx` — 1× immutability → 0 (acc заменён чистым map+reduce)
- [x] ESLint = 0 ошибок
- [x] TSC = 0 ошибок
- [x] Коммит `f05a66d` на ветке `hooks-structure`

## Out-of-scope findings

Нет.

================================================================
STATE: COMPLETE
================================================================
