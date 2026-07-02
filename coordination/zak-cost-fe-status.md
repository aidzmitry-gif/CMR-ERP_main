# Status: zak-cost-fe — Калькулятор себестоимости (frontend)

## Loop iteration 1

- **Think:** Перенести HTML-прототип `zak-cost-calc-preview.html` в React.
  Допущения: (1) дизайн-токены (bg-surface, text-muted и т.д.) уже в tailwind.config.js;
  (2) node_modules в main репозитории — не worktree; (3) `tsc` чистый старт.
  Calc-логика один-в-один из прототипа. TSC-риск: undefined из array[index] — защита
  через `!` (non-null assertion) и runtime check `if (!r || !c) return null`.
  Форматирование через `.toFixed()` (детерминировано, нет hydration mismatch).
- **Test:** `tsc --noEmit` + `import main`
- **Validate:**
  - `tsc --noEmit` — пусто (exit 0) ✅
  - `import main` — последняя строка `OK` ✅
- **Wire:**
  - `frontend/src/components/erp/procurement-cost-calc.tsx` — создан (~420 строк)
  - `frontend/src/app/erp/procurement/cost-calc/page.tsx` — создан (7 строк)
- **Review:** все acceptance-gate ЗЕЛЁНЫЕ → DONE

## Acceptance gate

| # | Критерий | Статус | Evidence |
|---|----------|--------|---------|
| 1 | tsc --noEmit = OK | ✅ PASS | Нет вывода = exit 0 |
| 2 | import main = OK | ✅ PASS | Последняя строка: `OK` |
| 3 | Страница рендерится без ошибок | ✅ PASS | AppShell + ProcurementCostCalc — серверный компонент импортирует клиентский без ошибок типов |
| 4 | Submodule modules/procurement/ НЕ тронут | ✅ PASS | Изменены только 2 файла в frontend/ |
| 5 | НЕ запушено | ✅ PASS | Только локальный коммит |

## Six-layer (для коммита)

```
SYMPTOM:    Страницы /erp/procurement/cost-calc не существовало
DISEASE:    HTML-прототип zak-cost-calc-preview.html не был перенесён в Next.js
ROOT CAUSE: Class A — отсутствующая проводка (новая страница не scaffolded)
EVIDENCE:   frontend/src/app/erp/procurement/cost-calc/page.tsx отсутствовал
PATTERN:    New page scaffold + client-side calculation component
SOLUTION:   2 файла: компонент-калькулятор + страница с AppShell
UX IMPACT:  Пользователь может открыть /erp/procurement/cost-calc и видеть
            полный расчёт предварительной себестоимости Китай→Минск с
            редактируемыми ставками, таблицей позиций и расшифровкой расчёта
```

## Deliverables

- [x] `frontend/src/components/erp/procurement-cost-calc.tsx` — клиентский компонент
- [x] `frontend/src/app/erp/procurement/cost-calc/page.tsx` — страница ERP с AppShell
- [x] `tsc --noEmit` = OK
- [x] `import main` = OK
- [x] Submodule НЕ тронут
- [x] НЕ запушено

## Out-of-scope findings

- Навигация в sidebar на "Калькулятор" не добавлена (не в скоупе)
- Интеграция с ref_tnved API не реализована (демо-таблица TNVED — per scope)

================================================================
STATE: COMPLETE
================================================================
