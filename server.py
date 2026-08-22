import os
import sys
import json
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
import uvicorn

# Import our JarvisAgent and validation
from ollama_agent import JarvisAgent, validate_ollama

agent = None
startup_error = None


async def startup():
    global agent, startup_error
    if not validate_ollama():
        startup_error = "Ollama is not reachable or the requested model is not available."
        print(f"[FATAL] {startup_error}")
        return

    agent = JarvisAgent()
    print("Connecting to MCP servers...")
    try:
        connected, failed = await agent.connect_servers()
        print(f"Connected servers: {connected}")
        if failed:
            print(f"Failed servers: {failed}")
    except Exception as e:
        startup_error = f"Failed to initialize MCP servers: {e}"
        print(f"[FATAL] {startup_error}")


async def shutdown():
    global agent
    if agent:
        await agent.shutdown()


async def get_mcp_settings(request):
    """Return current MCP enable/disable policy from the agent."""
    if not agent:
        return JSONResponse({})
    return JSONResponse(agent.get_mcp_policy())


async def post_mcp_settings(request):
    """
    Update MCP enable/disable policy on the backend.
    Body: { "server_name": "tavily", "enabled": false }
    The backend is authoritative — this is the real enforcement point.
    """
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=500)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    server_name = data.get("server_name", "").strip()
    enabled = data.get("enabled")

    if not server_name:
        return JSONResponse({"error": "Missing server_name"}, status_code=400)
    if enabled is None or not isinstance(enabled, bool):
        return JSONResponse({"error": "enabled must be a boolean"}, status_code=400)
    if server_name not in agent.sessions:
        return JSONResponse({"error": f"Unknown server: {server_name}"}, status_code=404)

    agent.set_mcp_enabled(server_name, enabled)
    print(f"[Policy] MCP '{server_name}' set to {'enabled' if enabled else 'disabled'}")
    return JSONResponse(agent.get_mcp_policy())


@asynccontextmanager
async def lifespan(app_obj):
    await startup()
    yield
    await shutdown()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def root_redirect(request):
    return RedirectResponse(url="/html/index.html")


async def get_messages(request):
    if startup_error:
        return JSONResponse({"error": startup_error}, status_code=500)
    if not agent:
        return JSONResponse([], status_code=200)

    ui_messages = []
    for msg in agent.conversation:
        role = msg["role"]
        if role == "system":
            continue
        # Skip tool result messages and assistant tool_calls entries (no text content)
        if role == "tool":
            continue
        content = msg.get("content") or ""
        if not content:
            continue
        ui_messages.append({
            "id": len(ui_messages) + 1,
            "role": role,
            "content": content,
            "timestamp": None
        })
    return JSONResponse(ui_messages)


async def get_status(request):
    if startup_error:
        return JSONResponse({"error": startup_error, "connected_servers": [], "mcp_servers": []})
    if not agent:
        return JSONResponse({"connected_servers": [], "mcp_servers": []})

    connected_servers = list(agent.sessions.keys())
    mcp_servers_status = []

    for server_name in connected_servers:
        tools = [
            mcp_tool.name
            for key, (srv_name, mcp_tool) in agent.tool_map.items()
            if srv_name == server_name
        ]
        mcp_servers_status.append({
            "id": server_name,
            "connected": True,
            "tools": tools
        })

    return JSONResponse({
        "connected_servers": connected_servers,
        "mcp_servers": mcp_servers_status
    })


async def post_chat(request):
    """Non-streaming chat — kept as fallback."""
    if startup_error:
        return JSONResponse({"error": startup_error}, status_code=500)
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=500)

    data = await request.json()
    message = data.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    try:
        reply = await agent.chat(message)
        return JSONResponse({"role": "assistant", "content": reply})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def stream_chat(request):
    """
    SSE streaming endpoint.

    POST /api/chat/stream  { "message": "..." }

    Returns an SSE stream of structured events:
      request_start, assistant_start, assistant_delta, assistant_complete,
      tool_call_start, tool_call_result, tool_call_error,
      request_complete, request_error
    """
    if startup_error:
        async def err_gen():
            yield {"data": json.dumps({"type": "request_error", "error": startup_error})}
        return EventSourceResponse(err_gen())

    if not agent:
        async def no_agent_gen():
            yield {"data": json.dumps({"type": "request_error", "error": "Agent not initialized"})}
        return EventSourceResponse(no_agent_gen())

    try:
        body = await request.body()
        data = json.loads(body)
    except Exception:
        async def bad_req():
            yield {"data": json.dumps({"type": "request_error", "error": "Invalid JSON body"})}
        return EventSourceResponse(bad_req())

    message = data.get("message", "").strip()
    if not message:
        async def empty_msg():
            yield {"data": json.dumps({"type": "request_error", "error": "Empty message"})}
        return EventSourceResponse(empty_msg())

    async def event_generator():
        try:
            async for event in agent.chat_stream(message):
                yield {"data": json.dumps(event)}
        except Exception as exc:
            yield {"data": json.dumps({"type": "request_error", "error": str(exc)})}
            yield {"data": json.dumps({"type": "request_complete", "agent": "jarvis"})}

    return EventSourceResponse(event_generator())


async def cancel_chat(request):
    """Signal the current streaming generation to stop."""
    if agent:
        agent.request_cancel()
        return JSONResponse({"cancelled": True})
    return JSONResponse({"cancelled": False})


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "jarvis-phase-2.1-frontend" / "src"

routes = [
    Route("/", endpoint=root_redirect),
    Route("/api/messages", endpoint=get_messages, methods=["GET"]),
    Route("/api/status", endpoint=get_status, methods=["GET"]),
    Route("/api/chat", endpoint=post_chat, methods=["POST"]),
    Route("/api/chat/stream", endpoint=stream_chat, methods=["POST"]),
    Route("/api/chat/cancel", endpoint=cancel_chat, methods=["POST"]),
    Route("/api/settings/mcp", endpoint=get_mcp_settings, methods=["GET"]),
    Route("/api/settings/mcp", endpoint=post_mcp_settings, methods=["POST"]),
    Mount("/", app=StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="info")
