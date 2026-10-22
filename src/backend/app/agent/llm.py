"""LLM access. Switching providers is config only: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL."""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from app.core.config import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, validated by the executor


@dataclass
class AssistantTurn:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return msg


class LLMClient(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn: ...


class OpenAICompatibleClient:
    """OpenRouter or our vLLM endpoint on RunPod; both speak the OpenAI API."""

    def __init__(self) -> None:
        self._client = openai.OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=60,
            max_retries=2,
        )

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AssistantTurn:
        try:
            resp = self._client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=600,
            )
        except openai.OpenAIError as exc:
            log.warning("LLM call failed: %s", type(exc).__name__)
            raise LLMError(str(exc)) from exc
        if not resp.choices:
            raise LLMError("empty response")
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=c.id or f"call_{i}", name=c.function.name, arguments=c.function.arguments)
            for i, c in enumerate(msg.tool_calls or [])
            if c.type == "function"
        ]
        return AssistantTurn(content=msg.content, tool_calls=calls)


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = OpenAICompatibleClient()
    return _client


def set_llm_client(client: LLMClient | None) -> None:
    """Tests inject a scripted client here."""
    global _client
    _client = client
