#!/usr/bin/env bash
###############################################################################
# split-to-repos.sh — раздать монорепо CMR-ERP_main по репозиториям-модулям
#                     и собрать супер-проект на git submodules.
#
# ВНИМАНИЕ: это РЕКОНСТРУКЦИЯ. Оригинальный скрипт в репозитории отсутствовал,
# поэтому он написан заново по спецификации из задачи. Сначала ВСЕГДА читайте
# предпросмотр (DRY) и сверяйте карту «модуль -> репозиторий» ниже.
#
# Режимы запуска:
#   bash split-to-repos.sh            # ПРЕДПРОСМОТР (DRY=true) — НИЧЕГО не меняет
#   DRY=false bash split-to-repos.sh  # боевой прогон
#
# Переменные окружения (значения по умолчанию):
#   DRY=true                       true = только предпросмотр, без изменений
#   OWNER=aidzmitry-gif            владелец репозиториев на GitHub
#   WORK_BRANCH=split/submodules   рабочая ветка (main НЕ трогаем)
#   PUSH_SUPER=true                в боевом режиме пушить рабочую ветку в origin
#
# Что делает боевой прогон:
#   1) ставит бэкап-тег pre-split-<дата> на текущий HEAD;
#   2) переходит на ветку split/submodules (создаёт от текущего HEAD);
#   3) для 9 КОДОВЫХ доменов: git subtree split modules/<имя> (с историей)
#      -> push в репозиторий модуля -> git rm + git submodule add modules/<имя>;
#   4) для 8 не-submodule доменов: 3 с кодом (legal/office/knowledge) пушатся
#      содержимым modules/<имя> (subtree split, с историей, БЕЗ submodule —
#      код остаётся в монорепо); 5 пустых — README-каркас;
#   5) создаёт bootstrap.sh и коммитит его;
#   6) (PUSH_SUPER) пушит split/submodules в origin.
#
# НЕ выносится из супер-проекта (остаётся как есть):
#   core/ frontend/ migrations/ config/ tests/ .github/ modules/integrations/
###############################################################################
set -euo pipefail

DRY="${DRY:-true}"
OWNER="${OWNER:-aidzmitry-gif}"
WORK_BRANCH="${WORK_BRANCH:-split/submodules}"
PUSH_SUPER="${PUSH_SUPER:-true}"
DATE_TAG="pre-split-$(date +%Y-%m-%d)"
GIT_NAME="$(git config user.name 2>/dev/null || echo "$OWNER")"
GIT_EMAIL="$(git config user.email 2>/dev/null || echo "$OWNER@users.noreply.github.com")"
LAST_ERR=""

# --- Карта: КОДОВЫЙ домен -> репозиторий (подключается как submodule в modules/<имя>)
#     Формат строки: "<модуль-папка-в-modules/>  <репозиторий>"
CODE_MODULES=(
  "sales        CRM"
  "procurement  ZAK-3"
  "production   PRO-4"
  "wms          SKL-5"
  "logistics    LOG-6"
  "finance      fin-7"
  "marketing    MAR-8"
  "service      SER-POD-9"
  "hr           HR-10"
)

# --- Карта: не-submodule домен -> репозиторий-каркас (НЕ submodule сейчас)
#     Формат: "<имя-без-пробелов>  <репозиторий>  <локальный-путь-или-->"
#       путь != "-"  -> репо засевается содержимым пути (subtree split, с историей, БЕЗ submodule)
#       путь == "-"  -> в репо пушится README-каркас
SKELETON_DOMAINS=(
  "главная      GL-1        -"
  "лиды         CRM-LID1.1  -"
  "тендеры      CRM-TEN1.2  -"
  "юр-отдел     UR-12       modules/legal"
  "офис         OF-11       modules/office"
  "база-знаний  BZ-13       modules/knowledge"
  "аналитика    AN-14       -"
  "бухгалтерия  BY-15       -"
)

ANY_BAD=0

say(){ printf '%s\n' "$*"; }
hr(){  printf -- '----------------------------------------------------------------------\n'; }

# Состояние репозитория на GitHub: missing | empty | nonempty | error
repo_state(){
  local full="$OWNER/$1" out rc
  out=$(gh api "repos/$full/commits?per_page=1" 2>&1) && rc=0 || rc=$?
  LAST_ERR=""
  if [ "$rc" -eq 0 ]; then echo nonempty; return; fi
  if printf '%s' "$out" | grep -qiE 'Git Repository is empty|HTTP 409'; then echo empty;   return; fi
  if printf '%s' "$out" | grep -qiE 'Not Found|HTTP 404';            then echo missing; return; fi
  LAST_ERR="$out"; echo error
}

