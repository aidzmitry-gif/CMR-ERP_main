import hashlib
import hmac

import pytest

from modules.marketing.seo_webhook import _snapshot_extra, handle_seo_event, verify_hmac_signature


def test_seo_hmac_verification_requires_secret_signature_and_exact_body():
    body = b'{"event":"snapshot"}'
    signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_hmac_signature(body, "secret", signature) is True
    assert verify_hmac_signature(body, "secret", " " + signature + " ") is True
    assert verify_hmac_signature(body + b"!", "secret", signature) is False
    assert verify_hmac_signature(body, "", signature) is False
    assert verify_hmac_signature(body, "secret", "") is False


def test_snapshot_extra_merges_supported_aliases_without_overwriting_payload():
    assert _snapshot_extra({}) is None
    result = _snapshot_extra(
        {
            "payload": {"task_count": 1, "custom": "keep"},
            "task_count": 2,
            "taskCount": 3,
            "quickWins": [{"keyword": "x"}],
        }
    )
    assert result == {"task_count": 1, "custom": "keep", "taskCount": 3, "quickWins": [{"keyword": "x"}]}


@pytest.mark.asyncio
async def test_unknown_seo_event_is_rejected_without_database_work():
    assert await handle_seo_event(object(), "marketing.seo.unknown", {}) is False
