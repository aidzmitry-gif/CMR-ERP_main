"""Юнит-тесты уведомления перевозчиков (notify) — выбор канала, текст, отправка."""
from types import SimpleNamespace

from modules.logistics import notify


def test_pick_channel_email():
    assert notify.pick_channel("sales@dpd.by") == "email"


def test_pick_channel_telegram():
    assert notify.pick_channel("@autolight") == "telegram"
    assert notify.pick_channel("tg:logist") == "telegram"
    assert notify.pick_channel("https://t.me/cdek") == "telegram"


def test_pick_channel_phone():
    assert notify.pick_channel("+375291234567") == "phone"


def test_pick_channel_none_when_no_address():
    assert notify.pick_channel("") == "none"
    assert notify.pick_channel("   ") == "none"
    assert notify.pick_channel("Контактное лицо") == "none"   # без цифр/@/tg — некуда слать


def test_invite_message_has_params_and_link():
    msg = notify.invite_message("ТНД-2026-0001", "АКБ 280Ач", 900, "Минск", "Гомель",
                                "Автолайт Экспресс", "/logistics/rfqs/bid/abc123")
    assert "ТНД-2026-0001" in msg and "АКБ 280Ач" in msg
    assert "900 кг" in msg and "Минск → Гомель" in msg
    assert "/logistics/rfqs/bid/abc123" in msg
    assert msg.startswith("Автолайт Экспресс")


def test_send_invite_skips_without_channel():
    r = notify.send_invite("none", "", "msg")
    assert r["status"] == "skipped" and r["channel"] == "none"


def test_send_invite_returns_sent():
    r = notify.send_invite("email", "sales@dpd.by", "msg")
    assert r["status"] == "sent" and r["channel"] == "email" and "отправлено" in r["detail"]


def test_send_invite_mvp_log_when_unconfigured():
    s = SimpleNamespace(smtp_host="", telegram_bot_token="")
    r = notify.send_invite("email", "a@b.by", "msg", settings=s)
    assert r["status"] == "sent" and "MVP" in r["detail"]   # нет SMTP → MVP-лог


def test_send_invite_real_email_when_configured(monkeypatch):
    import smtplib
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, msg):
            sent["to"], sent["from"] = msg["To"], msg["From"]

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = SimpleNamespace(smtp_host="smtp.x", smtp_port=587, smtp_user="u",
                        smtp_password="p", smtp_from="f@x.by", smtp_tls=True)
    r = notify.send_invite("email", "carrier@x.by", "msg", settings=s)
    assert r["status"] == "sent" and r["channel"] == "email"
    assert sent["to"] == "carrier@x.by" and sent.get("tls") and sent.get("login") == "u"


def test_send_invite_email_failure_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notify, "_send_email", boom)
    r = notify.send_invite("email", "c@x.by", "msg", settings=SimpleNamespace(smtp_host="smtp.x"))
    assert r["status"] == "failed" and "smtp down" in r["detail"]   # ошибку не молчим


def test_send_invite_real_telegram_strips_prefix(monkeypatch):
    import httpx
    calls: dict = {}

    class FakeResp:
        def raise_for_status(self):
            calls["ok"] = True

    def fake_post(url, json, timeout=10):
        calls["url"], calls["chat"] = url, json["chat_id"]
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    r = notify.send_invite("telegram", "tg:12345", "msg",
                           settings=SimpleNamespace(telegram_bot_token="TOK"))
    assert r["status"] == "sent" and r["channel"] == "telegram"
    assert "botTOK/sendMessage" in calls["url"] and calls["chat"] == "12345"
