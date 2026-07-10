#!/usr/bin/env python3
"""tg_digest.py — ежедневный дайджест в Telegram: дашборд флота + готовность + статус CI.

Гонит fleet_dashboard.py (в его шапке — CI(main)) и scripts/readiness.py, собирает
компактное сообщение и шлёт в Telegram ботом из tg_bridge (TG_BOT_TOKEN/TG_CHAT_ID из
.env в корне). Для ежедневного запуска по расписанию (Windows Task Scheduler, 08:00).

  python tg_digest.py            собрать и отправить
  python tg_digest.py --dry-run  напечатать сообщение, НЕ отправляя (для проверки)

Креды (env или .env): TG_BOT_TOKEN, TG_CHAT_ID, опц. TG_PROXY, TG_DIGEST_TOPIC (id топика).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
TG_API = "https://api.telegram.org"
MAXLEN = 3800


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _load_dotenv() -> None:
    """Подтянуть TG_* из .env (как tg_bridge), не трогая остальное окружение."""
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key.startswith("TG_") and key not in os.environ:
            os.environ[key] = val.strip().strip('"').strip("'")


def _run(args: list[str]) -> str:
    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
    try:
        r = subprocess.run([py, *args], cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
        return (r.stdout or "").rstrip()
    except Exception as e:  # noqa: BLE001 — дайджест не должен падать из-за под-команды
        return f"(ошибка {' '.join(args)}: {e})"


def _review_status() -> str:
    """Строка о ночном ревью 23:59 из last-run.log (провал должен быть виден утром)."""
    log = ROOT / "coordination" / ".daily-review-data" / "last-run.log"
    try:
        line = log.read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError):
        return "⚠️ ночное ревью: лога нет (не запускалось или упало до записи)"
    return ("🌙 " if " OK " in line else "⚠️ ") + f"ночное ревью: {line}"


def _compose() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fleet = _run(["fleet_dashboard.py"])
    readi = _run(["scripts/readiness.py"])
    body = (f"\U0001F4CA Дайджест {stamp}\n\n"
            f"{_review_status()}\n\n"
            f"— Флот + CI —\n{fleet}\n\n"
            f"— Готовность модулей —\n{readi}")
    if len(body) > MAXLEN:
        body = body[:MAXLEN] + "\n…(обрезано)"
    return body


def _send(text: str) -> int:
    import requests  # лениво: не нужен для --dry-run
    _load_dotenv()
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        print("нет TG_BOT_TOKEN/TG_CHAT_ID (.env) — отправить не могу", file=sys.stderr)
        return 1
    params = {"chat_id": chat, "text": text}
    topic = os.environ.get("TG_DIGEST_TOPIC", "").strip()
    if topic:
        params["message_thread_id"] = topic
    proxy = os.environ.get("TG_PROXY", "").strip()
    proxies = {"https": proxy, "http": proxy} if proxy else None
    try:
        r = requests.post(f"{TG_API}/bot{token}/sendMessage", data=params,
                          proxies=proxies, timeout=30)
        ok = r.status_code == 200 and r.json().get("ok")
    except Exception as e:  # noqa: BLE001
        print(f"ошибка отправки: {e}", file=sys.stderr)
        return 1
    print("дайджест отправлен ✓" if ok else f"telegram отказал: {r.text[:200]}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argv = argv if argv is not None else sys.argv[1:]
    text = _compose()
    if "--dry-run" in argv:
        print(text)
        return 0
    return _send(text)


if __name__ == "__main__":
    raise SystemExit(main())
