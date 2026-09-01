from __future__ import annotations

import json
import asyncio
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.runtime.server import RuntimeServer


def test_claude_gateway_config_is_session_scoped_and_disposable(tmp_path: Path) -> None:
    transport = SimpleNamespace(
        create_session=lambda gateway: {"token": "session-token", "expires_in": 3600},
        revoke_session=lambda token: True,
    )
    agent = SimpleNamespace(
        execution_gateway=SimpleNamespace(
            tool_registry=object(),
        )
    )

    with patch("app.server.agent", agent), patch(
        "app.server.gateway_transport", transport
    ):
        token, config_path = RuntimeServer._create_claude_gateway_config()

    assert token == "session-token"
    assert config_path is not None
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    server = config["mcpServers"]["jarvis"]
    assert server["command"]
    assert server["env"]["JARVIS_GATEWAY_TOKEN"] == token
    assert "JARVIS_GATEWAY_URL" in server["env"]

    RuntimeServer._cleanup_gateway(
        SimpleNamespace(
            extra={
                "jarvis_gateway_token": token,
                "jarvis_mcp_config": config_path,
            }
        )
    )
    assert not Path(config_path).exists()


@pytest.mark.asyncio
async def test_real_stdio_bridge_calls_local_gateway() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length))
            assert self.headers["Authorization"] == "Bearer test-token"
            if payload["operation"] == "search":
                response = {
                    "ok": True,
                    "tools": [{"name": "test__echo", "description": "Echo"}],
                    "total_candidates": 1,
                }
            else:
                response = {
                    "ok": True,
                    "status": "success",
                    "content": "actual gateway result",
                    "is_error": False,
                }
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    http_server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    bridge = Path(__file__).resolve().parents[1] / "tools" / "mcp_gateway_stdio.py"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(bridge)],
        env={
            **os.environ,
            "JARVIS_GATEWAY_URL": f"http://127.0.0.1:{http_server.server_port}",
            "JARVIS_GATEWAY_TOKEN": "test-token",
        },
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                search = await session.call_tool("jarvis_search", {"query": "echo"})
                execute = await session.call_tool(
                    "jarvis_execute",
                    {"tool_name": "test__echo", "arguments": {}},
                )
                assert "test__echo" in search.content[0].text
                assert "actual gateway result" in execute.content[0].text
    finally:
        http_server.shutdown()
        await asyncio.sleep(0)