preflight(){
  hr
  say "split-to-repos.sh  |  DRY=$DRY  |  OWNER=$OWNER  |  рабочая ветка=$WORK_BRANCH"
  hr
  if [ ! -f config/modules.py ] || [ ! -d .git ]; then
    say "ОШИБКА: запускать из корня CMR-ERP_main (нет config/modules.py или .git/)"; exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    say "ОШИБКА: gh не авторизован — выполните 'gh auth login'"; exit 1
  fi
  say "gh: авторизован.   Текущая ветка: $(git branch --show-current)"
  say "Бэкап-тег боевого прогона: $DATE_TAG   |   автор коммитов: $GIT_NAME <$GIT_EMAIL>"
}

preview_repos(){
  hr; say "ПРОВЕРКА 17 РЕПОЗИТОРИЕВ (owner = $OWNER)"; hr
  say "Кодовые домены (9) -> submodule в modules/<имя>:"
  local entry mod repo name st
  for entry in "${CODE_MODULES[@]}"; do
    read -r mod repo <<<"$entry"
    st=$(repo_state "$repo")
    printf '  modules/%-12s -> %-26s : ' "$mod" "$OWNER/$repo"
    if [ ! -d "modules/$mod" ]; then printf '[нет локальной папки modules/%s] ' "$mod"; ANY_BAD=1; fi
    case "$st" in
      empty)    printf 'репо есть, пустой -> submodule\n' ;;
      nonempty) printf 'репо есть, НЕ пустой — пропускаю\n'; ANY_BAD=1 ;;
      missing)  printf 'репо НЕ найден — пропускаю\n';       ANY_BAD=1 ;;
      *)        printf 'ОШИБКА проверки: %s\n' "$LAST_ERR";  ANY_BAD=1 ;;
    esac
  done
  say ""
  say "Не-submodule домены (8): 3 с кодом (контент) + 5 пустых (README):"
  local path act
  for entry in "${SKELETON_DOMAINS[@]}"; do
    read -r name repo path <<<"$entry"
    st=$(repo_state "$repo")
    if [ "$path" != "-" ]; then
      act="каркас+контент ($path, с историей)"
      [ -d "$path" ] || { act="[нет папки $path] -> README"; ANY_BAD=1; }
    else
      act="каркас (README)"
    fi
    printf '  %-12s -> %-26s : ' "$name" "$OWNER/$repo"
    case "$st" in
      empty)    printf 'репо есть, пустой -> %s\n' "$act" ;;
      nonempty) printf 'репо есть, НЕ пустой — пропускаю\n'; ANY_BAD=1 ;;
      missing)  printf 'репо НЕ найден — пропускаю\n';       ANY_BAD=1 ;;
      *)        printf 'ОШИБКА проверки: %s\n' "$LAST_ERR";  ANY_BAD=1 ;;
    esac
  done
  hr
  say "Остаётся в супер-проекте: core/ frontend/ migrations/ config/ tests/ .github/ modules/integrations/"
  hr
}

require_clean_tree(){
  # учитываем только отслеживаемые изменения (untracked, напр. сам скрипт/.venv, игнорируем)
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    say "ОШИБКА: рабочее дерево не чистое (есть незакоммиченные изменения). Останов."; exit 1
  fi
}

ensure_work_branch(){
  git tag -f "$DATE_TAG" >/dev/null
  say ">> Бэкап-тег поставлен: $DATE_TAG"
  if git show-ref --verify --quiet "refs/heads/$WORK_BRANCH"; then
    git checkout "$WORK_BRANCH"
  else
    git checkout -b "$WORK_BRANCH"
  fi
  say ">> Работаем на ветке $WORK_BRANCH (main не трогаем)"
}

split_one_code_module(){
  local mod="$1" repo="$2" url="https://github.com/$OWNER/$repo.git"
  local exb="split-export-$mod"
  say ">> [$mod] subtree split modules/$mod (с историей)"
  git branch -D "$exb" >/dev/null 2>&1 || true
  git subtree split --prefix="modules/$mod" -b "$exb"
  say ">> [$mod] push -> $OWNER/$repo (main)"
  git push "$url" "$exb:refs/heads/main"
  say ">> [$mod] git rm modules/$mod из супер-проекта"
  git rm -r --quiet "modules/$mod"
  git commit -q -m "chore(split): вынести modules/$mod в репозиторий $repo"
  rm -rf "modules/$mod"               # убрать незакоммиченные остатки (__pycache__ и т.п.), иначе submodule add упадёт
  rm -rf ".git/modules/modules/$mod"  # подстраховка на случай повторного прогона
  say ">> [$mod] git submodule add <- $repo"
  git submodule add "$url" "modules/$mod"
  git commit -q -m "chore(split): подключить modules/$mod как submodule ($repo)"
  git branch -D "$exb" >/dev/null 2>&1 || true
}

