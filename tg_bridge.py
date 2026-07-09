#!/usr/bin/env python3
"""tg_bridge.py — Telegram-мост к оркестратору воркеров (spawn_workers.py).

Идея: вести параллельные Claude-воркеры и видеть уведомления живых VSCode-чатов
прямо из Telegram, не путая «чаты» между собой. Один топик форум-группы = один
воркер; отдельный топик «💬 VSCode» = уведомления интерактивных сессий.

ЧТО ДЕЛАЕТ
  A. Оркестратор ↔ Telegram (двусторонне):
     - опрашивает состояния воркеров (через внутренние функции spawn_workers.py,
       состояния 1-в-1: LIVE/IDLE/STALE/COMPLETE/NEEDS-ANSWER/BLOCKED);
     - на смене значимого состояния шлёт сообщение в топик воркера;
     - твой текст в топике воркера = ответ воркеру (spawn_workers respond):
       стоп → дописать ответ в first-msg → пере-spawn в том же worktree;
     - команды /status /tail /spawn /integrate /cleanup /stop /respond.
  C. Уведомления живых VSCode-чатов (только пуши):
     - hook Notification пишет события в coordination/.tg-events.jsonl
       (см. tg_notify_hook.py), бот их пересылает в топик «💬 VSCode».

ЗАПУСК
  & ".\\.venv\\Scripts\\python.exe" tg_bridge.py            # основной режим
  & ".\\.venv\\Scripts\\python.exe" tg_bridge.py --probe    # узнать chat_id группы

КОНФИГ (env или .env в корне репо):
  TG_BOT_TOKEN        токен бота от @BotFather (обязательно)
  TG_CHAT_ID          id форум-группы (отрицательный, напр. -1001234567890)
  TG_ALLOWED_USER_IDS (опц.) список твоих user id через запятую — фильтр доступа
  TG_POLL_SEC         (опц.) период опроса состояний, по умолчанию 8
  TG_FORUM            (опц.) 1=форум-топики (деф.), 0=один чат с префиксами

Зависимостей сверх проекта нет: httpx уже в requirements.txt.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spawn_workers as sw  # noqa: E402  (внутренности оркестратора = наша библиотека)
import tg_sessions as tgs  # noqa: E402  (вариант B: продолжение твоих сессий)

# ─── конфиг ────────────────────────────────────────────────────────────────────

STATE_FILE = sw.COORD_DIR / ".tg-bridge-state.json"
EVENTS_FILE = sw.COORD_DIR / ".tg-events.jsonl"   # сюда пишет tg_notify_hook.py
TG_MSG_LIMIT = 3900                                # запас от лимита Telegram 4096

# Состояния, о которых вообще стоит уведомлять (остальные — тихо обновляем).
INTERESTING = {"🟠 NEEDS-ANSWER", "✅ COMPLETE", "❌ BLOCKED", "🔴 STALE"}


def _load_dotenv() -> None:
    """Подтянуть TG_* из .env в корне репо, не трогая остальное окружение."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.startswith("TG_") and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")
    except OSError:
        pass


class Config:
    def __init__(self) -> None:
        _load_dotenv()
        # Алфавит токена — только [A-Za-z0-9:_-]. Чистим от случайного мусора
        # (BOM, zero-width, остаток плейсхолдера), чтобы кривая вставка не ломала.
        self.token = re.sub(r"[^A-Za-z0-9:_-]", "", os.environ.get("TG_BOT_TOKEN", ""))
        self.chat_id = os.environ.get("TG_CHAT_ID", "").strip()
        self.poll_sec = float(os.environ.get("TG_POLL_SEC", "8"))
        self.forum = os.environ.get("TG_FORUM", "1").strip() != "0"
        ids = os.environ.get("TG_ALLOWED_USER_IDS", "").strip()
        self.allowed_users = {int(x) for x in ids.replace(" ", "").split(",") if x.isdigit()}
        # Прокси на случай, если ISP режет api.telegram.org (напр. http://127.0.0.1:1080
        # или socks5://user:pass@host:port). Пусто = напрямую.
        self.proxy = os.environ.get("TG_PROXY", "").strip() or None


# ─── состояние моста (топики, оффсеты) ──────────────────────────────────────────


def _load_bridge_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_bridge_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        print(f"[tg] warn: не сохранил state: {e}", file=sys.stderr)


# ─── Telegram API (httpx, по-вызову — потокобезопасно) ─────────────────────────


