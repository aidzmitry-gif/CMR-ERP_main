"""Gateway wire contract; all provider traffic stays in MockTransport."""
import gzip
import json
from types import SimpleNamespace

import httpx
import pytest

from core.services.litellm import LLMGateway


def gateway(base="http://model.test/v1", model="configured-model"):
    return LLMGateway(SimpleNamespace(ai_enabled=True, llm_base_url=base, llm_model=model))


def completion(content="Provider text", **choice):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}, **choice}]}


@pytest.fixture
def provider(monkeypatch):
    original_client = httpx.AsyncClient
    calls = []

    def install(response):
        def respond(request):
            calls.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            return original_client(transport=httpx.MockTransport(respond), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)
        return calls

    return install


@pytest.mark.parametrize("base", ["http://model.test/v1", "http://model.test/v1/"])
async def test_configured_endpoint_and_messages(provider, base):
    calls = provider(httpx.Response(200, json=completion()))
    assert await gateway(base).complete("Synthetic prompt", system="System instruction") == "Provider text"
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].headers["accept-encoding"] == "identity"
    assert str(calls[0].url) == "http://model.test/v1/chat/completions"
    assert json.loads(calls[0].content) == {
        "model": "configured-model", "stream": False,
        "messages": [{"role": "system", "content": "System instruction"}, {"role": "user", "content": "Synthetic prompt"}],
    }


async def test_empty_system_is_not_a_message(provider):
    calls = provider(httpx.Response(200, json=completion()))
    assert await gateway().complete("Synthetic prompt") == "Provider text"
    assert json.loads(calls[0].content)["messages"] == [{"role": "user", "content": "Synthetic prompt"}]


@pytest.mark.parametrize("status", [302, 503])
async def test_http_error_never_becomes_mock_or_discloses_body(provider, status):
    calls = provider(httpx.Response(status, text="PRIVATE_PROVIDER_BODY", headers={"location": "http://other.test"}))
    with pytest.raises(RuntimeError, match="недоступ") as caught:
        await gateway().complete("PRIVATE_PROMPT", kind="draft")
    assert len(calls) == 1
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("PRIVATE_PROVIDER_ERROR"), TimeoutError("PRIVATE_PROVIDER_ERROR")])
async def test_transport_error_is_sanitized_without_retry(provider, error):
    calls = provider(error)
    with pytest.raises(RuntimeError, match="недоступ") as caught:
        await gateway().complete("PRIVATE_PROMPT")
    assert len(calls) == 1
    assert "PRIVATE" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("payload", [
    b"not json PRIVATE_PROVIDER_BODY",
    b"null",
    b'{"choices": []}',
    json.dumps(completion("   ")).encode(),
    json.dumps(completion(["invalid content"])).encode(),
    json.dumps(completion("partial", finish_reason="tool_calls")).encode(),
    json.dumps(completion("partial", finish_reason="length")).encode(),
    json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "partial", "refusal": "refused"}}]}).encode(),
], ids=["invalid-json", "null", "empty-choices", "blank-text", "nontext", "tool-call", "truncated", "refusal"])
async def test_invalid_response_is_not_a_success(provider, payload):
    calls = provider(httpx.Response(200, content=payload))
    with pytest.raises(RuntimeError, match="некоррект") as caught:
        await gateway().complete("PRIVATE_PROMPT")
    assert len(calls) == 1
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("base,model", [
    ("file:///model", "model"),
    ("http://user:synthetic@model.test", "model"),
    ("http://model.test?token=synthetic", "model"),
    ("http://model.test#fragment", "model"),
    ("http://model.test", " "),
], ids=["scheme", "userinfo", "query", "fragment", "empty-model"])
async def test_invalid_configuration_sends_no_prompt(provider, base, model):
    calls = provider(httpx.Response(200, json=completion()))
    with pytest.raises(RuntimeError, match="настрой"):
        await gateway(base, model).complete("PRIVATE_PROMPT")
    assert calls == []


async def test_provider_body_has_a_size_limit(provider):
    calls = provider(httpx.Response(200, content=b" " * (1024 * 1024 + 1)))
    with pytest.raises(RuntimeError, match="некоррект"):
        await gateway().complete("Synthetic prompt")
    assert len(calls) == 1


@pytest.mark.parametrize("environment", ["prod", "staging", "", None])
@pytest.mark.parametrize("base", [None, "", "   "])
async def test_missing_provider_outside_dev_never_returns_mock(provider, environment, base):
    calls = provider(httpx.Response(200, json=completion()))
    g = LLMGateway(SimpleNamespace(ai_enabled=True, environment=environment, llm_base_url=base))
    with pytest.raises(RuntimeError, match="настрой"):
        await g.complete("PRIVATE_PROMPT", kind="draft")
    assert calls == []


async def test_omitted_environment_never_implies_dev_mock(provider):
    calls = provider(httpx.Response(200, json=completion()))
    with pytest.raises(RuntimeError, match="настрой"):
        await LLMGateway(SimpleNamespace(ai_enabled=True)).complete("PRIVATE_PROMPT")
    assert calls == []


@pytest.mark.parametrize("base", [None, "", "   "])
async def test_explicit_dev_retains_mock_without_provider_calls(provider, base):
    calls = provider(httpx.Response(200, json=completion()))
    g = LLMGateway(SimpleNamespace(ai_enabled=True, environment="dev", llm_base_url=base))
    assert await g.complete("Synthetic prompt", kind="summary") == g._MOCKS["summary"]
    assert calls == []


@pytest.mark.parametrize("base", ["http://model.test/v1?", "http://model.test/v1#"])
async def test_empty_url_delimiters_send_no_prompt(provider, base):
    calls = provider(httpx.Response(200, json=completion()))
    with pytest.raises(RuntimeError, match="настрой"):
        await gateway(base).complete("PRIVATE_PROMPT")
    assert calls == []


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("encoding", ["gzip", "gzip, identity", "unknown"])
async def test_encoded_response_is_rejected_before_body_read(provider, encoding):
    stream = TrackedStream([gzip.compress(b" " * (1024 * 1024 + 1))])
    calls = provider(httpx.Response(200, headers={"content-encoding": encoding}, stream=stream))
    with pytest.raises(RuntimeError, match="некоррект"):
        await gateway().complete("PRIVATE_PROMPT")
    assert len(calls) == 1
    assert stream.reads == 0
    assert stream.closed


async def test_identity_stream_accepts_exact_body_limit(provider):
    payload = json.dumps(completion()).encode()
    payload += b" " * (1024 * 1024 - len(payload))
    stream = TrackedStream(payload[i:i + 16384] for i in range(0, len(payload), 16384))
    provider(httpx.Response(200, headers={"content-encoding": "identity"}, stream=stream))
    assert await gateway().complete("Synthetic prompt") == "Provider text"
    assert stream.reads == 64
    assert stream.closed


async def test_oversize_identity_stream_stops_and_closes_before_exhaustion(provider):
    stream = TrackedStream([b" " * 16384] * 67)
    provider(httpx.Response(200, stream=stream))
    with pytest.raises(RuntimeError, match="некоррект"):
        await gateway().complete("PRIVATE_PROMPT")
    assert stream.reads == 65
    assert stream.closed
