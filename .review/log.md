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
