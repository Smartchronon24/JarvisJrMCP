from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.execution import ExecutionResult
from app.tools.gateway import GatewaySearchRequest, JarvisToolGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tools(
        [
            ToolMetadata(
                name="whatsapp__send_message",
                server="whatsapp",
                tool_name="send_message",
                capability="communication",
                description="Send a WhatsApp message to a contact",
                input_schema={
                    "type": "object",
                    "properties": {"recipient": {"type": "string"}},
                    "required": ["recipient"],
                },
            ),
            ToolMetadata(
                name="filesystem__read_file",
                server="filesystem",
                tool_name="read_file",
                capability="filesystem",
                description="Read a file",
                input_schema={"type": "object", "properties": {}},
            ),
        ]
    )
    return registry


def test_search_returns_sanitized_registered_metadata() -> None:
    execution = SimpleNamespace()
    gateway = JarvisToolGateway(_registry(), execution)

    result = gateway.search({"query": "send a WhatsApp message"})

    assert result.total_candidates == 1
    assert result.tools[0]["name"] == "whatsapp__send_message"
    assert result.tools[0]["input_schema"]["required"] == ["recipient"]
    assert "enabled" not in result.tools[0]
    assert "available" not in result.tools[0]


def test_search_request_rejects_malformed_filters() -> None:
    with pytest.raises(ValueError, match="query must be a string"):
        GatewaySearchRequest.from_mapping({"query": 42})


@pytest.mark.asyncio
async def test_execute_delegates_to_existing_execution_gateway() -> None:
    expected = ExecutionResult(status="success", content="sent")
    execution = SimpleNamespace(execute=AsyncMock(return_value=expected))
    gateway = JarvisToolGateway(_registry(), execution)

    result = await gateway.execute("whatsapp__send_message", {"recipient": "Alex"})

    assert result is expected
    execution.execute.assert_awaited_once_with(
        "whatsapp__send_message", {"recipient": "Alex"}
    )
