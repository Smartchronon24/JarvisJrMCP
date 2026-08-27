from __future__ import annotations

from typing import Any, Iterable, Protocol, Optional, List, Dict
from dataclasses import dataclass, field

class ProviderError(RuntimeError):
    """Provider-level failure with enough context for the agent error policy."""

    def __init__(self, message: str, *, supports_tools: bool = True) -> None:
        super().__init__(message)
        self.supports_tools = supports_tools

@dataclass
class ChatFunction:
    name: str
    arguments: Dict[str, Any]

@dataclass
class ChatToolCall:
    function: ChatFunction

@dataclass
class ChatMessage:
    content: Optional[str] = None
    tool_calls: Optional[List[ChatToolCall]] = None

@dataclass
class ChatResponse:
    message: ChatMessage
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None

class LLMProvider(Protocol):
    """Minimal contract required by Jarvis agents."""

    name: str

    def format_tool(self, server_name: str, mcp_tool: Any) -> dict[str, Any]:
        ...

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        response_format: str | None = None,
    ) -> Any | Iterable[Any]:
        ...

    def list_models(self) -> list[str]:
        ...