class Telegram:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.base = f"https://api.telegram.org/bot{cfg.token}"
        self.proxy = cfg.proxy

    def call(self, method: str, http_timeout: float = 35.0, retries: int = 2,
             **params) -> dict | None:
        # http_timeout — таймаут httpx-клиента; Telegram-long-poll задаётся
        # отдельным params["timeout"] и всегда должен быть меньше http_timeout.
        # retries сглаживают прерывистую сеть (ISP-троттлинг Telegram).
        last = None
        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=http_timeout, proxy=self.proxy) as c:
                    r = c.post(f"{self.base}/{method}", json=params)
                    data = r.json()
                if not data.get("ok"):
                    print(f"[tg] {method} -> {data.get('description')}", file=sys.stderr)
                    return None
                return data.get("result")
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                last = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        print(f"[tg] {method} сеть не ответила ({retries + 1} попыток): {last}",
              file=sys.stderr)
        return None

    def send(self, text: str, thread_id: int | None = None) -> dict | None:
        if len(text) > TG_MSG_LIMIT:
            text = text[:TG_MSG_LIMIT] + "\n…(обрезано)"
        params: dict = {"chat_id": self.cfg.chat_id, "text": text,
                        "disable_web_page_preview": True}
        if thread_id is not None:
            params["message_thread_id"] = thread_id
        return self.call("sendMessage", **params)

    def create_topic(self, name: str) -> int | None:
        res = self.call("createForumTopic", chat_id=self.cfg.chat_id, name=name)
        if res and "message_thread_id" in res:
            return int(res["message_thread_id"])
        return None


# ─── мост ───────────────────────────────────────────────────────────────────────


