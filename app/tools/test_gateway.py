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
            ToolMetadata(
                name="playwright__browser_navigate",
                server="playwright",
                tool_name="browser_navigate",
                capability="browser",
                description="Navigate to a URL",
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
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


@pytest.mark.asyncio
async def test_external_action_discovers_and_executes_selected_capability() -> None:
    execution = SimpleNamespace(
        execute=AsyncMock(return_value=ExecutionResult(status="success", content="sent"))
    )
    gateway = JarvisToolGateway(_registry(), execution)

    result = await gateway.external_action(
        "send a WhatsApp message", {"recipient": "Alex"}
    )

    assert result["ok"] is True
    assert result["tool_name"] == "whatsapp__send_message"
    assert result["message"] == "sent"


@pytest.mark.asyncio
async def test_external_action_reports_missing_capability() -> None:
    gateway = JarvisToolGateway(_registry(), SimpleNamespace())

    result = await gateway.external_action("launch a spaceship")

    assert result["ok"] is False
    assert result["status"] == "capability_not_found"


@pytest.mark.asyncio
async def test_external_action_preserves_execution_failure() -> None:
    failure = ExecutionResult(
        status="runtime_error",
        content="browser failed",
        is_error=True,
        error_type="runtime_error",
    )
    execution = SimpleNamespace(execute=AsyncMock(return_value=failure))
    gateway = JarvisToolGateway(_registry(), execution)

    result = await gateway.external_action(
        "send a WhatsApp message", {"recipient": "Alex"}
    )

    assert result["ok"] is False
    assert result["status"] == "runtime_error"
    assert result["message"] == "browser failed"


def test_external_action_infers_url_for_navigation_schema() -> None:
    metadata = ToolMetadata(
        name="playwright__browser_navigate",
        server="playwright",
        tool_name="browser_navigate",
        capability="browser",
        description="Navigate to a URL",
        input_schema={"type": "object", "properties": {"url": {}}, "required": ["url"]},
    )

    result = JarvisToolGateway._infer_arguments("Please open youtube for me", metadata, {})

    assert result == {"url": "https://youtube.com"}


def test_external_action_infers_phone_query_from_schema() -> None:
    metadata = ToolMetadata(
        name="whatsapp__search_contacts",
        server="whatsapp",
        tool_name="search_contacts",
        capability="communication",
        description="Search contacts by name or phone number.",
        input_schema={"type": "object", "properties": {"query": {}}, "required": ["query"]},
    )

    result = JarvisToolGateway._infer_arguments(
        "Please get the contact +917358247423 from WhatsApp.", metadata, {}
    )

    assert result == {"query": "+917358247423"}


def test_external_action_infers_phone_for_identifier_schema() -> None:
    metadata = ToolMetadata(
        name="messaging__get_contact",
        server="messaging",
        tool_name="get_contact",
        capability="communication",
        description="Look up a contact by phone number.",
        input_schema={
            "type": "object",
            "properties": {"identifier": {}, "phone_number": {}, "phone": {}},
        },
    )

    result = JarvisToolGateway._infer_arguments(
        "Get contact +917358247423.", metadata, {}
    )

    assert result == {"phone_number": "+917358247423"}


@pytest.mark.asyncio
async def test_external_action_uses_url_shape_to_discover_navigation() -> None:
    execution = SimpleNamespace(
        execute=AsyncMock(return_value=ExecutionResult(status="success", content="opened"))
    )
    gateway = JarvisToolGateway(_registry(), execution)

    result = await gateway.external_action(
        "open_url", {"url": "https://example.com"}
    )

    assert result["ok"] is True
    assert result["tool_name"] == "playwright__browser_navigate"
    execution.execute.assert_awaited_once_with(
        "playwright__browser_navigate", {"url": "https://example.com"}
    )
