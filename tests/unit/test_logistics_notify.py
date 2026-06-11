"""Юнит-тесты уведомления перевозчиков (notify) — выбор канала и текст приглашения."""
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
