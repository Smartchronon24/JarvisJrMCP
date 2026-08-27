from __future__ import annotations

import json
from typing import Any, Iterable

from app.llm.base import ProviderError, ChatResponse, ChatMessage, ChatToolCall, ChatFunction
from app.llm.credentials import get_provider_api_key


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        self._client = None
        self._api_key = None

    def _get_client(self) -> Any:
        api_key = get_provider_api_key("gemini")
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set. Please set it in .env or via the UI.")
        
        if self._client is None or self._api_key != api_key:
            from google import genai
            self._client = genai.Client(api_key=api_key)
            self._api_key = api_key
        return self._client

    def format_tool(self, server_name: str, mcp_tool: Any) -> dict[str, Any]:
        """
        Return an OpenAI-style tool dict.
        Gemini SDK accepts function declarations in its own format, but we convert
        at call time inside .chat() so the rest of the system sees a uniform format.
        """
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

    def _build_gemini_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI-style tool dicts to Gemini FunctionDeclaration objects."""
        from google.genai import types as genai_types

        declarations = []
        for t in tools:
            fn = t.get("function", t)  # handle both OpenAI format and raw
            params = fn.get("parameters", {})
            declarations.append(
                genai_types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=genai_types.Schema(
                        type=genai_types.Type.OBJECT,
                        properties={
                            k: genai_types.Schema(
                                type=v.get("type", "string").upper(),
                                description=v.get("description", ""),
                            )
                            for k, v in params.get("properties", {}).items()
                        },
                        required=params.get("required", []),
                    ),
                )
            )
        return [genai_types.Tool(function_declarations=declarations)]

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[Any]]:
        """Extract system prompt and convert chat history to Gemini Content objects."""
        from google.genai import types as genai_types

        system_prompt = ""
        contents = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_prompt += content + "\n"
                continue
            elif role == "user":
                gemini_role = "user"
            elif role == "assistant":
                gemini_role = "model"
            elif role == "tool":
                # Tool results go back as user-role function responses in Gemini
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part(text=f"[Tool result]: {content}")]
                    )
                )
                continue
            else:
                continue

            contents.append(
                genai_types.Content(
                    role=gemini_role,
                    parts=[genai_types.Part(text=content or "")]
                )
            )

        return system_prompt.strip(), contents

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
            from google.genai import types as genai_types

            system_prompt, contents = self._convert_messages(messages)

            config_kwargs: dict[str, Any] = {}
            if system_prompt:
                config_kwargs["system_instruction"] = system_prompt
            if response_format == "json":
                config_kwargs["response_mime_type"] = "application/json"

            gemini_tools = self._build_gemini_tools(tools) if tools else None
            if gemini_tools:
                config_kwargs["tools"] = gemini_tools

            config = genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

            if stream:
                raw = client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                )
                return self._stream_generator(raw, client)
            else:
                raw = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(raw)

        except Exception as exc:
            err_str = str(exc)
            supports_tools = "does not support" not in err_str.lower()
            raise ProviderError(err_str, supports_tools=supports_tools) from exc

    def _stream_generator(self, raw_iter: Iterable[Any], client: Any) -> Iterable[ChatResponse]:
        for chunk in raw_iter:
            # Extract text content
            content = None
            tool_calls = None

            try:
                for part in chunk.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        content = part.text
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls = [
                            ChatToolCall(
                                function=ChatFunction(
                                    name=fc.name,
                                    arguments=dict(fc.args) if fc.args else {},
                                )
                            )
                        ]
            except (AttributeError, IndexError):
                pass

            yield ChatResponse(
                message=ChatMessage(content=content, tool_calls=tool_calls),
            )

    def _parse_response(self, raw: Any) -> ChatResponse:
        content = None
        tool_calls = None

        try:
            for part in raw.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    content = (content or "") + part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append(
                        ChatToolCall(
                            function=ChatFunction(
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {},
                            )
                        )
                    )
        except (AttributeError, IndexError):
            pass

        # Gemini usage metadata
        p_eval = None
        c_eval = None
        try:
            p_eval = raw.usage_metadata.prompt_token_count
            c_eval = raw.usage_metadata.candidates_token_count
        except AttributeError:
            pass

        return ChatResponse(
            message=ChatMessage(content=content, tool_calls=tool_calls),
            prompt_eval_count=p_eval,
            eval_count=c_eval,
        )

    def list_models(self) -> list[str]:
        try:
            client = self._get_client()
            models = client.models.list()
            return [m.name for m in models]
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
