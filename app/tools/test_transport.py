from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.execution import ExecutionResult
from app.tools.gateway import JarvisToolGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.transport import GatewayTransport


def _gateway() -> JarvisToolGateway:
    registry = ToolRegistry()
    registry.register_tool(
        ToolMetadata(
            name="filesystem__read_file",
            server="filesystem",
            tool_name="read_file",
            capability="filesystem",
            description="Read a file",
            input_schema={"type": "object", "properties": {}},
        )
    )
    execution = SimpleNamespace(
        execute=AsyncMock(
            return_value=ExecutionResult(status="success", content="ok")
        )
    )
    return JarvisToolGateway(registry, execution)


@pytest.mark.asyncio
async def test_transport_search_and_execute() -> None:
    transport = GatewayTransport()
    token = transport.create_session(_gateway())["token"]

    search = await transport.dispatch(
        token, {"operation": "search", "arguments": {"query": "read file"}}
    )
    execute = await transport.dispatch(
        token,
        {
            "operation": "execute",
            "arguments": {
                "tool_name": "filesystem__read_file",
                "arguments": {},
            },
        },
    )

    assert search["ok"] is True
    assert search["tools"][0]["name"] == "filesystem__read_file"
    assert execute["status"] == "success"


@pytest.mark.asyncio
async def test_transport_rejects_invalid_operation_and_token() -> None:
    transport = GatewayTransport()
    with pytest.raises(PermissionError, match="invalid"):
        await transport.dispatch("invalid", {"operation": "search", "arguments": {}})

    token = transport.create_session(_gateway())["token"]
    with pytest.raises(ValueError, match="operation"):
        await transport.dispatch(token, {"operation": "delete", "arguments": {}})


@pytest.mark.asyncio
async def test_transport_rejects_stale_session() -> None:
    transport = GatewayTransport()
    token = transport.create_session(_gateway())["token"]
    assert transport.revoke_session(token) is True

    with pytest.raises(PermissionError, match="invalid"):
        await transport.dispatch(token, {"operation": "search", "arguments": {}})
