from __future__ import annotations

from typing import Any, Iterable

from ollama import Client
import ollama

from app.llm.base import ProviderError, ChatResponse, ChatMessage, ChatToolCall, ChatFunction
from config.settings import OLLAMA_HOST


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str | None = OLLAMA_HOST) -> None:
        self.client = Client(host=host) if host else Client()

    def format_tool(self, server_name: str, mcp_tool: Any) -> dict[str, Any]:
        scoped_name = f"{server_name}__{mcp_tool.name}"
        input_schema = (
            getattr(mcp_tool, "input_schema", None)
            or getattr(mcp_tool, "inputSchema", None)
            or {}
        )
        properties = {}
        for prop_name, prop_schema in input_schema.get("properties", {}).items():
            properties[prop_name] = {
                "type": prop_schema.get("type", "string"),
                "description": prop_schema.get("description", ""),
            }
            if "items" in prop_schema:
                properties[prop_name]["items"] = prop_schema["items"]

        return {
            "type": "function",
            "function": {
                "name": scoped_name,
                "description": mcp_tool.description or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": input_schema.get("required", []),
                },
            },
        }

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        response_format: str | None = None,
    ) -> Any | Iterable[Any]:
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "stream": stream,
            }
            if response_format is not None:
                kwargs["format"] = response_format
            raw = self.client.chat(**kwargs)

            if stream:
                return self._stream_wrap(raw)
            else:
                return self._wrap_response(raw)

        except ollama.ResponseError as exc:
            raise ProviderError(
                str(exc),
                supports_tools="does not support tools" not in str(exc),
            ) from exc
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    def _stream_wrap(self, raw_iter: Iterable[Any]) -> Iterable[ChatResponse]:
        """Wrap Ollama streaming chunks into unified ChatResponse objects."""
        for chunk in raw_iter:
            msg = chunk.message
            raw_tool_calls = msg.tool_calls or []
            unified_tcs = None
            if raw_tool_calls:
                unified_tcs = [
                    ChatToolCall(
                        function=ChatFunction(
                            name=tc.function.name,
                            arguments=dict(tc.function.arguments) if tc.function.arguments else {},
                        )
                    )
                    for tc in raw_tool_calls
                ]
            yield ChatResponse(
                message=ChatMessage(
                    content=msg.content,
                    tool_calls=unified_tcs,
                ),
                prompt_eval_count=getattr(chunk, "prompt_eval_count", None),
                eval_count=getattr(chunk, "eval_count", None),
            )

    def _wrap_response(self, raw: Any) -> ChatResponse:
        """Wrap a non-streaming Ollama response into a unified ChatResponse."""
        msg = raw.message
        raw_tool_calls = msg.tool_calls or []
        unified_tcs = None
        if raw_tool_calls:
            unified_tcs = [
                ChatToolCall(
                    function=ChatFunction(
                        name=tc.function.name,
                        arguments=dict(tc.function.arguments) if tc.function.arguments else {},
                    )
                )
                for tc in raw_tool_calls
            ]
        return ChatResponse(
            message=ChatMessage(
                content=msg.content,
                tool_calls=unified_tcs,
            ),
            prompt_eval_count=getattr(raw, "prompt_eval_count", None),
            eval_count=getattr(raw, "eval_count", None),
        )

    def list_models(self) -> list[str]:
        try:
            response = self.client.list()
            return [model.model for model in response.models]
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
