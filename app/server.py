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
from app.agents.ollama_agent import JarvisAgent, validate_provider

agent = None
startup_error = None


async def startup():
    global agent, startup_error
    if not validate_provider():
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
# LLM Provider & Model Configuration API (Phase C.1)
# ---------------------------------------------------------------------------

async def get_llm_config(request):
    """
    GET /api/settings/llm
    Returns current provider/model config for all roles (router, worker, default).
    """
    from app.llm import get_model_config
    from app.llm.credentials import get_provider_api_key
    providers = {
        "ollama": {"configured": True, "requires_api_key": False, "local": True},
        "gemini": {"configured": bool(get_provider_api_key("gemini")), "requires_api_key": True, "local": False},
        "anthropic": {"configured": bool(get_provider_api_key("anthropic")), "requires_api_key": True, "local": False},
        "openai": {"configured": bool(get_provider_api_key("openai")), "requires_api_key": True, "local": False},
    }
    return JSONResponse({
        role: {"provider": get_model_config(role).provider, "model": get_model_config(role).model}
        for role in ("default", "router", "worker")
    } | {"providers": providers})


async def patch_llm_config(request):
    """
    PATCH /api/settings/llm/{role}
    Update provider and/or model for a given role at runtime.
    Body: { "provider": "gemini", "model": "gemini-2.0-flash" }
    """
    from app.llm import set_model_config, get_model_config
    role = request.path_params.get("role", "default")
    if role not in ("default", "router", "worker"):
        return JSONResponse({"error": f"Unknown role '{role}'. Must be: default, router, worker"}, status_code=400)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    current = get_model_config(role)
    provider = data.get("provider", current.provider)
    model = data.get("model", current.model)

    try:
        updated = set_model_config(role, provider=provider, model=model)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    print(f"[Config] LLM role '{role}' updated → provider={updated.provider}, model={updated.model}")
    return JSONResponse({"role": role, "provider": updated.provider, "model": updated.model})


async def get_provider_key_status(request):
    """
    GET /api/settings/keys
    Returns which providers have API keys set (boolean — never returns the key itself).
    """
    from app.llm.credentials import get_provider_api_key
    providers = ["gemini", "anthropic", "openai"]
    return JSONResponse({
        p: bool(get_provider_api_key(p))
        for p in providers
    })


async def set_provider_key(request):
    """
    POST /api/settings/keys/{provider}
    Store an API key for a provider. Body: { "key": "sk-..." }
    Key is written to the local credentials file — never logged.
    """
    from app.llm.credentials import set_provider_api_key
    provider = request.path_params.get("provider", "").strip().lower()
    allowed = {"gemini", "anthropic", "openai"}
    if provider not in allowed:
        return JSONResponse({"error": f"Unknown provider '{provider}'. Allowed: {sorted(allowed)}"}, status_code=400)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    key = data.get("key", "").strip()
    if not key:
        return JSONResponse({"error": "key must not be empty"}, status_code=400)

    set_provider_api_key(provider, key)
    print(f"[Config] API key for '{provider}' updated.")  # intentionally do NOT log the key value
    return JSONResponse({"provider": provider, "key_set": True})


async def list_llm_models(request):
    """
    GET /api/settings/llm/models?provider=ollama
    List available models for a given provider.
    """
    from app.llm import get_provider, ProviderError
    provider_name = request.query_params.get("provider", "ollama")
    try:
        provider = get_provider(provider_name)
        models = provider.list_models()
        return JSONResponse({"provider": provider_name, "models": models})
    except ProviderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# ---------------------------------------------------------------------------
# Bookkeeping REST API (Phase 6.2 — Hard Tasks)
# Future UI plugs into these endpoints. No SQLite knowledge required.
# ---------------------------------------------------------------------------


async def get_usage_providers(request):
    """
    GET /api/usage/providers
    Returns quota status for all known providers in one call.
    """
    from app.bookkeeping.service import bookkeeping_service
    return JSONResponse(bookkeeping_service.get_all_providers_quota_status())


async def get_usage_provider(request):
    """
    GET /api/usage/providers/{provider}
    Returns quota status for a single provider with auto-period-advancement.
    """
    from app.bookkeeping.service import bookkeeping_service
    provider = request.path_params["provider"]
    return JSONResponse(bookkeeping_service.get_provider_usage(provider))


