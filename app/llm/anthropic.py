from __future__ import annotations

from typing import Any, Iterable
import json

import anthropic
from anthropic import Anthropic, APIError
from app.llm.base import ProviderError, ChatResponse, ChatMessage, ChatToolCall, ChatFunction
from app.llm.credentials import get_provider_api_key

class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self._client = None
        self._api_key = None

    def _get_client(self) -> Anthropic:
        api_key = get_provider_api_key("anthropic")
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set. Please set it in .env or via the UI.")
        
        if self._client is None or self._api_key != api_key:
            self._client = Anthropic(api_key=api_key)
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

        # Anthropic uses a slightly different tool format but the dict structure is expected by our wrapper
        return {
            "name": scoped_name,
            "description": mcp_tool.description or "",
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": input_schema.get("required", []),
            }
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
            
            # Extract system prompt if it exists as Anthropic handles it differently
            system_prompt = ""
            anthropic_messages = []
            
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt += msg["content"] + "\n"
                else:
                    anthropic_messages.append(msg)

            kwargs: dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": 4096,
            }
            if system_prompt:
                kwargs["system"] = system_prompt.strip()
            
            if tools:
                # Convert OpenAI tool format (used by OllamaProvider) to Anthropic tool format if needed
                anthropic_tools = []
                for t in tools:
                    if "function" in t: # OpenAI format
                        anthropic_tools.append({
                            "name": t["function"]["name"],
                            "description": t["function"].get("description", ""),
                            "input_schema": t["function"]["parameters"]
                        })
                    else: # Anthropic format
                        anthropic_tools.append(t)
                kwargs["tools"] = anthropic_tools

            if stream:
                response = client.messages.create(stream=True, **kwargs)
                return self._stream_generator(response)
            else:
                response = client.messages.create(**kwargs)
                return self._parse_response(response)
                
        except APIError as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderError(str(exc)) from exc

    def _stream_generator(self, response: Iterable[Any]) -> Iterable[ChatResponse]:
        tool_call_name = ""
        tool_call_args = ""
        
        p_eval = None
        c_eval = None

        for event in response:
            if event.type == "message_start":
                if hasattr(event.message, "usage"):
                    p_eval = event.message.usage.input_tokens
            elif event.type == "content_block_start":
                if event.content_block.type == "tool_use":
                    tool_call_name = event.content_block.name
                    tool_call_args = ""
            elif event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield ChatResponse(
                        message=ChatMessage(content=event.delta.text),
                        prompt_eval_count=p_eval
                    )
                    p_eval = None # only send once
                elif event.delta.type == "input_json_delta":
                    tool_call_args += event.delta.partial_json
            elif event.type == "content_block_stop":
                if tool_call_name:
                    try:
                        args = json.loads(tool_call_args)
                    except Exception:
                        args = {}
                    tc = ChatToolCall(function=ChatFunction(name=tool_call_name, arguments=args))
                    yield ChatResponse(
                        message=ChatMessage(tool_calls=[tc])
                    )
                    tool_call_name = ""
                    tool_call_args = ""
            elif event.type == "message_delta":
                if hasattr(event.delta, "usage"):
                    c_eval = event.delta.usage.output_tokens

        # Send final token counts if we haven't
        if c_eval is not None:
            yield ChatResponse(
                message=ChatMessage(),
                eval_count=c_eval
            )

    def _parse_response(self, response: Any) -> ChatResponse:
        content = ""
        tool_calls = []
        
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                # input is already parsed as dict
                tool_calls.append(ChatToolCall(function=ChatFunction(name=block.name, arguments=block.input)))

        p_eval = response.usage.input_tokens if response.usage else None
        c_eval = response.usage.output_tokens if response.usage else None

        return ChatResponse(
            message=ChatMessage(
                content=content if content else None,
                tool_calls=tool_calls if tool_calls else None
            ),
            prompt_eval_count=p_eval,
            eval_count=c_eval
        )

    def list_models(self) -> list[str]:
        # Anthropic doesn't have a list models endpoint in the same way, return static list of popular ones
        return [
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]
