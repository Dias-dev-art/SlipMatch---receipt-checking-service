"""Scripted LLM for tests: no network. Each step is an AssistantTurn or a function of messages."""

import json
from collections.abc import Callable
from typing import Any

from app.agent.llm import AssistantTurn, LLMError, ToolCall

Step = AssistantTurn | Callable[[list[dict[str, Any]]], AssistantTurn] | Exception


def call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(arguments))


def tools(*calls: ToolCall) -> AssistantTurn:
    return AssistantTurn(tool_calls=list(calls))


def say(text: str) -> AssistantTurn:
    return AssistantTurn(content=text)


class ScriptedLLM:
    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.requests: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[dict[str, Any]]] = []

    def script(self, *steps: Step) -> "ScriptedLLM":
        self.steps.extend(steps)
        return self

    def chat(self, messages, tools_):
        self.requests.append([dict(m) for m in messages])
        self.tools_seen.append(tools_)
        if not self.steps:
            raise AssertionError("LLM called more times than scripted")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step

    def tool_results(self) -> list[dict[str, Any]]:
        """All tool results the backend sent back to the LLM, in order."""
        last = self.requests[-1] if self.requests else []
        return [json.loads(m["content"]) for m in last if m.get("role") == "tool"]


__all__ = ["LLMError", "ScriptedLLM", "call", "say", "tools"]
