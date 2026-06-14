#!/usr/bin/env python3
"""claude_guard_hook.py — PreToolUse-гард: жёсткий блок катастрофических действий.

Запускается Claude Code ПЕРЕД каждым вызовом инструмента (Bash/Edit/Write/Read/…),
работает при ЛЮБОМ permission-mode, включая bypassPermissions. Это последний рубеж
против автономных факапов, prompt-injection и «удалённого шелла» через Telegram.

ФИЛОСОФИЯ: allow-by-default. Ничего НЕ спрашивает (для headless «спросить человека»
невозможно — только разрешить/запретить). Молча пропускает всё, КРОМЕ короткого
списка заведомо разрушительного, который ты руками почти никогда не пишешь, — поэтому
обычная работа идёт без трения и без подтверждений.

ДВА УРОВНЯ:
  • BASE (всегда): катастрофа ФС, дропперы (curl|sh), доступ к секретам
    (.env/.ssh/id_rsa/~.claude.json), боковой ход на прод (tailscale ssh / prod-IP),
    git push --force, попытка отключить сам гард.
  • STRICT (только если выставлен env CLAUDE_GUARD_STRICT=1): добавляет «опасное, но
    иногда легитимное в dev» (reset --hard, clean -fdx, docker down -v, DROP TABLE…).
    tg_sessions.py включает STRICT для удалённых B-сессий, твой интерактив — нет.

Блокировка = stderr с причиной + exit 2 (Claude увидит причину и не выполнит вызов).
Разрешение = exit 0 без вывода. Блоки логируются в coordination/.tg-guard-denied.jsonl.

Установка — в ~/.claude/settings.json (глобально, покрывает воркеры/B/интерактив).
Готовый блок — в coordination/TG-BRIDGE.md.
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

# Имя секретных путей: .env (но не .env.example/.sample/.template), приватные ключи,
# токен подписки Claude, сервис-аккаунты. Эти ссылки в shell/файл-инструменте = стоп.
_SECRET_FILE = re.compile(
    r"""(?ix)
    (^|[\\/\s'"=])\.env(?!\.(example|sample|template|dist))(\b|['"]|$)
    | id_rsa | id_ed25519 | id_ecdsa
    | [\\/]\.ssh[\\/] | \.ssh[\\/].*\.(pem|key)?
    | \.claude\.json
    | service[-_]account | [-_]credentials\.json
    | \.(pem|p12|pfx)(\b|['"]|$)
    """,
)

# Защита самого гарда и конфигурации хуков от отключения агентом.
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
    (re.compile(r"(?i)\bpowershell\b[^\n]*\s-(e|enc|encodedcommand)\b"), "powershell -EncodedCommand"),
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
    (re.compile(r"(?i)\bgit\s+clean\s+-\w*f\w*d|-\w*d\w*f\b"), "git clean -fd"),
    (re.compile(r"(?i)\bdocker\s+compose\b[^\n]*\bdown\b[^\n]*-v\b"), "docker compose down -v"),
    (re.compile(r"(?i)\bdocker\s+volume\s+rm\b"), "docker volume rm"),
    (re.compile(r"(?i)\bdocker\s+system\s+prune\b"), "docker system prune"),
    (re.compile(r"(?i)\bnpm\s+publish\b"), "npm publish"),
    (re.compile(r"(?i)\b(DROP\s+TABLE|TRUNCATE)\b"), "DROP TABLE / TRUNCATE"),
    (re.compile(r"(?i)\brm\s+(-\w*r\w*f|-\w*f\w*r)\b"), "rm -rf (строгий тир)"),
]


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
          f"Это правило безопасности (claude_guard_hook.py). Если это действительно "
          f"нужно — выполни вручную в терминале или ослабь правило.",
          file=sys.stderr)
    sys.exit(2)


def _check_bash(command: str) -> None:
    rules = _BASE_BASH + (_STRICT_BASH if STRICT else [])
    for rx, label in rules:
        if rx.search(command):
            _deny(label, "Bash", command)
    # секреты/гард через любые shell-обращения
    # Только глаголы ЧТЕНИЯ/выгрузки секрета (не запись в .env). cp/tar убраны:
    # `cp .env.example .env` — легитимная настройка, не эксфильтрация.
    if _SECRET_FILE.search(command) and re.search(
            r"(?i)\b(cat|type|more|less|head|tail|Get-Content|gc|scp|"
            r"curl|wget|Invoke-RestMethod|irm|base64|openssl)\b", command):
        _deny("чтение/выгрузка секрета (.env/.ssh/ключи/.claude.json)", "Bash", command)
    if _GUARD_FILES.search(command) and re.search(
            r"(?i)(>|>>|Set-Content|Out-File|Add-Content|tee|sed\s+-i|rm|del|Remove-Item)",
            command):
        _deny("попытка изменить/удалить сам гард или settings.json", "Bash", command)


def _check_file(tool: str, path: str) -> None:
    if not path:
        return
    if _SECRET_FILE.search(path):
        _deny(f"{tool} к секретному файлу ({path})", tool, path)
    if _GUARD_FILES.search(path) and tool not in ("Read",):
        _deny(f"{tool} правит сам гард / settings.json ({path})", tool, path)


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # не смогли разобрать вход — не мешаем (fail-open: гард не ломает работу)

    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if not isinstance(ti, dict):
        return 0

    if tool == "Bash":
        cmd = ti.get("command") or ""
        if cmd:
            _check_bash(cmd)
    elif tool in ("Edit", "Write", "MultiEdit", "Read"):
        _check_file(tool, ti.get("file_path") or "")
    elif tool == "NotebookEdit":
        _check_file(tool, ti.get("notebook_path") or "")
    return 0  # разрешено


if __name__ == "__main__":
    raise SystemExit(main())