class Bridge:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.tg = Telegram(cfg)
        st = _load_bridge_state()
        self.topics: dict[str, int] = st.get("topics", {})          # worker -> thread_id
        self.last_state: dict[str, str] = st.get("last_state", {})  # worker -> state
        self.msg_to_worker: dict[str, str] = st.get("msg_to_worker", {})  # msg_id -> worker (fallback)
        self.offset: int = int(st.get("update_offset", 0))          # getUpdates offset
        self.events_pos: int = int(st.get("events_pos", 0))         # байт-оффсет .tg-events.jsonl
        self.c_topic: int | None = st.get("c_topic")                # топик «💬 VSCode»
        self.forum = cfg.forum
        # вариант B: топик -> привязанная сессия Claude Code
        self.sessions: dict[str, dict] = st.get("sessions", {})     # thread_id(str) -> {id,cwd,project,started}
        self.busy: set[str] = set()                                 # session id'ы, занятые ходом
        self.last_listing: list[dict] = []                          # последний /sessions для /attach по индексу

    def save(self) -> None:
        _save_bridge_state({
            "topics": self.topics,
            "last_state": self.last_state,
            "msg_to_worker": dict(list(self.msg_to_worker.items())[-200:]),
            "update_offset": self.offset,
            "events_pos": self.events_pos,
            "c_topic": self.c_topic,
            "sessions": self.sessions,
        })

    # — топики —

    def topic_for(self, name: str) -> int | None:
        """thread_id топика воркера; создаёт при первом обращении. None = General."""
        if not self.forum:
            return None
        if name in self.topics:
            return self.topics[name]
        tid = self.tg.create_topic(f"⚙ {name}")
        if tid is None:
            # Не форум / бот не админ — разово деградируем в один чат.
            print("[tg] createForumTopic не сработал — режим одного чата с префиксами.",
                  file=sys.stderr)
            self.forum = False
            return None
        self.topics[name] = tid
        self.save()
        return tid

    def c_topic_id(self) -> int | None:
        if not self.forum:
            return None
        if self.c_topic is not None:
            return self.c_topic
        tid = self.tg.create_topic("💬 VSCode")
        if tid is not None:
            self.c_topic = tid
            self.save()
        return tid

    def notify_worker(self, name: str, text: str) -> None:
        tid = self.topic_for(name)
        if tid is not None:
            self.tg.send(text, tid)
        else:
            res = self.tg.send(f"[{name}]\n{text}")
            if res and "message_id" in res:        # для ответа реплаем в режиме одного чата
                self.msg_to_worker[str(res["message_id"])] = name

    # — A: опрос состояний воркеров —

    def _status_tail(self, name: str, limit: int = 1200) -> str:
        """Хвост status-файла воркера — чтобы показать текст вопроса/блокера."""
        wt = sw._worktree_path(name)
        for cand in (wt / "coordination" / f"{name}-status.md",
                     sw.COORD_DIR / f"{name}-status.md"):
            if cand.is_file():
                try:
                    txt = cand.read_text(encoding="utf-8", errors="replace").strip()
                    return txt[-limit:]
                except OSError:
                    pass
        return ""

    def poll_workers(self) -> None:
        for name in sw._list_available():
            try:
                row = sw._status_row(name)
            except Exception as e:                  # опрос не должен ронять бот
                print(f"[tg] status {name}: {e}", file=sys.stderr)
                continue
            state = row["state"]
            prev = self.last_state.get(name)
            if state == prev:
                continue
            self.last_state[name] = state
            if state not in INTERESTING:             # LIVE/IDLE/NO-TRANSCRIPT/DEAD — тихо
                self.save()
                continue
            self.notify_worker(name, self._format_change(name, state))
            self.save()

    def _format_change(self, name: str, state: str) -> str:
        if state == "🟠 NEEDS-ANSWER":
            tail = self._status_tail(name)
            return (f"🟠 {name}: нужен твой ответ.\n\n"
                    f"…{tail}\n\n"
                    f"➡ Ответь сообщением прямо в этот топик — передам воркеру и "
                    f"перезапущу его. (или /respond {name} <текст>)")
        if state == "✅ COMPLETE":
            return (f"✅ {name}: готов к интеграции.\n"
                    f"➡ /integrate {name}  (затем /cleanup {name})")
        if state == "❌ BLOCKED":
            return f"❌ {name}: заблокирован.\n\n…{self._status_tail(name)}"
        if state == "🔴 STALE":
            return (f"🔴 {name}: завис (>30м без активности).\n"
                    f"➡ /tail {name}  ·  /stop {name}  ·  /respond {name} <текст>")
        return f"{state} {name}"

    # — C: уведомления живых VSCode-чатов —

    def drain_events(self) -> None:
        if not EVENTS_FILE.is_file():
            return
        try:
            size = EVENTS_FILE.stat().st_size
            if size < self.events_pos:               # файл усечён/пересоздан
                self.events_pos = 0
            if size == self.events_pos:
                return
            with EVENTS_FILE.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self.events_pos)
                new = f.readlines()
                self.events_pos = f.tell()
        except OSError as e:
            print(f"[tg] чтение событий: {e}", file=sys.stderr)
            return
        tid = self.c_topic_id()
        for line in new:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            proj = Path(ev.get("cwd", "")).name or "?"
            sess = ev.get("session", "")
            msg = (ev.get("message") or "").strip()
            text = f"🔔 {proj} ждёт ввода"
            if msg:
                text += f": {msg}"
            if sess:
                text += f"\n(сессия {sess})"
            self.tg.send(text, tid)
        self.save()

    # — inbound: команды и ответы —

    def process_updates(self) -> None:
        wait = int(self.cfg.poll_sec)
        updates = self.tg.call("getUpdates", http_timeout=wait + 25,
                               offset=self.offset + 1, timeout=wait)
        if not updates:
            return
        for upd in updates:
            self.offset = max(self.offset, int(upd.get("update_id", 0)))
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            self._handle_message(msg)
        self.save()

    def _handle_message(self, msg: dict) -> None:
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if self.cfg.chat_id and chat_id != self.cfg.chat_id:
            return                                    # чужой чат — игнор
        user_id = int(msg.get("from", {}).get("id", 0))
        if self.cfg.allowed_users and user_id not in self.cfg.allowed_users:
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        thread_id = msg.get("message_thread_id")

        if text.startswith("/"):
            self._handle_command(text, thread_id)
            return

        # обычный текст → по контексту топика: воркер (A) или сессия (B)
        worker = self._worker_from_context(thread_id, msg)
        if worker:
            self._respond(worker, text, thread_id)
            return
        sess_key = self._session_key(thread_id)
        if sess_key:
            self._session_turn(sess_key, text, thread_id)
            return
        self.tg.send(
            "Топик ни к воркеру, ни к сессии не привязан.\n"
            "• воркеру: пиши в его топик или /respond <имя> <текст>\n"
            "• сессии (вариант B): /sessions → /attach <№|id>\n"
            "/help — все команды.",
            thread_id,
        )

    def _worker_from_context(self, thread_id, msg) -> str | None:
        if thread_id is not None:
            for name, tid in self.topics.items():
                if tid == thread_id:
                    return name
        reply = msg.get("reply_to_message")            # fallback: реплай на уведомление
        if reply:
            return self.msg_to_worker.get(str(reply.get("message_id")))
        return None

    # — команды —

    def _handle_command(self, text: str, thread_id) -> None:
        parts = text.split()
        cmd = parts[0].lstrip("/").split("@", 1)[0].lower()
        args = parts[1:]

        if cmd in ("help", "start"):
            self.tg.send(self._help_text(), thread_id)
        elif cmd in ("status", "st"):
            self._send_capture(lambda: sw.cmd_status(args), thread_id)
        elif cmd in ("workers", "list", "ls"):
            self._send_capture(lambda: self._workers_brief(), thread_id)
        elif cmd == "tail":
            if not args:
                self.tg.send("использование: /tail <имя> [n]", thread_id)
                return
            n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
            self._send_capture(lambda: sw.cmd_tail(args[0], n), thread_id)
        elif cmd == "respond":
            if len(args) < 2:
                self.tg.send("использование: /respond <имя> <текст>", thread_id)
                return
            self._respond(args[0], " ".join(args[1:]), thread_id)
        elif cmd == "spawn":
            if not args:
                self.tg.send("использование: /spawn <имя> [имя…]", thread_id)
                return
            self._bg(thread_id, f"spawn {' '.join(args)}",
                     lambda: sw.cmd_spawn(args, dry_run=False,
                                          max_concurrent=sw.DEFAULT_MAX_CONCURRENT,
                                          allow_over_cap=False,
                                          perm=sw.DEFAULT_PERMISSION_MODE,
                                          model=sw.DEFAULT_WORKER_MODEL))
        elif cmd == "integrate":
            if not args:
                self.tg.send("использование: /integrate <имя>", thread_id)
                return
            self._bg(thread_id, f"integrate {args[0]}",
                     lambda: sw.cmd_integrate(args[0], dry_run=False))
        elif cmd == "cleanup":
            if not args:
                self.tg.send("использование: /cleanup <имя>", thread_id)
                return
            self._bg(thread_id, f"cleanup {args[0]}",
                     lambda: sw.cmd_cleanup([args[0]], dry_run=False))
        elif cmd == "stop":
            if not args:
                self.tg.send("использование: /stop <имя>", thread_id)
                return
            self._send_capture(lambda: sw.cmd_stop(args[0]), thread_id)
        # ─── вариант B: сессии ───
        elif cmd == "sessions":
            self._cmd_sessions(thread_id)
        elif cmd == "attach":
            if not args:
                self.tg.send("использование: /attach <№ из /sessions | id> [имя]", thread_id)
                return
            self._cmd_attach(args[0], " ".join(args[1:]).strip(), thread_id)
        elif cmd == "new":
            self._cmd_new(" ".join(args) if args else "", thread_id)
        elif cmd in ("detach",):
            self._cmd_detach(thread_id)
        elif cmd in ("attached", "bound"):
            self._cmd_attached(thread_id)
        else:
            self.tg.send(f"неизвестная команда: /{cmd}\n{self._help_text()}", thread_id)

    def _respond(self, name: str, answer: str, thread_id) -> None:
        if name not in sw._list_available():
            self.tg.send(f"нет такого воркера: {name}", thread_id)
            return
        self.tg.send(f"↩ передаю воркеру {name} и перезапускаю…", thread_id)
        self._bg(thread_id, f"respond {name}",
                 lambda: sw.cmd_respond(name, answer, dry_run=False,
                                        perm=sw.DEFAULT_PERMISSION_MODE,
                                        model=sw.DEFAULT_WORKER_MODEL))

    # ─── вариант B: продолжение твоих сессий Claude Code ───

    def _session_key(self, thread_id) -> str | None:
        """Ключ привязанной сессии для топика (или None)."""
        key = str(thread_id) if thread_id is not None else "general"
        return key if key in self.sessions else None

    def _session_label(self, sess: dict) -> str:
        """Человекочитаемая метка сессии: «имя · #id8»."""
        lbl = (sess.get("label") or sess.get("project") or "session").strip()
        sid = sess.get("id")
        return f"{lbl} · #{sid[:8]}" if sid else lbl

    def _cmd_sessions(self, thread_id) -> None:
        items = tgs.list_sessions(limit=12)
        self.last_listing = items
        if not items:
            self.tg.send("(нет недавних сессий Claude Code)", thread_id)
            return
        attached = {s.get("id") for s in self.sessions.values() if s.get("id")}
        lines = ["Недавние сессии (свежие сверху).",
                 "Привязать: /attach <№> [имя]   ·   например  /attach 1 Закупки", ""]
        for i, s in enumerate(items, 1):
            snippet = s["last"] or s["first"] or "—"
            mark = "  ✅уже привязана" if s["id"] in attached else ""
            lines.append(f"{i}. [{s['project']}] #{s['id'][:8]}{mark}\n   {snippet}")
        self.tg.send("\n".join(lines), thread_id)

    def _resolve_session(self, arg: str) -> dict | None:
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(self.last_listing):
                return self.last_listing[idx]
            return None
        pool = self.last_listing or tgs.list_sessions(limit=40)
        for s in pool:
            if s["id"].startswith(arg):
                return s
        return None

    def _send_session_card(self, sess: dict, target, new: bool = False) -> None:
        """Карточка-закреп в топике: что это за сессия (видно сразу при входе)."""
        guard = "вкл" if tgs.B_GUARD else "выкл"
        head = "🆕 Новая сессия" if new else "🧠 Сессия привязана"
        idline = sess.get("id") or "(будет создан при первом сообщении)"
        card = (
            f"{head} к этому топику\n"
            f"• имя:    {sess.get('label') or sess.get('project')}\n"
            f"• проект: {sess.get('project')}\n"
            f"• папка:  {sess.get('cwd')}\n"
            f"• id:     {idline}\n"
            f"• модель: {tgs.B_MODEL} · режим: {tgs.B_PERMISSION_MODE} · гард: {guard}\n\n"
            f"Пиши сюда обычным текстом — продолжу ТУ ЖЕ беседу (подписка). /detach — отвязать."
        )
        m = self.tg.send(card, target)
        if m and m.get("message_id"):                # закрепим, чтобы шапка топика = эта карточка
            self.tg.call("pinChatMessage", chat_id=self.cfg.chat_id,
                         message_id=m["message_id"], disable_notification=True)

    def _cmd_attach(self, arg: str, name: str, thread_id) -> None:
        sess = self._resolve_session(arg)
        if not sess:
            self.tg.send("не нашёл такую сессию. Сначала /sessions, потом /attach <№>.", thread_id)
            return
        label = (name or sess.get("first") or sess.get("project") or "session").strip()[:40]
        target = thread_id
        if self.forum and target is None:           # в General → отдельный топик
            target = self.tg.create_topic(f"🧠 {label} · #{sess['id'][:8]}"[:120])
        key = str(target) if target is not None else "general"
        self.sessions[key] = {"id": sess["id"], "cwd": sess["cwd"],
                              "project": sess["project"], "label": label, "started": True}
        self.save()
        self._send_session_card(self.sessions[key], target)

    def _cmd_new(self, path: str, thread_id) -> None:
        cwd = path.strip() or str(sw.REPO_ROOT)
        if not Path(cwd).is_dir():
            self.tg.send(f"нет такой папки: {cwd}", thread_id)
            return
        label = f"new:{Path(cwd).name}"
        target = thread_id
        if self.forum and target is None:
            target = self.tg.create_topic(f"🧠 {label}"[:120])
        key = str(target) if target is not None else "general"
        # id сгенерит CLI на первом ходу (new_session=True) — пометим started=False
        self.sessions[key] = {"id": None, "cwd": cwd, "project": Path(cwd).name,
                              "label": label, "started": False}
        self.save()
        self._send_session_card(self.sessions[key], target, new=True)

    def _cmd_detach(self, thread_id) -> None:
        key = self._session_key(thread_id)
        if not key:
            self.tg.send("к этому топику сессия не привязана.", thread_id)
            return
        lbl = self._session_label(self.sessions[key])
        self.sessions.pop(key, None)
        self.save()
        self.tg.send(f"🔌 отвязал сессию ({lbl}) от топика.", thread_id)

    def _cmd_attached(self, thread_id) -> None:
        if not self.sessions:
            self.tg.send("Пока ничего не привязано. /sessions → /attach <№> [имя].", thread_id)
            return
        lines = ["Привязанные сессии:"]
        for key, s in self.sessions.items():
            where = "General" if key == "general" else f"топик {key}"
            lines.append(f"• {where} → 🧠 {self._session_label(s)}  [{s.get('project')}]")
        self.tg.send("\n".join(lines), thread_id)

    def _session_turn(self, key: str, text: str, thread_id) -> None:
        sess = self.sessions[key]
        sid = sess.get("id")
        busy_key = sid or key
        if busy_key in self.busy:
            self.tg.send(f"⏳ 🧠 {self._session_label(sess)}: ещё думаю над прошлым — "
                         f"дождись ответа.", thread_id)
            return
        self.busy.add(busy_key)
        self.tg.send(f"🧠 {self._session_label(sess)}\n💭 думаю…", thread_id)

        def run():
            try:
                if sess.get("started") and sid:
                    r = tgs.run_turn(text, resume_id=sid, cwd=sess.get("cwd"))
                else:
                    r = tgs.run_turn(text, resume_id=sid, cwd=sess.get("cwd"),
                                     new_session=True)
            finally:
                self.busy.discard(busy_key)
            if not r.get("ok"):
                self.tg.send(f"🧠 {self._session_label(sess)} ✗\n"
                             f"⚠ {r.get('error') or 'ошибка хода'}", thread_id)
                return
            # resume не форкает → id стабилен; для /new фиксируем выданный id.
            new_sid = r.get("session_id") or sid
            if new_sid and (new_sid != sid or not sess.get("started")):
                sess["id"] = new_sid
                sess["started"] = True
                self.save()
            hdr = f"🧠 {self._session_label(sess)} ✓"
            foot = []
            if r.get("duration"):
                foot.append(f"⏱ {round(r['duration'] / 1000)}с")
            if r.get("turns"):
                foot.append(f"{r['turns']} шаг.")
            footer = ("\n\n— " + " · ".join(foot)) if foot else ""
            chunks = _chunks(r.get("result") or "(пустой ответ)")
            last = len(chunks) - 1
            for i, ch in enumerate(chunks):
                prefix = hdr + "\n\n" if i == 0 else ""
                suffix = footer if i == last else ""
                self.tg.send(prefix + ch + suffix, thread_id)

        threading.Thread(target=run, daemon=True).start()

    # — выполнение команд с захватом вывода —

    def _send_capture(self, fn, thread_id) -> None:
        out = _capture(fn)
        self.tg.send(out or "(пусто)", thread_id)

    def _bg(self, thread_id, label: str, fn) -> None:
        """Долгая операция (spawn/respond/integrate) — в фоне, чтобы не залипал loop."""
        def run():
            out = _capture(fn)
            self.tg.send(f"▶ {label}\n\n{out or '(готово)'}", thread_id)
        threading.Thread(target=run, daemon=True).start()

    def _workers_brief(self) -> int:
        names = sw._list_available()
        if not names:
            print("(воркеров нет — создай coordination/first-msgs/<name>.md)")
            return 0
        for name in names:
            st = self.last_state.get(name) or sw._status_row(name)["state"]
            print(f"{st}  {name}")
        return 0

    @staticmethod
    def _help_text() -> str:
        return (
            "Команды моста:\n"
            "/status [имя…] — таблица состояний\n"
            "/workers — краткий список воркеров\n"
            "/tail <имя> [n] — хвост транскрипта\n"
            "/spawn <имя…> — запустить воркера(ов)\n"
            "/respond <имя> <текст> — ответить воркеру (или просто текст в его топике)\n"
            "/integrate <имя> — влить ветку в main\n"
            "/cleanup <имя> — убрать worktree+ветку\n"
            "/stop <имя> — остановить воркера\n\n"
            "Вариант B — продолжить свои сессии Claude Code (handoff, подписка):\n"
            "/sessions — список недавних сессий\n"
            "/attach <№|id> [имя] — привязать сессию к топику (имя — чтобы не путать)\n"
            "/new [путь] — новая сессия в папке (деф. — этот репо)\n"
            "/attached — какие топики к каким сессиям привязаны\n"
            "/detach — отвязать сессию\n\n"
            "В топике воркера обычный текст = ответ воркеру.\n"
            "В топике сессии обычный текст = продолжение беседы.\n"
            "Каждый ответ помечен 🧠 имя · #id — видно, к какой сессии он относится."
        )


