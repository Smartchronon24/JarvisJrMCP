"""MCP stdio adapter for the session-scoped Jarvis HTTP gateway."""

import asyncio
import json
import os
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP


_URL = os.environ.get("JARVIS_GATEWAY_URL", "")
_TOKEN = os.environ.get("JARVIS_GATEWAY_TOKEN", "")
_mcp = FastMCP("Jarvis Gateway")


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
                "Authorization": f"Bearer {_TOKEN}",
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
    """Find enabled Jarvis capabilities for external-world actions.

    Use this before acting on messaging, browser, web, memory, or other
    connected-service requests. Do not inspect the repository to discover
    Jarvis capabilities.
    """
    return await _request("search", {"query": query})


@_mcp.tool()
async def jarvis_execute(tool_name: str, arguments: dict) -> str:
    """Execute one previously discovered Jarvis capability tool."""
    return await _request(
        "execute",
        {"tool_name": tool_name, "arguments": arguments},
    )


def main() -> None:
    _mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
