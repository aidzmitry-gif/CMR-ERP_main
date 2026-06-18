#!/usr/bin/env bash
# .review/metrics.sh — снимает метрики проекта за период и дописывает строку в .review/metrics.jsonl
# Архитектура: ВСЯ арифметика здесь (детерминировано). LLM-ревьюер только читает JSON и делает выводы.
# Использование: ./.review/metrics.sh [BASE_REF]
#   BASE_REF — коммит/тег прошлого ревью (last_commit из .review/state.json). Нет → окно 2 дня.
# Модель: DORA (throughput+стабильность) + Flow (распределение) + находки качества.
#
# СТЕК ЭТОГО ПРОЕКТА (отличия от дефолтного шаблона — намеренные, не трогать вслепую):
#  - Корень = Python-монолит (ruff). Frontend (Node: tsc/eslint) живёт в ./frontend.
#  - Windows/Cygwin bash. `python3` в проекте перехватывает Store-заглушка (App-alias) и падает,
#    поэтому ВЕСЬ парс JSON — через `node -e`, а не python3.
#  - eslint во frontend не установлен → метрика = null ("не мерили"), НЕ 0 ("чисто"). Разница важна
#    для честности (Гудхарт): 0 значит проверено-и-чисто, null значит инструмент отсутствует.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
FE="frontend"   # корень Node-фронта

BASE="${1:-}"
if [ -n "$BASE" ] && git rev-parse --verify "$BASE" >/dev/null 2>&1; then
  RANGE="${BASE}..HEAD"; WINDOW="since ${BASE}"; SINCE=""
else
  SINCE="2 days ago"; RANGE=""; WINDOW="last 2 days"
fi

commits_subjects() {
  if [ -n "$RANGE" ]; then git log "$RANGE" --pretty=%s 2>/dev/null
  else git log --since="$SINCE" --pretty=%s 2>/dev/null; fi
}
git_in_range() {  # доп. аргументы git log
  if [ -n "$RANGE" ]; then git log "$RANGE" "$@" 2>/dev/null
  else git log --since="$SINCE" "$@" 2>/dev/null; fi
}

# === DORA throughput: фичи + коммиты + слияния (прокси частоты интеграции/деплоя) ===
THROUGHPUT=$(commits_subjects | grep -ciE '^feat(\(.+\))?!?:' || true)
COMMITS_TOTAL=$(commits_subjects | grep -c '' || true)
MERGES=$(git_in_range --merges --oneline | grep -c '' || true)

# === DORA стабильность: rework rate (доля починок) ===
FIXES=$(commits_subjects | grep -ciE '^(fix|bug|hotfix|revert)(\(.+\))?!?:' || true)
if [ "${COMMITS_TOTAL:-0}" -gt 0 ]; then
  REWORK_PCT=$(awk "BEGIN{printf \"%.1f\", ($FIXES/$COMMITS_TOTAL)*100}")
else REWORK_PCT=0; fi

# === Flow Distribution: features / defects / maintenance / other ===
F_FEAT="$THROUGHPUT"
F_DEFECT="$FIXES"
F_MAINT=$(commits_subjects | grep -ciE '^(refactor|perf|style|chore|build|ci|docs|test)(\(.+\))?!?:' || true)
F_CLASSIFIED=$(( F_FEAT + F_DEFECT + F_MAINT ))
F_OTHER=$(( COMMITS_TOTAL - F_CLASSIFIED )); [ "$F_OTHER" -lt 0 ] && F_OTHER=0

# === Находки качества (leading indicators) ===
# Frontend tsc/eslint — из ./frontend; парс через node (python3 в проекте = битый App-alias).
TSC="null"
if [ -x "$FE/node_modules/.bin/tsc" ]; then
  # pipefail off локально: grep -c при 0 совпадений даёт exit 1 — это не ошибка, а «0 ошибок типов».
  TSC=$( set +o pipefail; cd "$FE" && node_modules/.bin/tsc --noEmit 2>&1 | grep -cE 'error TS' )
fi
ESLINT="null"
if [ -x "$FE/node_modules/.bin/eslint" ]; then
  # eslint exit=1 при находках — снимаем pipefail локально; null если парс упал (инструмент сломан, не «чисто»).
  ESLINT=$( set +o pipefail; cd "$FE" && node_modules/.bin/eslint . -f json 2>/dev/null \
    | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{try{console.log(JSON.parse(s).reduce((a,f)=>a+f.messages.length,0))}catch{console.log('null')}})" )