def _chunks(text: str, size: int = TG_MSG_LIMIT) -> list[str]:
    """Разбить длинный ответ на части под лимит Telegram, по возможности по строкам."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else ["(пусто)"]
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:                 # очень длинная строка — режем жёстко
            out.append((buf + line[:size]).rstrip("\n"))
            buf, line = "", line[size:]
        if len(buf) + len(line) > size:
            out.append(buf.rstrip("\n"))
            buf = line
        else:
            buf += line
    if buf.strip():
        out.append(buf.rstrip("\n"))
    return out


def _capture(fn) -> str:
    """Выполнить fn, перехватив stdout/stderr (cmd_* печатают в stdout)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            fn()
    except Exception as e:
        buf.write(f"\n[ошибка] {e}")
    return buf.getvalue().strip()


# ─── probe / main ───────────────────────────────────────────────────────────────


def _probe(cfg: Config) -> int:
    """Узнать chat_id группы: долго опрашивает getUpdates и печатает, откуда пришло."""
    tg = Telegram(cfg)
    me = tg.call("getMe")
    if not me:
        print("Токен невалиден — проверь TG_BOT_TOKEN.", file=sys.stderr)
        return 1
    print(f"Бот: @{me.get('username')}. Напиши любое сообщение в нужную группу "
          f"(добавь бота в группу и упомяни @{me.get('username')}).")
    print("Жду сообщения… Ctrl+C для выхода.")
    offset = 0
    while True:
        updates = tg.call("getUpdates", http_timeout=60, offset=offset + 1, timeout=30) or []
        for upd in updates:
            offset = max(offset, int(upd.get("update_id", 0)))
            m = upd.get("message") or upd.get("edited_message") or {}
            chat = m.get("chat", {})
            print(f"  chat_id={chat.get('id')}  type={chat.get('type')}  "
                  f"title={chat.get('title')!r}  from={m.get('from', {}).get('id')}  "
                  f"thread={m.get('message_thread_id')}")
            if chat.get("id"):
                print(f"\n→ TG_CHAT_ID={chat.get('id')}  (впиши в .env)")


