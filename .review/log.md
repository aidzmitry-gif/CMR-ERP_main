# Журнал ревью (append-only)

## Ревью 2026-06-15 — ПЕРВЫЙ ЗАПУСК (окно 2 дн.)
Северная звезда: довести 9 модулей до beta с нулём crit-уязвимостей.
Стек адаптирован: ruff по Python-корню, tsc/eslint по ./frontend, JSON-парс через node
(в проекте python3 = битый Store-alias). eslint = null (не установлен во frontend).
Метрики базы: feat=53, commits=102, rework=14.7%, ruff=1, tsc=0, todo=12, delta=2.1 МБ.
**Следующий шаг:** установить eslint во frontend (закрыть слепое пятно качества) ИЛИ
оставить null осознанно; гонять ревью по дельте от d743b35.

## Фикс 2026-06-16 — /code-review нашёл 2 honesty-бага в metrics.sh, исправлены
- npm_audit при ошибке audit печатал 0 («чисто») вместо null («не мерили») → метрика главной
  цели «0 crit» врала зелёным. Теперь null, если нет metadata.vulnerabilities.
- TODO-grep считал собственный паттерн в metrics.sh (+3 ложных, 12→15). Исключён `:!.review`.
- Перепрогон: audit=null, todo=12 (верно), tsc=0, ruff=1. Baseline jsonl пересоздан чистым.

## 2026-06-16 — закрыто eslint-слепое пятно + всплыла 1 high-уязвимость
- Установлены eslint 9 + eslint-config-next@16 (flat-config eslint.config.mjs, БЕЗ FlatCompat —
  он несовместим с ESLint 9). lint-скрипт: next lint (deprecated, удалён в Next 16) → eslint.
- eslint метрика: null → **48** (37 errors, 11 warnings) на текущем коде. Слепое пятно закрыто.
- После установки deps npm audit заработал и нашёл **3 уязвимости (1 high: undici TLS-bypass)** —
  ровно то, что прятал ложный зелёный. Метрика «0 crit» теперь честная.
- metrics.sh: audit-парсер переписан устойчивым к сдвоенному JSON-выводу npm на Windows
  (брал position-3023-ошибку → null). Теперь audit=3/high_crit=1 верно.
- Долг: undici high чинится `npm audit fix` (тронет lockfile — отдельным шагом по согласованию).

## 2026-06-16 — /code-review по metrics.sh: закрыт ещё 1 honesty-путь
- num("") → null (а не 0): при полном сбое node на шаге audit/eslint пустой stdout давал
  Number("")=0 → ложный зелёный на метрике «0 crit». Теперь честный null. Прогон цел (audit=3/high=1).
- Отложенный долг (латентный, сейчас НЕ срабатывает): балансировщик {} в audit-парсере наивен к
  скобкам внутри строк JSON. Проверено — в текущем выводе npm audit скобок в строках нет. Чинить,
  только если появятся (заголовок/URL уязвимости с `}`).

## 2026-06-16 — закрыта high-уязвимость undici (npm audit fix, без --force)
- undici 7.27.0 → 7.28.0 (через jsdom, devDep тестов). high_crit: 1 → **0**. Цель «0 crit» держится.
- Next.js остался на 15.5.19 — `--force` НЕ запускал (он бы откатил next до 9.3.3, breaking).
- Осознанный долг: 2 moderate (postcss внутри next). Фикс только через ломающий откат next →
  ждём апстрим-патч next, руками не лезем.
- tsc=0 после обновления (фронт цел). Изменён только package-lock.json.

## 2026-06-19 — разбор eslint: 48 → 37 (закрыто тривиальное, React-hooks отложено)
- coverage/** добавлен в ignores (сгенерированные артефакты, git-ignored — не линтить).
- eslint --fix снял мёртвые eslint-disable директивы (от старого next lint) + прочее автофиксимое.
- Руками: postcss.config.mjs (анонимный экспорт → const config), убран unused Badge (charts),
  удалена мёртвая функция barLabel (sprav-rates). warnings 11 → 0. tsc=0.
- ОТЛОЖЕНО как известный долг (решение пользователя «оставить как есть»): 37 react-hooks errors
  (22 set-state-in-effect, 11 refs, 3 static-components, 1 immutability acc+= в charts) — новые
  строгие правила React 19, код работает в проде. Метрика eslint=37 честно это показывает.

## 2026-06-19 — флот воркеров (Sonnet) закрыл 37 react-hooks: eslint 37 → 0
- 3 воркера на Sonnet от ветки sales-2.0-redesign, файлы не пересекались:
  - hooks-refs: 11× refs в sprav-ai.tsx — `ref` был именем пропа (конфликт с React 19
    forwarded-ref) → переименован в reference/item.
  - hooks-setstate: 22× set-state-in-effect в 22 файлах — lazy useState / .then(setState) / queueMicrotask.
  - hooks-structure: 3× static-components (leads-workspace: Action вынесен из тела) +
    1× immutability (charts: DonutChart без acc+= мутации, предвычисление offset).
- Все 3 интегрированы (merge + boot-smoke OK), worktree снесены.
- Адверсариальная проверка ПОСЛЕ слияния всех: eslint=0 errors/0 warnings, tsc=0. Регрессий нет.
- Метрика: eslint 37 → **0**. tsc=0, high_crit=0. Frontend полностью чист по линту/типам.
- ⚠️ Гочи: integrate без acceptance-gate просто мержит; untracked coordination/*-scope.md в
  основном чекауте конфликтуют с merge — убирал их перед integrate (версия приходит из воркера).