async def patch_usage_provider(request):
    """
    PATCH /api/usage/providers/{provider}
    Update quota_limit and/or period_start at runtime — no code change required.
    Body: { "quota_limit": 1000, "period_start": "2026-09-10", "baseline_used": 16 }
    """
    from app.bookkeeping.service import bookkeeping_service
    provider = request.path_params["provider"]
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    quota_limit = data.get("quota_limit")
    period_start = data.get("period_start")
    baseline_used = data.get("baseline_used")

    if quota_limit is not None and not isinstance(quota_limit, int):
        return JSONResponse({"error": "quota_limit must be an integer"}, status_code=400)
    if baseline_used is not None and (not isinstance(baseline_used, int) or baseline_used < 0):
        return JSONResponse({"error": "baseline_used must be a non-negative integer"}, status_code=400)

    result = bookkeeping_service.update_provider_quota(
        provider=provider,
        quota_limit=quota_limit,
        period_start=period_start,
        baseline_used=baseline_used,
    )
    if "error" in result:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


async def get_usage_providers_recent(request):
    """
    GET /api/usage/providers/{provider}/recent?limit=50
    Recent individual operations for a provider (timeline view).
    """
    from app.bookkeeping.service import bookkeeping_service
    provider = request.path_params.get("provider")
    try:
        limit = int(request.query_params.get("limit", 50))
    except ValueError:
        limit = 50
    return JSONResponse(bookkeeping_service.get_recent_provider_usage(provider=provider, limit=limit))


async def get_usage_providers_period(request):
    """
    GET /api/usage/providers/{provider}/period?from=YYYY-MM-DD&to=YYYY-MM-DD
    Arbitrary date-range usage query for a provider.
    """
    from app.bookkeeping.service import bookkeeping_service
    provider = request.path_params["provider"]
    from_date = request.query_params.get("from")
    to_date = request.query_params.get("to")

    if not from_date:
        return JSONResponse({"error": "Missing 'from' query parameter"}, status_code=400)

    return JSONResponse(bookkeeping_service.get_usage_for_period(provider, from_date, to_date))


async def get_usage_llm(request):
    """
    GET /api/usage/llm
    Aggregate summary of LLM usage by role (router/worker/fallback) and model.
    """
    from app.bookkeeping.service import bookkeeping_service
    return JSONResponse(bookkeeping_service.get_llm_usage_summary())


async def get_usage_llm_recent(request):
    """
    GET /api/usage/llm/recent?role=router&limit=50
    Recent individual LLM invocations, optionally filtered by role.
    """
    from app.bookkeeping.service import bookkeeping_service
    role = request.query_params.get("role")
    try:
        limit = int(request.query_params.get("limit", 50))
    except ValueError:
        limit = 50
    return JSONResponse(bookkeeping_service.get_recent_llm_usage(role=role, limit=limit))




# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend" / "src"

routes = [
    Route("/", endpoint=root_redirect),
    Route("/api/messages", endpoint=get_messages, methods=["GET"]),
    Route("/api/status", endpoint=get_status, methods=["GET"]),
    Route("/api/chat", endpoint=post_chat, methods=["POST"]),
    Route("/api/chat/stream", endpoint=stream_chat, methods=["POST"]),
    Route("/api/chat/cancel", endpoint=cancel_chat, methods=["POST"]),
    Route("/api/settings/mcp", endpoint=get_mcp_settings, methods=["GET"]),
    Route("/api/settings/mcp", endpoint=post_mcp_settings, methods=["POST"]),
    # LLM Provider & Model Configuration (Phase C.1)
    Route("/api/settings/llm", endpoint=get_llm_config, methods=["GET"]),
    Route("/api/settings/llm/models", endpoint=list_llm_models, methods=["GET"]),
    Route("/api/settings/llm/{role}", endpoint=patch_llm_config, methods=["PATCH"]),
    Route("/api/settings/keys", endpoint=get_provider_key_status, methods=["GET"]),
    Route("/api/settings/keys/{provider}", endpoint=set_provider_key, methods=["POST"]),
    # Bookkeeping API (Phase 6.2)
    Route("/api/usage/providers", endpoint=get_usage_providers, methods=["GET"]),
    Route("/api/usage/providers/{provider}", endpoint=get_usage_provider, methods=["GET"]),
    Route("/api/usage/providers/{provider}", endpoint=patch_usage_provider, methods=["PATCH"]),
    Route("/api/usage/providers/{provider}/recent", endpoint=get_usage_providers_recent, methods=["GET"]),
    Route("/api/usage/providers/{provider}/period", endpoint=get_usage_providers_period, methods=["GET"]),
    Route("/api/usage/llm", endpoint=get_usage_llm, methods=["GET"]),
    Route("/api/usage/llm/recent", endpoint=get_usage_llm_recent, methods=["GET"]),
    Mount("/", app=StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static"),
]


app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, log_level="info")