def _print_usage() -> None:
    print(
        "Usage:\n"
        "  python tg_bridge.py          start the Telegram bridge\n"
        "  python tg_bridge.py --probe  discover a group chat ID\n"
        "  python tg_bridge.py --help   show this help\n\n"
        "Configuration: TG_BOT_TOKEN and TG_CHAT_ID in .env.\n"
        "Details: coordination/TG-BRIDGE.md"
    )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    argv = sys.argv[1:] if argv is None else argv
    if any(arg in {"-h", "--help"} for arg in argv):
        _print_usage()
        return 0
    cfg = Config()
    if not cfg.token:
        print("Нет TG_BOT_TOKEN. Создай бота у @BotFather, впиши токен в .env.\n"
              "См. coordination/TG-BRIDGE.md.", file=sys.stderr)
        return 1
    if "--probe" in argv:
        try:
            return _probe(cfg)
        except KeyboardInterrupt:
            return 0
    if not cfg.chat_id:
        print("Нет TG_CHAT_ID. Запусти: python tg_bridge.py --probe — он подскажет id.",
              file=sys.stderr)
        return 1

    me = None
    for i in range(5):                      # сеть может моргать на старте — не падаем
        me = Telegram(cfg).call("getMe", retries=1)
        if me:
            break
        print(f"[tg] getMe попытка {i + 1}/5 не удалась (сеть?), повтор…", file=sys.stderr)
        time.sleep(2)
    if not me:
        print("[tg] getMe пока не отвечает — возможно ISP режет Telegram. Захожу в цикл "
              "всё равно, буду повторять. Если так и не заработает — задай TG_PROXY в .env.",
              file=sys.stderr)
    who = f"@{me.get('username')}" if me else "(getMe позже)"
    bridge = Bridge(cfg)
    bridge.tg.send("🟢 Мост запущен. /help — список команд.")
    print(f"[tg] мост запущен как {who} → chat {cfg.chat_id}. Ctrl+C для выхода.")

    while True:
        try:
            bridge.process_updates()   # long-poll ~poll_sec — задаёт ритм
            bridge.poll_workers()      # смены состояний воркеров
            bridge.drain_events()      # уведомления VSCode-чатов
        except KeyboardInterrupt:
            print("\n[tg] остановлен.")
            bridge.save()
            return 0
        except Exception as e:         # один сбой не должен ронять мост
            print(f"[tg] loop: {e}", file=sys.stderr)
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