push_skeleton(){
  local name="$1" repo="$2" url="https://github.com/$OWNER/$repo.git" tmp
  tmp="$(mktemp -d)"
  (
    cd "$tmp"
    git -c init.defaultBranch=main init -q
    printf '# %s\n\nКаркас репозитория модуля «%s» (домен пока без кода).\nПодключение как git submodule — на следующем этапе.\n' "$repo" "$name" > README.md
    git add README.md
    git -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" commit -q -m "chore: инициализация каркаса $repo"
    git push -q "$url" main
  )
  rm -rf "$tmp"
  say ">> [каркас] $name -> $OWNER/$repo (README запушен)"
}

# Засеять репозиторий-каркас реальным содержимым пути (с историей), БЕЗ submodule.
# Код остаётся в монорепо: ни git rm, ни submodule add тут не делаем.
seed_repo_with_content(){
  local mod_path="$1" repo="$2" url="https://github.com/$OWNER/$repo.git"
  local exb="split-seed-${mod_path//\//-}"
  say ">> [seed] subtree split $mod_path -> $OWNER/$repo (с историей, без submodule)"
  git branch -D "$exb" >/dev/null 2>&1 || true
  git subtree split --prefix="$mod_path" -b "$exb"
  git push "$url" "$exb:refs/heads/main"
  git branch -D "$exb" >/dev/null 2>&1 || true
}

write_bootstrap(){
  cat > bootstrap.sh <<'BOOT'
#!/usr/bin/env bash
# Поднять супер-проект CMR-ERP_main после клона (--recurse-submodules).
set -euo pipefail
git submodule update --init --recursive
python -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate 2>/dev/null || true
pip install -r requirements.txt -r requirements-dev.txt
if [ -d frontend ]; then ( cd frontend && npm install ); fi
echo "bootstrap: готово."
BOOT
  chmod +x bootstrap.sh
  git add bootstrap.sh
  git commit -q -m "chore(split): bootstrap.sh для подъёма супер-проекта"
  say ">> bootstrap.sh создан и закоммичен"
}

summary(){
  hr
  if [ "$ANY_BAD" -ne 0 ]; then
    say "ИТОГ: есть проблемные репозитории (НЕ пустой / НЕ найден / ошибка) — см. выше."
    $DRY && say "Это предпросмотр. Боевой прогон при таких пометках частично пропустит репозитории."
  else
    if $DRY; then
      say "ИТОГ: все 17 репозиториев есть и пусты. К боевому прогону готово."
    else
      say "ИТОГ: боевой прогон завершён. 9 модулей -> submodule, 8 доменов -> отдельные репозитории."
    fi
  fi
  if $DRY; then
    say ""
    say "DRY-режим: НИЧЕГО не изменено."
    say "Боевой прогон:  DRY=false bash split-to-repos.sh"
  fi
  hr
}

main(){
  preflight
  preview_repos
  if $DRY; then summary; exit 0; fi

  # -------------------- БОЕВОЙ ПРОГОН --------------------
  require_clean_tree
  ensure_work_branch
  local entry mod repo name st path
  for entry in "${CODE_MODULES[@]}"; do
    read -r mod repo <<<"$entry"
    st=$(repo_state "$repo")
    if [ "$st" = empty ] && [ -d "modules/$mod" ]; then
      split_one_code_module "$mod" "$repo"
    else
      say ">> ПРОПУСК [$mod -> $repo]: состояние '$st' (нужен пустой репо и локальная папка)"
    fi
  done
  for entry in "${SKELETON_DOMAINS[@]}"; do
    read -r name repo path <<<"$entry"
    st=$(repo_state "$repo")
    if [ "$st" != empty ]; then
      say ">> ПРОПУСК [$name -> $repo]: состояние '$st' (нужен пустой репо)"
    elif [ "$path" != "-" ] && [ -d "$path" ]; then
      seed_repo_with_content "$path" "$repo"
    else
      push_skeleton "$name" "$repo"
    fi
  done
  write_bootstrap
  if [ "$PUSH_SUPER" = true ]; then
    say ">> push $WORK_BRANCH -> origin"
    git push -u origin "$WORK_BRANCH"
  fi
  summary
}

main "$@"
