from __future__ import annotations

import json
from typing import Any, Iterable

from openai import OpenAI, OpenAIError
from app.llm.base import ProviderError, LLMProvider, ChatResponse, ChatMessage, ChatToolCall, ChatFunction
from app.llm.credentials import get_provider_api_key

class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self._client = None
        self._api_key = None

    def _get_client(self) -> OpenAI:
        api_key = get_provider_api_key("openai")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is not set. Please set it in .env or via the UI.")
        
        if self._client is None or self._api_key != api_key:
            self._client = OpenAI(api_key=api_key)
            self._api_key = api_key
        return self._client

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
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": stream,
            }
            if tools:
                kwargs["tools"] = tools
            
            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)

            if stream:
                return self._stream_generator(response)
            else:
                return self._parse_response(response)
                
        except OpenAIError as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    def _stream_generator(self, response: Iterable[Any]) -> Iterable[ChatResponse]:
        tool_calls_buffer = {}
        
        for chunk in response:
            delta = chunk.choices[0].delta
            content = delta.content
            
            # Tool calls streaming
            tool_calls = delta.tool_calls
            if tool_calls:
                for tc in tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"name": tc.function.name or "", "arguments": tc.function.arguments or ""}
                    else:
                        if tc.function.name:
                            tool_calls_buffer[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments
            
            # OpenAI doesn't send token usage in standard stream chunks unless stream_options is configured
            # For simplicity we omit token tracking here, bookkeeping will handle null
            
            yield ChatResponse(
                message=ChatMessage(content=content, tool_calls=None)
            )

        # After stream ends, yield the buffered tool calls as a final chunk
        if tool_calls_buffer:
            final_tool_calls = []
            for idx in sorted(tool_calls_buffer.keys()):
                tc_data = tool_calls_buffer[idx]
                try:
                    args = json.loads(tc_data["arguments"])
                except Exception:
                    args = {}
                final_tool_calls.append(ChatToolCall(function=ChatFunction(name=tc_data["name"], arguments=args)))
            
            yield ChatResponse(
                message=ChatMessage(content=None, tool_calls=final_tool_calls)
            )

    def _parse_response(self, response: Any) -> ChatResponse:
        message = response.choices[0].message
        content = message.content
        
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls.append(ChatToolCall(function=ChatFunction(name=tc.function.name, arguments=args)))

        p_eval = response.usage.prompt_tokens if response.usage else None
        c_eval = response.usage.completion_tokens if response.usage else None

        return ChatResponse(
            message=ChatMessage(
                content=content,
                tool_calls=tool_calls if tool_calls else None
            ),
            prompt_eval_count=p_eval,
            eval_count=c_eval
        )

    def list_models(self) -> list[str]:
        try:
            client = self._get_client()
            models = client.models.list()
            return [model.id for model in models.data]
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