fi
# npm audit — только если у фронта есть lockfile
AUDIT_TOTAL="null"; AUDIT_HIGHCRIT="null"
if [ -f "$FE/package.json" ] && command -v npm >/dev/null 2>&1; then
  AJ=$( (cd "$FE" && npm audit --json 2>/dev/null) || echo '{}' )
  # null (не 0!) если audit не дал metadata.vulnerabilities: 0 = «проверено-и-чисто»,
  # null = «audit не отработал». Парсер устойчив к сдвоенному выводу npm на Windows
  # (берём первый сбалансированный {...}). Один разбор → обе цифры "total highcrit".
  AUDIT=$(printf '%s' "$AJ" | node -e "
let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{
  try{
    let depth=0,start=s.indexOf('{'),end=-1;
    for(let i=start;i<s.length;i++){if(s[i]==='{')depth++;else if(s[i]==='}'){depth--;if(depth===0){end=i;break;}}}
    const v=JSON.parse(s.slice(start,end+1)).metadata.vulnerabilities;
    console.log(v?(v.total||0):'null', v?((v.high||0)+(v.critical||0)):'null');
  }catch{console.log('null null');}
});")
  AUDIT_TOTAL=${AUDIT% *}
  AUDIT_HIGHCRIT=${AUDIT#* }
fi
# ruff — Python-корень; парс через node
RUFF=0
if command -v ruff >/dev/null 2>&1; then
  # ruff exit=1 при найденных проблемах — под pipefail это валит пайп; снимаем локально.
  RUFF=$(set +o pipefail; ruff check . --output-format=json 2>/dev/null | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{try{console.log(JSON.parse(s).length)}catch{console.log(0)}})")
fi
# исключаем .review/ — иначе паттерн ниже считает сам себя (ложная инфляция долга)
TODO=$(git grep -nE 'TODO|FIXME|HACK|XXX' -- ':!.review' 2>/dev/null | grep -c '' || true)

# === Покрытие автоматизацией ===
NPM_SCRIPTS=0
[ -f "$FE/package.json" ] && NPM_SCRIPTS=$(node -e "console.log(Object.keys(require('./$FE/package.json').scripts||{}).length)" 2>/dev/null || echo 0)
GIT_HOOKS=$(ls .git/hooks 2>/dev/null | grep -v '\.sample$' | grep -c '' || true)
CI_STEPS=$(grep -rhE '^\s*run:' .github/workflows 2>/dev/null | grep -c '' || true)
# Хуки качества проекта живут в .claude/settings.json (PreToolUse/PostToolUse/Stop), не в .git/hooks:
CLAUDE_HOOKS=0
[ -f .claude/settings.json ] && CLAUDE_HOOKS=$(node -e "try{const h=require('./.claude/settings.json').hooks||{};console.log(Object.values(h).flat().length)}catch{console.log(0)}" 2>/dev/null || echo 0)

# === Экономия: прокси стоимости ревью = размер дельты ===
if [ -n "$RANGE" ]; then DELTA_BYTES=$(git diff "$RANGE" 2>/dev/null | wc -c | tr -d ' ')
else DELTA_BYTES=$(git_in_range -p | wc -c | tr -d ' '); fi

# === Собрать JSON через node (надёжно: null остаётся null, числа числами) и дописать ===
mkdir -p .review
M_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
JSON=$(M_DATE="$M_DATE" M_WINDOW="$WINDOW" \
  M_THROUGHPUT="${THROUGHPUT:-0}" M_COMMITS="${COMMITS_TOTAL:-0}" M_MERGES="${MERGES:-0}" M_REWORK="${REWORK_PCT:-0}" \
  M_FEAT="${F_FEAT:-0}" M_DEFECT="${F_DEFECT:-0}" M_MAINT="${F_MAINT:-0}" M_OTHER="${F_OTHER:-0}" \
  M_ESLINT="$ESLINT" M_TSC="$TSC" M_AUDIT="$AUDIT_TOTAL" M_AUDITHC="$AUDIT_HIGHCRIT" M_RUFF="${RUFF:-0}" M_TODO="${TODO:-0}" \
  M_NPMS="${NPM_SCRIPTS:-0}" M_HOOKS="${GIT_HOOKS:-0}" M_CLAUDEHOOKS="${CLAUDE_HOOKS:-0}" M_CI="${CI_STEPS:-0}" M_DELTA="${DELTA_BYTES:-0}" \
  node -e '
const env = process.env;
const num = (k) => { const v = env[k]; if (v === "null" || v === undefined) return null; const n = Number(v); return Number.isFinite(n) ? n : null; };
const o = {
  date: env.M_DATE, window: env.M_WINDOW,
  throughput_feat: num("M_THROUGHPUT"), commits_total: num("M_COMMITS"), merges: num("M_MERGES"),
  rework_rate_pct: num("M_REWORK"),
  flow_distribution: { features: num("M_FEAT"), defects: num("M_DEFECT"), maintenance: num("M_MAINT"), other: num("M_OTHER") },
  open_findings: { eslint: num("M_ESLINT"), tsc: num("M_TSC"), npm_audit_total: num("M_AUDIT"),
                   npm_audit_high_crit: num("M_AUDITHC"), ruff: num("M_RUFF"), todo: num("M_TODO") },
  automation: { npm_scripts: num("M_NPMS"), git_hooks: num("M_HOOKS"), claude_hooks: num("M_CLAUDEHOOKS"), ci_steps: num("M_CI") },
  review_cost: { delta_bytes: num("M_DELTA") }
};
console.log(JSON.stringify(o));
')
echo "$JSON" >> .review/metrics.jsonl
echo "$JSON"
