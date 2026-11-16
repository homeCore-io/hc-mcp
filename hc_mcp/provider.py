"""The model the chat talks to, behind a small interface.

The chat loop (``chat.py``) knows nothing about any one API. It hands a
provider the system prompt, the conversation so far and the tools, gets text
as it is written, and gets back the reply: its content (stored verbatim, so
the next turn can carry on from it), its tool calls, and why it stopped.

Only the Claude API is built. An OpenAI-compatible endpoint or a local model
would be another class with the same four methods; the conversation history a
chat keeps is in its provider's own format, so a chat stays with the provider
it started on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

#: Why a reply stopped, in the loop's words.
END = "end"
TOOL_USE = "tool_use"
MAX_TOKENS = "max_tokens"
REFUSAL = "refusal"


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any


@dataclass
class Reply:
    #: The reply as the provider's API takes it back in the next request.
    content: list[dict]
    stop: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ProviderError(Exception):
    """The model could not be reached or would not answer. ``str()`` is
    written for the person in the chat; ``reason`` is for the screen and the
    log: ``no_key``, ``auth``, ``model``, ``busy``, ``unavailable``,
    ``network``, ``bad_request``."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class Canceled(Exception):
    """The person stopped the reply."""


class Provider(Protocol):
    async def reply(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_text: Callable[[str], None],
        should_stop: Callable[[], bool],
    ) -> Reply: ...

    def user_message(self, text: str) -> dict: ...

    def tool_results_message(self, results: list[tuple[str, str, bool]]) -> dict:
        """One message answering every tool call of a reply:
        ``(tool call id, content, is_error)`` each."""
        ...

    async def check(self) -> None:
        """Raise :class:`ProviderError` unless the key and model work."""
        ...


NO_KEY = (
    "The assistant needs a Claude API key. An admin can add it in Settings > Plugins > Assistant."
)


class AnthropicProvider:
    """The Claude API (Anthropic Messages API) with tool use, streamed."""

    #: Room for a long answer; streaming keeps a large cap from timing out.
    MAX_TOKENS = 16000

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        if not api_key:
            raise ProviderError(NO_KEY, "no_key")
        self.model = model
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
        self._client = client

    def user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def tool_results_message(self, results: list[tuple[str, str, bool]]) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": err}
                for tid, content, err in results
            ],
        }

    def _request(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        req: dict = {
            "model": self.model,
            "max_tokens": self.MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if tools:
            req["tools"] = tools
        # Chat about a house wants quick, plain answers. Haiku 4.5 takes no
        # effort setting at all.
        if not self.model.startswith("claude-haiku"):
            req["output_config"] = {"effort": "low"}
        return req

    async def reply(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_text: Callable[[str], None],
        should_stop: Callable[[], bool],
    ) -> Reply:
        try:
            async with self._client.messages.stream(
                **self._request(system, messages, tools)
            ) as stream:
                async for event in stream:
                    if should_stop():
                        raise Canceled()
                    if event.type == "text":
                        on_text(event.text)
                final = await stream.get_final_message()
        except Canceled:
            raise
        except Exception as exc:
            raise self._words(exc) from exc

        content = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
        calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in final.content
            if b.type == "tool_use"
        ]
        stop = {
            "end_turn": END,
            "stop_sequence": END,
            "tool_use": TOOL_USE,
            "max_tokens": MAX_TOKENS,
            "refusal": REFUSAL,
        }.get(final.stop_reason or "", END)
        return Reply(content=content, stop=stop, tool_calls=calls)

    async def check(self) -> None:
        try:
            await self._client.models.retrieve(self.model)
        except Exception as exc:
            raise self._words(exc) from exc

    def _words(self, exc: Exception) -> ProviderError:
        """An API failure in words for the person in the chat."""
        import anthropic

        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return ProviderError(
                "The Claude API key was not accepted. An admin can replace it in "
                "Settings > Plugins > Assistant.",
                "auth",
            )
        if isinstance(exc, anthropic.NotFoundError):
            return ProviderError(
                f"This API key can't use {self.model}. An admin can pick another model in "
                "Settings > Plugins > Assistant.",
                "model",
            )
        if isinstance(exc, anthropic.RateLimitError):
            return ProviderError(
                "Claude is busy for this API key right now. Try again in a minute.", "busy"
            )
        if isinstance(exc, anthropic.BadRequestError):
            return ProviderError(
                f"Claude could not take that request: {exc.message}", "bad_request"
            )
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderError(
                "Claude isn't answering right now. Try again shortly.", "unavailable"
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError(
                "The assistant can't reach the Claude API. Check this computer's internet "
                "connection.",
                "network",
            )
        return ProviderError(f"Something went wrong talking to Claude: {exc}", "unavailable")
