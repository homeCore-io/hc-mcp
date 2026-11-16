"""The Claude provider against a fake Anthropic client: streaming text, tool
calls, and failures in words. No request leaves the machine."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types import TextBlock, ToolUseBlock

from hc_mcp.provider import END, TOOL_USE, AnthropicProvider, Canceled, ProviderError


class FakeStream:
    def __init__(self, deltas, final, fail=None):
        self.deltas, self.final, self.fail = deltas, final, fail

    async def __aenter__(self):
        if self.fail:
            raise self.fail
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for d in self.deltas:
                yield SimpleNamespace(type="text", text=d)
            yield SimpleNamespace(type="message_stop")

        return gen()

    async def get_final_message(self):
        return self.final


class FakeAnthropic:
    def __init__(self, stream=None, retrieve_error=None):
        self.requests = []
        self._stream = stream
        self._retrieve_error = retrieve_error
        self.messages = SimpleNamespace(stream=self._stream_call)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    def _stream_call(self, **kw):
        self.requests.append(kw)
        return self._stream

    async def _retrieve(self, model):
        if self._retrieve_error:
            raise self._retrieve_error
        return SimpleNamespace(id=model)


def final(content, stop):
    return SimpleNamespace(content=content, stop_reason=stop)


def reply(provider, **kw):
    seen = []
    out = asyncio.run(
        provider.reply(
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            tools=kw.get("tools", []),
            on_text=seen.append,
            should_stop=kw.get("should_stop", lambda: False),
        )
    )
    return out, seen


def api_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json={"error": {"message": "nope"}})
    return cls("nope", response=response, body=None)


def test_no_key_is_said_plainly():
    with pytest.raises(ProviderError) as e:
        AnthropicProvider("", "claude-sonnet-5-5")
    assert e.value.reason == "no_key"
    assert "needs a Claude API key" in str(e.value)
    assert "Settings > Plugins > Assistant" in str(e.value)


def test_text_streams_and_tool_calls_come_back():
    blocks = [
        TextBlock(type="text", text="Let me look."),
        ToolUseBlock(type="tool_use", id="toolu_1", name="list_devices", input={}),
    ]
    fake = FakeAnthropic(FakeStream(["Let ", "me look."], final(blocks, "tool_use")))
    p = AnthropicProvider("sk-ant-x", "claude-sonnet-5-5", client=fake)
    out, seen = reply(p, tools=[{"name": "list_devices"}])
    assert seen == ["Let ", "me look."]
    assert out.stop == TOOL_USE
    assert [(c.id, c.name, c.input) for c in out.tool_calls] == [("toolu_1", "list_devices", {})]
    # Kept verbatim for the next request, without nulls.
    assert out.content[0] == {"type": "text", "text": "Let me look."}
    assert out.content[1]["type"] == "tool_use"
    req = fake.requests[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["tools"] == [{"name": "list_devices"}]
    assert req["output_config"] == {"effort": "low"}


def test_haiku_gets_no_effort_setting():
    fake = FakeAnthropic(FakeStream([], final([], "end_turn")))
    p = AnthropicProvider("k", "claude-haiku-4-5-20251001", client=fake)
    out, _ = reply(p)
    assert out.stop == END
    assert "output_config" not in fake.requests[0]
    assert "tools" not in fake.requests[0]


def test_stopping_mid_reply():
    fake = FakeAnthropic(FakeStream(["a", "b"], final([], "end_turn")))
    p = AnthropicProvider("k", "claude-sonnet-5-5", client=fake)
    with pytest.raises(Canceled):
        reply(p, should_stop=lambda: True)


@pytest.mark.parametrize(
    "error, reason",
    [
        (api_error(anthropic.AuthenticationError, 401), "auth"),
        (api_error(anthropic.NotFoundError, 404), "model"),
        (api_error(anthropic.RateLimitError, 429), "busy"),
        (api_error(anthropic.InternalServerError, 500), "unavailable"),
        (api_error(anthropic.BadRequestError, 400), "bad_request"),
        (
            anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            "network",
        ),
    ],
)
def test_failures_are_put_in_words(error, reason):
    fake = FakeAnthropic(FakeStream([], None, fail=error))
    p = AnthropicProvider("k", "claude-sonnet-5-5", client=fake)
    with pytest.raises(ProviderError) as e:
        reply(p)
    assert e.value.reason == reason
    assert str(e.value)


def test_check_uses_the_models_endpoint():
    ok = AnthropicProvider("k", "claude-opus-5-5", client=FakeAnthropic())
    asyncio.run(ok.check())
    bad = AnthropicProvider(
        "k", "claude-opus-5-5",
        client=FakeAnthropic(retrieve_error=api_error(anthropic.AuthenticationError, 401)),
    )  # fmt: skip
    with pytest.raises(ProviderError) as e:
        asyncio.run(bad.check())
    assert e.value.reason == "auth"
