# sprav-ai — Status

## Worktree
Path: D:\6 Проекты\CRM ERP\crm-worker-sprav-ai
Branch: sprav-ai
Spawned at: 2026-06-15T14:55:01.768885+00:00

## Karpathy 5-step iterations

### Iteration 1 (2026-06-15T18:45Z)

**Think:**
- Прочитал: worker-engineering-standards.md, sprav-ai-scope.md, sprav-fe-common.md, reference-fe-scope.md
- Изучил: reference-data.ts (все типы AiCatalog/AiReference/ReferenceQueryInput/ReferenceQueryResult готовы)
- Эталон визуала: spravochniki-ai-preview.html — 2-column grid (каталог + цепочка ответа) + нижний ряд (semantic/pgvector)
- Решение: заменить статичную «цепочку ответа» на интерактивную форму запроса (нужна scope); оставить нижний ряд как в макете
- Допущение: as_of — HTML `<input type="date">` автоматически даёт YYYY-MM-DD, пустое значение не слать

**Test (написан до кода):**
- vitest покрывает buildQueryInput (7 случаев) + FALLBACK_CATALOG (5 случаев) = 12 тестов

**Validate (написаны файлы):**
- `lib/spravochniki-ai.ts` — buildQueryInput + FALLBACK_CATALOG (6 ai_exposed справочников)
- `lib/spravochniki-ai.test.ts` — 12 vitest тестов
- `app/erp/spravochniki/ai/page.tsx` — SSR: currentRole()→fetchAiCatalog(role)→AppShell+SpravAi
- `components/erp/spravochniki/sprav-ai.tsx` — "use client": каталог + форма + результат + graceful degrade

**Wire:**
- Поднят junction node_modules (pitfall 9)
- `npx tsc --noEmit` → пусто (чисто)
- `npx vitest run src/lib/spravochniki-ai.test.ts` → 12/12 зелено

**Review:**
- Коммит `9804cfa` (4 файла, six-layer body)
- Замечание от хука: в следующий раз запускать /code-review перед коммитом

## Acceptance gate

- [x] `/erp/spravochniki/ai` показывает AI-каталог (`fetchAiCatalog`): какие справочники видны AI, поля, эндпоинты.
- [x] Есть форма структурного запроса (ref/key/as_of/name/limit) → `runReferenceQuery`, результат рендерится.
- [x] Graceful degrade без бэка (initial=null → FALLBACK_CATALOG + демо-плашка). Вид как `spravochniki-ai-preview.html`.
- [x] `npx tsc --noEmit` чисто; vitest 12/12 зелено. Только файлы scope (4/4). Six-layer. Без push.

## Доставленные файлы (scope)

| Файл | Статус |
|------|--------|
| `frontend/src/app/erp/spravochniki/ai/page.tsx` | создан |
| `frontend/src/components/erp/spravochniki/sprav-ai.tsx` | создан |
| `frontend/src/lib/spravochniki-ai.ts` | создан |
| `frontend/src/lib/spravochniki-ai.test.ts` | создан |

## Коммиты

- `9804cfa` feat(frontend/spravochniki): экран 4 AI-каталог + интерактивный reference.query

## PITFALLS-DISCOVERED

- **СИМПТОМ: хук CLAUDE.md напомнил `/code-review` → `/simplify` постфактум (уже после коммита)** — причина: hook срабатывает на `Bash`, а не на логику кода, поэтому предупреждение приходит только когда git commit уже вызван. → **ЛЕЧЕНИЕ: запускать `/code-review` на staged-diff ДО `git commit`, не после**; в частности, хук виден в первом Bash-вызове git-операции — взять за правило проверять tsc+vitest+review в отдельном шаге до staging.

---

STATE: COMPLETE
