import hashlib
import hmac
from unittest.mock import AsyncMock

import pytest

from modules.marketing import seo_webhook


def test_verify_hmac_signature_rejects_missing_or_wrong_signatures():
    body = b'{"project":"P-1"}'
    secret = "local-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert seo_webhook.verify_hmac_signature(body, secret, signature) is True
    assert seo_webhook.verify_hmac_signature(body, secret, f" {signature} ") is True
    assert seo_webhook.verify_hmac_signature(body, secret, "wrong") is False
    assert seo_webhook.verify_hmac_signature(body, "", signature) is False
    assert seo_webhook.verify_hmac_signature(body, secret, "") is False


def test_snapshot_extra_merges_nested_payload_without_overwriting_it():
    assert seo_webhook._snapshot_extra({}) is None
    assert seo_webhook._snapshot_extra(
        {
            "payload": {"quick_wins": ["nested"], "source": "seo"},
            "quick_wins": ["top"],
            "task_count": 4,
            "visibilityHistory": [{"date": "2026-09-01", "visibility": 10}],
        }
    ) == {
        "quick_wins": ["nested"],
        "source": "seo",
        "task_count": 4,
        "visibilityHistory": [{"date": "2026-09-01", "visibility": 10}],
    }


@pytest.mark.asyncio
async def test_seo_event_dispatch_accepts_supported_events_and_rejects_unknown(monkeypatch):
    handlers = {
        name: AsyncMock()
        for name in (
            "_on_project_linked",
            "_on_snapshot_updated",
            "_on_task_upsert",
            "_on_task_status_changed",
            "_on_quick_win",
        )
    }
    for name, handler in handlers.items():
        monkeypatch.setattr(seo_webhook, name, handler)

    event_map = {
        "marketing.seo.project.linked": "_on_project_linked",
        "marketing.seo.snapshot.updated": "_on_snapshot_updated",
        "marketing.seo.task.created": "_on_task_upsert",
        "marketing.seo.task.status_changed": "_on_task_status_changed",
        "marketing.seo.quick_win.detected": "_on_quick_win",
    }
    for event, name in event_map.items():
        assert await seo_webhook.handle_seo_event("session", event, {"id": 1}) is True
        handlers[name].assert_awaited_once_with("session", {"id": 1})

    assert await seo_webhook.handle_seo_event("session", "marketing.seo.unknown", {}) is False
