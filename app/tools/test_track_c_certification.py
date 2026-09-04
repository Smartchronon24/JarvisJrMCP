"""C3-C6 deterministic tool-platform certification tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.execution import ToolExecutionGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry


@pytest.mark.parametrize(
    "server, capability, tool_name",
    [
        ("playwright", "browser", "navigate"),
        ("messaging", "communication", "send_message"),
        ("filesystem", "filesystem", "read_file"),
        ("terminal", "terminal", "run"),
        ("memory", "memory", "search"),
        ("exa", "web_research", "search"),
    ],
)
def test_representative_domain_tool_metadata_is_discoverable(server, capability, tool_name):
    registry = ToolRegistry()
    registry.register_tool(
        ToolMetadata(
            name=f"{server}__{tool_name}",
            server=server,
            tool_name=tool_name,
            capability=capability,
            description=f"Representative {capability} capability",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
    )

    matches = registry.search_tools(capability)

    assert [tool.name for tool in matches] == [f"{server}__{tool_name}"]


@pytest.mark.asyncio
async def test_execution_gateway_enforces_authorization_timeout_and_audit():
    registry = ToolRegistry()
    registry.register_tool(
        ToolMetadata(
            name="terminal__run",
            server="terminal",
            tool_name="run",
            capability="terminal",
            description="Run a command",
            input_schema={"required": ["command"]},
        )
    )
    session = MagicMock()
    session.call_tool = AsyncMock()
    result = MagicMock(is_error=False, content=[])
    session.call_tool.return_value = result
    audits = []
    gateway = ToolExecutionGateway(
        registry,
        {"terminal": session},
        {"terminal__run": ("terminal", object())},
        authorize=lambda tool, args: args.get("command") == "safe",
        audit=audits.append,
        timeout_seconds=1,
    )

    denied = await gateway.execute("terminal__run", {"command": "unsafe"})
    assert denied.error_type == "authorization_denied"
    allowed = await gateway.execute("terminal__run", {"command": "safe"})

    assert allowed.status == "success"
    assert any(event["event"] == "tool_execution_started" for event in audits)
    assert any(event["event"] == "tool_execution_completed" for event in audits)
