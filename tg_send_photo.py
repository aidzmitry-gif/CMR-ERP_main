#!/usr/bin/env python3
"""tg_send_photo.py — отправить картинку в Telegram тем же ботом, что и дайджест.

    python tg_send_photo.py <путь-к-png> ["подпись"]

Креды берёт из .env (TG_BOT_TOKEN/TG_CHAT_ID/опц. TG_DIGEST_TOPIC) через загрузчик
tg_digest — отдельных секретов не вводим.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import tg_digest  # переиспользуем _load_dotenv / TG_API

TG_API = tg_digest.TG_API


def main(argv: list[str] | None = None) -> int:
    tg_digest._utf8()
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("укажи путь к картинке", file=sys.stderr)
        return 2
    img = Path(args[0])
    caption = args[1] if len(args) > 1 else ""
    if not img.is_file():
        print(f"нет файла: {img}", file=sys.stderr)
        return 1

    import requests

    tg_digest._load_dotenv()
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        print("нет TG_BOT_TOKEN/TG_CHAT_ID (.env) — отправить не могу", file=sys.stderr)
        return 1
    data = {"chat_id": chat}
    if caption:
        data["caption"] = caption
    topic = os.environ.get("TG_DIGEST_TOPIC", "").strip()
    if topic:
        data["message_thread_id"] = topic
    proxy = os.environ.get("TG_PROXY", "").strip()
    proxies = {"https": proxy, "http": proxy} if proxy else None
    with img.open("rb") as fh:
        try:
            r = requests.post(f"{TG_API}/bot{token}/sendPhoto", data=data,
                              files={"photo": (img.name, fh, "image/png")},
                              proxies=proxies, timeout=60)
            ok = r.status_code == 200 and r.json().get("ok")
        except Exception as e:  # noqa: BLE001
            print(f"ошибка отправки: {e}", file=sys.stderr)
            return 1
    print("картинка отправлена ✓" if ok else f"telegram отказал: {r.text[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
