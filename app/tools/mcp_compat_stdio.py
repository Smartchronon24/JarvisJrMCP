"""MCP stdio adapter for the session-scoped Jarvis HTTP gateway."""

import asyncio
import json
import os
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP
from pydantic import Field


_URL = os.environ.get("JARVIS_GATEWAY_URL", "")
_TOKEN = os.environ.get("JARVIS_GATEWAY_TOKEN", "")
_mcp = FastMCP(
    "Jarvis Gateway",
    instructions=(
        "This server exposes the user's enabled Jarvis capabilities. "
        "For a request involving an external system, use external_action with "
        "the user's complete request. Do not refuse or ask for confirmation "
        "before checking the available capability. The gateway discovers the "
        "appropriate registered tool and maps obvious values from the request."
    ),
)


async def _request(operation: str, arguments: dict) -> str:
    if not _URL or not _TOKEN:
        raise RuntimeError("Jarvis gateway configuration is missing")
    payload = json.dumps(
        {"operation": operation, "arguments": arguments},
        ensure_ascii=True,
    ).encode("utf-8")

    def send() -> str:
        request = urllib.request.Request(
            _URL,
            data=payload,
            headers={
                "Authorization": "Bearer " + _TOKEN,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Jarvis gateway HTTP {exc.code}: {detail}") from exc

    return await asyncio.to_thread(send)


@_mcp.tool()
async def jarvis_search(query: str = "") -> str:
    """Find enabled Jarvis capabilities for external-world actions."""
    return await _request("search", {"query": query})


@_mcp.tool()
async def jarvis_execute(tool_name: str, arguments: dict) -> str:
    """Execute one previously discovered Jarvis capability tool."""
    return await _request(
        "execute",
        {"tool_name": tool_name, "arguments": arguments},
    )


@_mcp.tool()
async def external_action(
    request: str,
    arguments: dict = Field(default_factory=dict),
) -> str:
    """Perform an external action through Jarvis capabilities."""
    return await _request(
        "external_action",
        {"request": request, "arguments": arguments},
    )


def main() -> None:
    _mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
