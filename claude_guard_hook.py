#!/usr/bin/env python3
"""claude_guard_hook.py — PreToolUse-гард: жёсткий блок катастрофических действий.

Запускается Claude Code ПЕРЕД каждым вызовом инструмента (Bash/Edit/Write/Read/…),
работает при ЛЮБОМ permission-mode, включая bypassPermissions. Это последний рубеж
против автономных факапов, prompt-injection и «удалённого шелла» через Telegram.

ФИЛОСОФИЯ: allow-by-default. Ничего НЕ спрашивает (для headless «спросить человека»
невозможно — только разрешить/запретить). Молча пропускает всё, КРОМЕ короткого
списка заведомо разрушительного, который ты руками почти никогда не пишешь, — поэтому
обычная работа идёт без трения и без подтверждений.

ПОКРЫТИЕ ШЕЛЛА: инструменты **Bash И PowerShell** (на Windows PowerShell — штатный шелл,
до 25.07.2026 он шёл мимо гарда: правила были написаны, но никогда не выполнялись).

ДВА УРОВНЯ:
  • BASE (всегда): катастрофа ФС, дропперы (curl|sh), доступ к секретам
    (.env/.ssh/id_rsa/~.claude.json), боковой ход на прод (tailscale ssh / prod-IP),
    git push --force, попытка отключить сам гард.
  • STRICT (только если выставлен env CLAUDE_GUARD_STRICT=1): добавляет «опасное, но
    иногда легитимное в dev» (reset --hard, clean -fdx, docker down -v, DROP TABLE…).
    tg_sessions.py включает STRICT для удалённых B-сессий, твой интерактив — нет.

Блокировка = stderr с причиной + exit 2 (Claude увидит причину и не выполнит вызов).
Разрешение = exit 0 без вывода. Блоки логируются в coordination/.tg-guard-denied.jsonl.
ИСКЛЮЧЕНИЕ (не блок): на `git commit` хук добавляет НЕблокирующее напоминание про
стандарт ревью (/code-review → /simplify) через hookSpecificOutput.additionalContext —
коммит выполняется в любом случае.

САМОЗАЩИТА (узкая): запись/удаление гарда или settings.json блокируется только когда
глагол записи (>, >>, tee, Set-Content/Out-File/Add-Content, sed -i, rm/del/Remove-Item)
ЦЕЛИТ в имя файла (см. _GUARD_WRITE). Простое упоминание имени — `cat`, `wc`, `ls`,
`git log/add/commit` с именем в сообщении/выводе — НЕ блокируется (раньше блокировалось
ложно: имя-подстрока + любой `>`).

УСТАНОВКА (важно, проверено 25.07.2026): гард зарегистрирован ТОЛЬКО в проектном
`.claude/settings.json` — в ~/.claude/settings.json секции "hooks" НЕТ. Значит сессии,
запущенные вне этого проекта (например из корня воркспейса «D:\\6 Проекты»), работают
БЕЗ гарда. Воркеры получают его отдельно, через `--settings` (spawn_workers.py).
Готовый блок — в coordination/TG-BRIDGE.md.

КОДИРОВКА: хук НЕ полагается на env PYTHONUTF8 (он задан только в проектном
settings.json, который лежит в .gitignore и до воркеров не доезжает) — stdin читается
байтами, stdout/stderr переводятся в UTF-8 явно. Иначе причина блока приходит мозаикой,
а на кириллице в команде stdin.read() падает с UnicodeDecodeError → гард молча выключается.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

STRICT = os.environ.get("CLAUDE_GUARD_STRICT", "") not in ("", "0", "false", "False")
DENY_LOG = Path(__file__).resolve().parent / "coordination" / ".tg-guard-denied.jsonl"

# Инструменты, на которые вешается гард. ОДИН источник истины: строку читают генераторы
# settings-файлов для воркеров (spawn_workers.py) и для удалённых B-сессий (tg_sessions.py).
# Раньше список жил четырьмя копиями, и PowerShell доехал не во все — самый рискованный
# путь (Telegram, headless, STRICT) оставался без покрытия при докстринге, обещавшем обратное.
GUARD_MATCHER = "Bash|PowerShell|Edit|Write|MultiEdit|Read|NotebookEdit"

# Имена защищаемых файлов (для файл-инструментов Edit/Write/MultiEdit — это путь цели,
# поэтому достаточно совпадения подстрокой). Для Bash используется узкий _GUARD_WRITE.
_GUARD_FILES = re.compile(
    r"""(?ix)
    claude_guard_hook\.py
    | (^|[\\/])\.claude[\\/]settings\.json
    | [\\/]\.claude[\\/]settings\.json
    | \.claude\.json
    """,
)

# ── BASE: команды Bash, блокируемые всегда ──────────────────────────────────────
_BASE_BASH = [
    # катастрофа ФС в корне/доме/корне диска
    (re.compile(r"(?i)\brm\s+(-\w*r\w*f|-\w*f\w*r|-r\s+-f|-f\s+-r)\b[^\n|;&]*\s(/|~|/\*|\*|\$HOME|[A-Za-z]:[\\/])(\s|$|/\*)"),
     "rm -rf по корню/дому/корню диска"),
    (re.compile(r"(?i)\b(Remove-Item|ri|rd|rmdir|del)\b[^\n|;]*[-/](Recurse|s)\b[^\n|;]*\s([A-Za-z]:[\\/]|\$HOME|~|\\)(\s|$)"),
     "рекурсивное удаление корня (Windows)"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"(?i)\bdd\b[^\n]*\bof=/dev/"), "dd на устройство"),
    (re.compile(r"(?i)\bmkfs(\.\w+)?\b"), "mkfs (форматирование)"),
    (re.compile(r"(?i)>\s*/dev/sd[a-z]"), "запись на raw-устройство"),
    (re.compile(r"(?i)\bformat\s+[A-Za-z]:"), "format диска"),
    # дропперы: скачать-и-выполнить
    (re.compile(r"(?is)\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(ba)?sh\b"), "curl/wget | sh"),
    (re.compile(r"(?i)\b(Invoke-WebRequest|iwr|curl|wget)\b[^\n]*\|\s*(iex|Invoke-Expression)\b"),
     "download | iex"),
    (re.compile(r"(?i)\b(iex|Invoke-Expression)\s*\("), "Invoke-Expression(...)"),
    # Голый `-e` убран: после включения PowerShell в покрытие он ловил `docker run -e VAR=1`
    # и `git rebase -e` внутри `powershell -Command "…"`. Реальные дропперы пишут -enc/-EncodedCommand.
    (re.compile(r"(?i)\b(powershell|pwsh)(\.exe)?\b[^\n]*[\s\"'/-](enc|encodedcommand)\b"),
     "powershell -EncodedCommand"),
    (re.compile(r"(?i)\bcertutil\b[^\n]*-urlcache"), "certutil дроппер"),
    (re.compile(r"(?i)\bbitsadmin\b[^\n]*/transfer"), "bitsadmin дроппер"),
    # боковой ход на прод
    (re.compile(r"(?i)\btailscale\b[^\n]*\bssh\b"), "tailscale ssh (ход на прод)"),
    (re.compile(r"\b100\.70\.224\.109\b"), "обращение к prod-IP"),
    (re.compile(r"(?i)\bssh\s+root@"), "ssh root@ (привилегир. вход)"),
    # необратимый remote-push
    (re.compile(r"(?i)\bgit\s+push\b[^\n]*?(\s--force(?!-with-lease)\b|\s-f\b)"),
     "git push --force"),
    (re.compile(r"(?i)\bgit\s+push\b[^\n]*--mirror"), "git push --mirror"),
    (re.compile(r"(?i)\bDROP\s+DATABASE\b"), "DROP DATABASE"),
]

# ── STRICT: добавляется для удалённых/headless контекстов ────────────────────────
_STRICT_BASH = [
    (re.compile(r"(?i)\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    # ⚠ Альтернативу ОБЯЗАТЕЛЬНО держать в группе: без скобок `|` связывается на верхнем
    # уровне и правая ветка `-\w*d\w*f\b` матчит любой флаг где угодно — под STRICT это
    # блокировало `ruff check --diff`, `tar -xdf`, `docker build -df` как «git clean -fd».
    (re.compile(r"(?i)\bgit\s+clean\s+-(?:\w*f\w*d|\w*d\w*f)\b"), "git clean -fd"),
    (re.compile(r"(?i)\bdocker\s+compose\b[^\n]*\bdown\b[^\n]*-v\b"), "docker compose down -v"),
    (re.compile(r"(?i)\bdocker\s+volume\s+rm\b"), "docker volume rm"),
    (re.compile(r"(?i)\bdocker\s+system\s+prune\b"), "docker system prune"),
    (re.compile(r"(?i)\bnpm\s+publish\b"), "npm publish"),
    (re.compile(r"(?i)\b(DROP\s+TABLE|TRUNCATE)\b"), "DROP TABLE / TRUNCATE"),
    (re.compile(r"(?i)\brm\s+(-\w*r\w*f|-\w*f\w*r)\b"), "rm -rf (строгий тир)"),
    # PowerShell-эквиваленты того же класса. Без них STRICT-тир на Windows покрывал только
    # bash-синтаксис: `rm -rf ./build` блокировался, а `Remove-Item -Recurse -Force .\build`
    # — нет, хотя воркеры под bypassPermissions работают именно в PowerShell.
    (re.compile(r"(?i)\b(Remove-Item|ri)\b[^\n|;]*-Recurse\b[^\n|;]*-Force\b"),
     "Remove-Item -Recurse -Force (строгий тир)"),
    (re.compile(r"(?i)\b(Remove-Item|ri)\b[^\n|;]*-Force\b[^\n|;]*-Recurse\b"),
     "Remove-Item -Force -Recurse (строгий тир)"),
    (re.compile(r"(?i)\brd\s+/s\b[^\n]*/q|\brd\s+/q\b[^\n]*/s"), "rd /s /q (строгий тир)"),
]

# ── Самозащита для Bash: глагол ЗАПИСИ/удаления, целящий в гард/settings.json ─────
# Узко: глагол-записи стоит ПЕРЕД именем файла (между ними нет |;&), поэтому простое
# упоминание имени в commit-сообщении, git log, cat/wc/ls НЕ ловится. Список глаголов
# и набор файлов тот же, что был, — меняется только точность (не трогаем Move/Copy,
# чтобы не закрывать легитимный путь обслуживания самого гарда).
_GUARD_WRITE = re.compile(
    r"""(?ix)
    (?: >>? | \btee\b | \bSet-Content\b | \bOut-File\b | \bAdd-Content\b
      | \bsed\s+-i | \brm\b | \bdel\b | \bRemove-Item\b | \bri\b )
    [^|;&\n]*?
    ( claude_guard_hook\.py
      | [\\/]?\.claude[\\/]settings\.json
      | \.claude\.json )
    """,
)

# ── Чтение/выгрузка секрета: три независимых правила ─────────────────────────────
# Было ОДНО правило: «в строке есть .env» И «в строке есть read-глагол» — без связи между
# ними. Оно ловило рутину: `| head -N` Claude дописывает почти в каждую команду, а `-type f`
# у find совпадал с глаголом `type`; блокировались `grep ... .env | head`,
# `git ls-files | grep "^\.env" | head`, проверка .gitignore и текст commit-сообщения.
# Стало три правила, каждое со своим якорем:
#   _SECRET_READ — глагол чтения ЦЕЛИТ в путь (как в _GUARD_WRITE);
#   _SECRET_PIPE — секрет слева от пайпа, аплоадер справа (`tar cf - .env | base64`);
#   _SECRET_GREP — чтение ВНУТРИ секрета (`grep TOKEN .env`), но не поиск .env как паттерна.
# Слова-омонимы (type/more/less) НЕ удалены — в PowerShell `type` реально читает файл;
# они обезврежены lookbehind'ом `(?<![-\w])`, который отсекает формы вида `-type`/`--tail`.
_SECRET_PATH = r"""
    ( (^|[\\/\s'"=@(])\.env(?!\.(example|sample|template|dist))(\b|['"]|$)
      | id_rsa | id_ed25519 | id_ecdsa
      | [\\/]\.ssh(?![\w.])
      | \.claude\.json
      | service[-_]account | [-_]credentials\.json
      | \.(pem|p12|pfx)(\b|['"]|$) )
"""

# Тот же список путей — для файловых инструментов (Read/Edit/Write). ОДНА декларация:
# раньше здесь и у шапки лежали две дословные копии, и любой новый секрет рисковал
# попасть только в одну из них.
_SECRET_FILE = re.compile(r"(?ix)" + _SECRET_PATH)

_SECRET_READ = re.compile(
    r"""(?ix)
    (?: (?<![-\w])                   # не флаг: `find -type f`, `Get-Content -Tail 5`
        (?: cat | Get-Content | gc | type | more | less | head | tail
          | xxd | od | strings | awk | sed
          | scp | curl | wget | Invoke-RestMethod | irm | base64 | openssl )\b
      | \[IO\.File\]::Read\w* )      # PowerShell-форма чтения файла целиком
    [^;&\n]*?                        # путь идёт ПОСЛЕ глагола; пайп разрешён — он и есть
    """ + _SECRET_PATH,              # канал выгрузки (`cat .env | curl -T -`)
)

# Схема «секрет слева, выгрузка справа от пайпа»: глагол чтения может быть любым
# (`tar cf - .env | base64`), поэтому здесь якорь — сам пайп и аплоадер.
_SECRET_PIPE = re.compile(
    r"""(?ix) """ + _SECRET_PATH + r"""
    [^\n]*\|[^\n]*
    (?<![-\w])(?: curl | wget | nc | ncat | base64 | openssl | irm
                | Invoke-RestMethod | Invoke-WebRequest | iwr | scp )\b
    """,
)

# grep-семейство: блокируем ЧТЕНИЕ ВНУТРИ секрета (`grep AIOS_AUTH_MODE .env` печатает
# значение), но НЕ поиск .env КАК ПАТТЕРНА в другом файле (`grep -E "^\.env" .gitignore`,
# `git ls-files | grep "^\.env"` — рутина). Различаем по одному признаку: путь-операнд
# отделён пробелом, а паттерн внутри кавычек стоит после `^`/`\` и пробелом не предваряется.
_SECRET_GREP = re.compile(
    r"""(?ix)
    (?<![-\w])(?: grep | egrep | fgrep | rg | Select-String | sls | findstr )\b
    [^;&\n]*?\s
    \.env(?!\.(example|sample|template|dist))(\b|$)
    """,
)
# ⚠ Замер по coordination/.tg-guard-denied.jsonl (окно 2026-06-14…2026-07-24): 97 блокировок
# всего, 36 из них — правило секрета. Прежняя редакция («.env где-то в строке» И «read-глагол
# где-то в строке») ловила рутину: `find -type f`, `… .env | head`, текст commit-сообщения.
# Нынешняя связка (глагол→путь + пайп-выгрузка + grep-внутрь) сохраняет настоящие срабатывания
# и снимает эту рутину. Не «упрощай» её обратно в один общий поиск подстроки.

# Текстовые участки команды, которые НЕ являются исполняемым кодом: тело heredoc и
# сообщение коммита. Раньше `git commit -m "... curl | sh ..."` блокировался как дроппер
# (реальный инцидент 2026-06-14: сессия трижды не смогла закоммитить описание гарда).
#
# ⚠ ДВА КАПКАНА, на которых первая версия этой функции пробила гард насквозь (адверсариальный
# аудит 25.07.2026 — воспроизведено запуском bash):
#  1. Ленивый `.*?` до `\1` без якоря строки: если слово-терминатор встречается ДВАЖДЫ,
#     вырезалось всё между первым и вторым вхождением, а bash закрывает heredoc ПЕРВЫМ —
#     строки между ними исполняются. `cat <<EOF\nEOF\nrm -rf /\nEOF` уходил из-под всех правил.
#     Лечение: терминатор привязан к началу строки (re.M), прыжок через него запрещён.
#  2. Внутри двойных кавычек `-m "…"` bash выполняет подстановку `$(…)` и обратные кавычки.
#     Вырезая сообщение целиком, мы прятали исполняемый код: `git commit -m "$(cat .env)"`.
#     Лечение: сообщение вырезается ТОЛЬКО если внутри нет `$(`, `${` и обратных кавычек.
_HEREDOC = re.compile(
    r"<<-?[ \t]*(['\"]?)(\w+)\1[^\n]*\n(?:(?![ \t]*\2[ \t]*$).)*?^[ \t]*\2[ \t]*$",
    re.S | re.M,
)
_COMMIT_MSG = re.compile(
    r"(?i)(-m|--message)\s+(['\"])((?:(?!\2|\$\(|\$\{|`).)*)\2", re.S,
)


def _strip_text_args(command: str) -> str:
    """Убрать из команды заведомо НЕисполняемые текстовые куски перед матчингом правил.

    Всё, что может быть исполнено (подстановки в сообщении коммита, строки за первым
    терминатором heredoc), обязано остаться в строке — иначе гард сам себя обходит.
    """
    command = _HEREDOC.sub(" <<HEREDOC>> ", command)
    return _COMMIT_MSG.sub(r"\1 <MSG>", command)


# ── Напоминание (НЕ блок): на `git commit` подсказать стандарт ревью ──────────────
_GIT_COMMIT = re.compile(r"(?i)\bgit\s+commit\b")
_GIT_COMMIT_NOOP = re.compile(r"(?i)\bgit\s+commit\b[^\n]*\s-(-help|h)\b")
_REVIEW_REMINDER = (
    "Перед этим коммитом — стандарт ревью (CLAUDE.md): если в этой задаче ещё не "
    "прогонял, запусти /code-review (баги/корректность), затем /simplify (чистка по "
    "«лестнице лени»). Это НЕблокирующее напоминание — коммит выполнится в любом случае."
)


def _remind_review(command: str) -> None:
    """На `git commit` впрыснуть в контекст Claude напоминание про ревью. Не блокирует."""
    if not _GIT_COMMIT.search(command) or _GIT_COMMIT_NOOP.search(command):
        return
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "additionalContext": _REVIEW_REMINDER}}
    print(json.dumps(out, ensure_ascii=False))


def _deny(reason: str, tool: str, detail: str) -> None:
    rec = {"ts": time.time(), "tool": tool, "reason": reason,
           "strict": STRICT, "detail": detail[:500]}
    try:
        DENY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DENY_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    print(f"[guard] ЗАБЛОКИРОВАНО: {reason}. "
          f"Это правило безопасности (claude_guard_hook.py). "
          f"НЕ обходи его: не переписывай команду, не дроби на части, не прячь в heredoc "
          f"или подстановку — это считается нарушением, а не решением. "
          f"Если действие действительно нужно — доложи координатору строкой "
          f"`КООРД: <BLOCKED> <полоса> — гард: {reason}` (статус подставь без скобок) и продолжай остальную работу без "
          f"этого шага. Разрешение даёт только оператор, вручную.",
          file=sys.stderr)
    sys.exit(2)


def _check_bash(command: str, tool: str = "Bash") -> None:
    """Проверить строку команды шелла (Bash или PowerShell). Матчим по очищенной
    от текстовых аргументов строке, но в лог/причину отдаём оригинал."""
    probe = _strip_text_args(command)
    rules = _BASE_BASH + (_STRICT_BASH if STRICT else [])
    for rx, label in rules:
        if rx.search(probe):
            _deny(label, tool, command)
    # секреты: только глаголы ЧТЕНИЯ/выгрузки, целящие в путь (не запись в .env).
    # `cp .env.example .env` — легитимная настройка, не эксфильтрация, поэтому cp/tar нет.
    if _SECRET_READ.search(probe) or _SECRET_PIPE.search(probe) or _SECRET_GREP.search(probe):
        _deny("чтение/выгрузка секрета (.env/.ssh/ключи/.claude.json)", tool, command)
    # Самозащита: только реальная запись/удаление, целящая в гард/settings.json.
    if _GUARD_WRITE.search(probe):
        _deny("запись/удаление в сам гард или settings.json", tool, command)


def _check_file(tool: str, path: str) -> None:
    if not path:
        return
    if _SECRET_FILE.search(path):
        _deny(f"{tool} к секретному файлу ({path})", tool, path)
    if _GUARD_FILES.search(path) and tool not in ("Read",):
        _deny(f"{tool} правит сам гард / settings.json ({path})", tool, path)


def main() -> int:
    # Кодировка — до любого ввода/вывода: гард не имеет права зависеть от PYTHONUTF8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        return 0  # не смогли разобрать вход — не мешаем (fail-open: гард не ломает работу)

    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        return 0

    # PowerShell — штатный шелл на Windows и тоже отдаёт команду в поле `command`.
    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        if cmd:
            _check_bash(cmd, tool)
            _remind_review(cmd)
    elif tool in ("Edit", "Write", "MultiEdit", "Read"):
        _check_file(tool, ti.get("file_path") or "")
    elif tool == "NotebookEdit":
        _check_file(tool, ti.get("notebook_path") or "")
    return 0  # разрешено


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise  # _deny() уходит через SystemExit(2) — это блокировка, её не глотаем
    except Exception:
        # fail-open: гард не должен ломать работу собственным багом. Молчаливое
        # исключение здесь опаснее пропущенной команды — но крах хука не защищает ни от чего.
        raise SystemExit(0)
