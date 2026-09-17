from __future__ import annotations

import pytest

from core.services import incident_alerts
from core.services.incident_alerts import IncidentAlertSink


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_sink_logs_without_external_delivery(caplog):
    called = False

    async def sender(*args):
        nonlocal called
        called = True

    sink = IncidentAlertSink(sender=sender)

    assert await sink.emit("worker", RuntimeError("password=secret")) is False
    assert called is False
    assert "[REDACTED_SECRET]" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sink_sends_payload_and_suppresses_duplicate_until_forced():
    sent = []
    now = [100.0]

    async def sender(url, payload, token):
        sent.append((url, payload, token))

    sink = IncidentAlertSink(
        "https://alerts.example.test/hook",
        "token-123",
        cooldown_seconds=60,
        sender=sender,
        clock=lambda: now[0],
    )

    assert await sink.emit("worker", ValueError("offline"), details={"job": "relay"}) is True
    assert await sink.emit("worker", ValueError("offline again")) is False
    assert await sink.emit("worker", ValueError("manual retry"), force=True) is True
    assert len(sent) == 2
    assert sent[0][0] == "https://alerts.example.test/hook"
    assert sent[0][2] == "token-123"
    assert sent[0][1]["details"] == {"job": "relay"}
    assert sent[0][1]["severity"] == "critical"

    now[0] = 161.0
    assert await sink.emit("worker", ValueError("after cooldown")) is True
    assert len(sent) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sink_contains_delivery_failures_and_default_sender_uses_thread(monkeypatch):
    async def broken_sender(*args):
        raise OSError("network down")

    sink = IncidentAlertSink("https://alerts.example.test/hook", sender=broken_sender)
    assert await sink.emit("worker", RuntimeError("boom")) is False

    seen = {}

    def fake_sync(url, payload, token):
        seen.update(url=url, payload=payload, token=token)

    monkeypatch.setattr(incident_alerts, "_send_webhook_sync", fake_sync)
    await incident_alerts._send_webhook("https://alerts.example.test/hook", {"ok": True}, "tok")
    assert seen == {
        "url": "https://alerts.example.test/hook",
        "payload": {"ok": True},
        "token": "tok",
    }


@pytest.mark.unit
def test_sync_webhook_builds_json_and_bearer_header(monkeypatch):
    captured = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured.update(
            url=request.full_url,
            body=request.data,
            headers=dict(request.header_items()),
            method=request.method,
            timeout=timeout,
        )
        return Response()

    monkeypatch.setattr(incident_alerts, "urlopen", fake_urlopen)
    incident_alerts._send_webhook_sync("https://alerts.example.test/hook", {"x": "тест"}, "tok")

    assert captured["url"] == "https://alerts.example.test/hook"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 10
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert '"x": "тест"' in captured["body"].decode()


@pytest.mark.unit
def test_safe_error_message_redacts_secret_like_values():
    message = incident_alerts._safe_error_message(RuntimeError("token=abc password:xyz api_key=123"))
    assert "abc" not in message and "xyz" not in message and "123" not in message
    assert message.count("[REDACTED_SECRET]") == 3
