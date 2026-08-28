"""
Jarvis MCP Test Harness
=======================
A reusable interactive CLI that connects to one or more MCP servers,
discovers their tools dynamically, and uses Ollama as the reasoning layer.

To add a new MCP server later, just add an entry to MCP_SERVERS in config/settings.py.
"""

import asyncio
import json
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

# Ensure UTF-8 output on Windows so unicode characters in banners work correctly.
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Load .env file if present before settings are imported.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment variables

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.llm import ProviderError, get_model_config, get_provider
from app.tools import tool_registry
from app.tools.models import ToolSnapshot
from app.tools.selector import selector

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from config.settings import OLLAMA_STREAM, MCP_SERVERS, SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Tool name collision prevention:
# If two servers expose a tool with the same name, we prefix with server name.
# e.g.  memory__create_entities
# ---------------------------------------------------------------------------

def _tool_key(server_name: str, tool_name: str) -> str:
    """Create a unique tool identifier scoped to a server."""
    return f"{server_name}__{tool_name}"


def _parse_tool_key(tool_key: str):
    """Split a scoped tool key back into (server_name, tool_name)."""
    parts = tool_key.split("__", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, tool_key


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------

class JarvisAgent:
    def __init__(self):
        model_config = get_model_config("default")
        self.model = model_config.model
        self.provider = get_provider(model_config.provider)
        self.sessions: dict[str, ClientSession] = {}   # server_name → session
        self.tool_map: dict[str, tuple[str, any]] = {} # scoped_tool_key → (server_name, mcp_tool)
        self.llm_tools: list[dict] = []                # full provider-formatted tools
        self.enabled_mcps: set[str] = set()            # which servers are currently enabled
        self.conversation: list[dict] = [              # message history
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self._exit_stack = AsyncExitStack()
        self._cancel_requested = False  # set True to stop current generation

    def request_cancel(self):
        """Signal the current streaming generation to stop after the next token."""
        self._cancel_requested = True

    def clear_cancel(self):
        self._cancel_requested = False

    # ------------------------------------------------------------------
    # MCP enable/disable policy
    # ------------------------------------------------------------------

    def set_mcp_enabled(self, server_name: str, enabled: bool):
        """
        Enable or disable an MCP server at runtime.
        This is the authoritative policy layer — disabled MCPs have their
        tools removed from the LLM's tool list entirely. The LLM cannot
        call, see, or infer the existence of disabled tools.
        """
        if enabled:
            self.enabled_mcps.add(server_name)
        else:
            self.enabled_mcps.discard(server_name)
        # TR-1: keep registry in sync with runtime policy
        tool_registry.set_server_enabled(server_name, enabled)

    def get_active_tools(self) -> list[dict]:
        """
        Return only the tool definitions for currently-enabled MCP tools.
        This uses the deterministic selector to narrow tools based on the latest user request.
        """
        # If there is no prior user message, fall back to returning all enabled tools.
        if len(self.conversation) < 2:
            snapshot = tool_registry.create_snapshot()
            active = []
            for meta in snapshot.tools:
                entry = self.tool_map.get(meta.name)
                if entry:
                    server_name, mcp_tool = entry
                    active.append(self.provider.format_tool(server_name, mcp_tool))
            return active or None

        # Extract the last user message (role == "user")
        last_user_msg = next(
            (msg["content"] for msg in reversed(self.conversation) if msg["role"] == "user"),
            "",
        )
        # Use the deterministic selector to pick relevant tools.
        from app.tools.selector import selector
        selected_names = selector.select(last_user_msg)
        # If selector could not narrow (empty list), fall back to capability‑filtered set.
        if not selected_names:
            # Fallback: use all enabled tools (same as earlier fallback).
            snapshot = tool_registry.create_snapshot()
            active = []
            for meta in snapshot.tools:
                entry = self.tool_map.get(meta.name)
                if entry:
                    server_name, mcp_tool = entry
                    active.append(self.provider.format_tool(server_name, mcp_tool))
            return active or None
        active = []
        for name in selected_names:
            entry = self.tool_map.get(name)
            if entry:
                server_name, mcp_tool = entry
                active.append(self.provider.format_tool(server_name, mcp_tool))
        return active or None

    def get_mcp_policy(self) -> dict[str, bool]:
        """Return a dict of {server_name: enabled} for all known servers."""
        all_servers = set(self.sessions.keys())
        return {srv: (srv in self.enabled_mcps) for srv in all_servers}

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def connect_servers(self):
        """Start all configured MCP servers and discover their tools."""
        await self._exit_stack.__aenter__()

        connected = []
        failed = []

        for server_name, config in MCP_SERVERS.items():
            try:
                server_cwd = config.get("cwd")
                if server_cwd:
                    Path(server_cwd).mkdir(parents=True, exist_ok=True)

                params = StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env"),
                    cwd=server_cwd,
                )
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self.sessions[server_name] = session
                connected.append(server_name)
            except Exception as exc:
                print(f"  [ERROR] Failed to start '{server_name}': {exc}")
                failed.append(server_name)
                # TR-1: mark any pre-existing registry entries as unavailable
                tool_registry.set_server_available(server_name, False)

        # Discover tools from every connected server
        for server_name in connected:
            try:
                result = await self.sessions[server_name].list_tools()
                for tool in result.tools:
                    key = _tool_key(server_name, tool.name)
                    self.tool_map[key] = (server_name, tool)
                    self.llm_tools.append(self.provider.format_tool(server_name, tool))
                    # TR-1: register into the canonical tool catalog
                    tool_registry.register_mcp_tool(server_name, tool, available=True)
            except Exception as exc:
                print(f"  [ERROR] Failed to list tools for '{server_name}': {exc}")

        # All connected servers are enabled by default
        self.enabled_mcps = set(connected)

        return connected, failed

    async def shutdown(self):
        await self._exit_stack.__aexit__(None, None, None)

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def execute_tool(self, scoped_name: str, arguments: dict) -> str:
        """Route a tool call to the correct MCP server and return the result."""
        mapped = self.tool_map.get(scoped_name)
        if mapped is None:
            return f"[Error] Unknown tool: {scoped_name}"

        server_name, mcp_tool = mapped
        _, real_tool_name = _parse_tool_key(scoped_name)

        # --- MCP policy guard: refuse tools from disabled servers ---
        if server_name not in self.enabled_mcps:
            msg = f"[Policy] MCP server '{server_name}' is currently disabled."
            print(f"  [MCP] {msg}")
            return msg
        
        # --- Strict Validation ---
        input_schema = (
            getattr(mcp_tool, "input_schema", None)
            or getattr(mcp_tool, "inputSchema", None)
            or {}
        )
        required_fields = input_schema.get("required", [])
        missing = [f for f in required_fields if f not in arguments]
        if missing:
            error_msg = f"[Validation Error] Missing required arguments for {real_tool_name}: {missing}"
            print(f"  [MCP] Status  : VALIDATION FAILED")
            print(f"  [MCP] Result  : {error_msg}")
            return error_msg
        # -------------------------

        session = self.sessions.get(server_name)
        if session is None:
            return f"[Error] Server '{server_name}' is not connected."

        print(f"  [MCP] Server  : {server_name}")
        print(f"  [MCP] Tool    : {real_tool_name}")
        print(f"  [MCP] Args    : {json.dumps(arguments, indent=2)}")

        try:
            t0 = time.time()
            result = await session.call_tool(real_tool_name, arguments)
            duration_ms = int((time.time() - t0) * 1000)
            result_is_error = bool(
                getattr(result, "is_error", None)
                if hasattr(result, "is_error")
                else getattr(result, "isError", False)
            )

            # Record provider usage for Exa, Tavily, Firecrawl
            if server_name in ("exa", "tavily", "firecrawl"):
                actual_count = 1
                metadata_str = None
                
                # Attempt to extract actual usage from result if it's JSON structured
                if not result_is_error and result.content:
                    try:
                        for item in result.content:
                            if hasattr(item, "text"):
                                try:
                                    parsed = json.loads(item.text)
                                    if isinstance(parsed, dict):
                                        # Look for common usage fields
                                        usage_data = parsed.get("usage") or parsed.get("metadata", {}).get("usage")
                                        if isinstance(usage_data, dict) and "credits" in usage_data:
                                            actual_count = int(usage_data["credits"])
                                        elif "api_requests" in parsed:
                                            actual_count = int(parsed["api_requests"])
                                        metadata_str = json.dumps(parsed.get("metadata", {}))
                                except json.JSONDecodeError:
                                    pass
                    except Exception:
                        pass

                from app.bookkeeping.service import bookkeeping_service
                bookkeeping_service.record_provider_usage(
                    provider=server_name,
                    operation=real_tool_name,
                    success=not result_is_error,
                    request_count=actual_count,
                    estimated_count=1,
                    duration_ms=duration_ms,
                    error_info=str(result.content) if result_is_error else None,
                    metadata=metadata_str,
                )

            # Extract a clean text result
            if result_is_error:
                content_str = f"[Tool error] {result.content}"
                print(f"  [MCP] Status  : ERROR")
                print(f"  [MCP] Result  : {content_str}")
            elif result.content:
                parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                    else:
                        parts.append(str(item))
                content_str = "\n".join(parts)
                print(f"  [MCP] Status  : completed")
                print(f"  [MCP] Result  : {content_str[:200]}{'...' if len(content_str) > 200 else ''}")
            else:
                content_str = "(no content returned)"
                print(f"  [MCP] Status  : completed (empty response)")

            return content_str

        except Exception as exc:
            print(f"  [MCP] Status  : FAILED — {exc}")
            return f"[Tool execution failed] {exc}"

    # ------------------------------------------------------------------
    # LLM turn
    # ------------------------------------------------------------------

    async def chat(self, user_message: str) -> str:
        """Send a message, handle any tool calls, stream the reply to stdout."""
        self.conversation.append({"role": "user", "content": user_message})

        print("\n  [LLM] Processing request...")

        first_reply = True   # print the "Jarvis: " prefix once before streaming

        # Agentic loop: keep calling the configured provider until it returns a plain reply
        while True:
            tools_payload = self.get_active_tools()
            try:
                response = self.provider.chat(
                    model=self.model,
                    messages=self.conversation,
                    tools=tools_payload,
                    stream=OLLAMA_STREAM,
                )
            except ProviderError as exc:
                # Some models (e.g. vision models) reject requests that include
                # a tools field entirely. Detect this and retry without tools.
                if not exc.supports_tools and tools_payload:
                    print("  [LLM] Model does not support tools — retrying without tool definitions.")
                    try:
                        response = self.provider.chat(
                            model=self.model,
                            messages=self.conversation,
                            tools=None,
                            stream=OLLAMA_STREAM,
                        )
                    except ProviderError as exc2:
                        print(f"  [LLM] [{self.provider.name} error] {exc2}")
                        return ""
                else:
                    print(f"  [LLM] [{self.provider.name} error] {exc}")
                    return ""

            content = ""
            tool_calls = []

            if OLLAMA_STREAM:
                # Streaming: iterate over chunks
                for chunk in response:
                    if chunk.message.content:
                        if first_reply and not tool_calls:
                            print("\nJarvis: ", end="", flush=True)
                            first_reply = False
                        print(chunk.message.content, end="", flush=True)
                        content += chunk.message.content
                    if chunk.message.tool_calls:
                        for tc in chunk.message.tool_calls:
                            tool_calls.append(tc)
                if content:
                    print()  # newline after streamed content
            else:
                # Non-streaming: single response object
                content = response.message.content or ""
                tool_calls = response.message.tool_calls or []
                if content and not tool_calls:
                    print(f"\nJarvis: {content}")

            # --- Tool calls requested? ---
            if tool_calls:
                # Build the assistant entry; only include content if non-empty
                assistant_entry: dict = {"role": "assistant"}
                if content:
                    assistant_entry["content"] = content
                assistant_entry["tool_calls"] = [
                    {
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    }
                    for tc in tool_calls
                ]
                self.conversation.append(assistant_entry)
                # Execute each tool and append results
                for tc in tool_calls:
                    scoped_name = tc.function.name
                    arguments = tc.function.arguments or {}

                    print(f"\n  [LLM] Requesting tool: {scoped_name}")
                    tool_result = await self.execute_tool(scoped_name, arguments)

                    self.conversation.append({
                        "role": "tool",
                        "content": tool_result,
                    })
                # Reset flag so the final reply also gets the prefix
                first_reply = True
                print("\n  [LLM] Generating response...")
                continue

            # --- Plain reply ---
            reply = content.strip()
            self.conversation.append({"role": "assistant", "content": reply})
            return reply

    # ------------------------------------------------------------------
    # Hard 4: Fallback stream — original single-agent execution path
    # Used when the Router is unavailable or returns an irrecoverable error
    # ------------------------------------------------------------------

    async def _fallback_stream(self):
        """
        Original single-agent execution path.
        Uses all currently-enabled MCPs (via get_active_tools()) and the
        configured OLLAMA_MODEL, bypassing the Router/Worker layer entirely.
        This preserves existing Jarvis functionality when the Router fails.
        """
        print(f"\n[JARVIS] Running in single-agent fallback mode with {self.provider.name} model: {self.model}")
        loop_index = 0
        MAX_LOOPS = 20

        while loop_index < MAX_LOOPS:
            loop_index += 1
            tools_payload = self.get_active_tools()
            print(f"[JARVIS] Available tools for fallback: {[t['function']['name'] for t in tools_payload] if tools_payload else []}")

            try:
                response = self.provider.chat(
                    model=self.model,
                    messages=self.conversation,
                    tools=tools_payload,
                    stream=True,
                )
            except ProviderError as exc:
                if not exc.supports_tools and tools_payload:
                    try:
                        response = self.provider.chat(
                            model=self.model,
                            messages=self.conversation,
                            tools=None,
                            stream=True,
                        )
                    except Exception as exc2:
                        yield {"type": "request_error", "agent": "jarvis", "error": str(exc2)}
                        return
                else:
                    yield {"type": "request_error", "agent": "jarvis", "error": str(exc)}
                    return
            except Exception as exc:
                yield {"type": "request_error", "agent": "jarvis", "error": str(exc)}
                return

            content = ""
            tool_calls = []
            emitted_assistant_start = False

            self.clear_cancel()
            cancelled = False
            t0 = time.time()
            p_tokens, c_tokens = None, None

            for chunk in response:
                if self._cancel_requested:
                    cancelled = True
                    break
                
                # Extract tokens from chunk if available
                p_eval = getattr(chunk, "prompt_eval_count", None)
                if p_eval is not None:
                    p_tokens = p_eval
                c_eval = getattr(chunk, "eval_count", None)
                if c_eval is not None:
                    c_tokens = c_eval

                delta = chunk.message.content or ""
                if delta:
                    if not emitted_assistant_start:
                        yield {"type": "assistant_start", "agent": "jarvis"}
                        emitted_assistant_start = True
                    content += delta
                    yield {"type": "assistant_delta", "agent": "jarvis", "content": delta}
                if chunk.message.tool_calls:
                    for tc in chunk.message.tool_calls:
                        tool_calls.append(tc)

            duration_ms = int((time.time() - t0) * 1000)
            t_tokens = (p_tokens + c_tokens) if (p_tokens is not None and c_tokens is not None) else None

            from app.bookkeeping.service import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=self.model,
                role="fallback",
                provider=self.provider.name,
                success=True,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                duration_ms=duration_ms
            )

            if cancelled:
                reply = content.strip()
                if reply:
                    self.conversation.append({"role": "assistant", "content": reply})
                if emitted_assistant_start:
                    yield {"type": "assistant_complete", "agent": "jarvis"}
                yield {"type": "request_complete", "agent": "jarvis", "cancelled": True}
                return

            if tool_calls:
                assistant_entry: dict = {"role": "assistant"}
                if content:
                    assistant_entry["content"] = content
                assistant_entry["tool_calls"] = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
                self.conversation.append(assistant_entry)

                for tc in tool_calls:
                    scoped_name = tc.function.name
                    arguments = tc.function.arguments or {}
                    parts = scoped_name.split("__", 1)
                    server_name = parts[0] if len(parts) == 2 else scoped_name
                    real_tool_name = parts[1] if len(parts) == 2 else scoped_name

                    exec_id = f"exec-{id(tc)}"
                    yield {
                        "type": "tool_call_start",
                        "agent": "jarvis",
                        "id": exec_id,
                        "server": server_name,
                        "tool": real_tool_name,
                        "arguments": arguments,
                    }

                    print(f"\n[JARVIS] Fallback Tool call:")
                    print(f"        {scoped_name} with args: {arguments}")

                    try:
                        result = await self.execute_tool(scoped_name, arguments)
                        self.conversation.append({"role": "tool", "content": result})
                        
                        result_str = str(result)
                        if len(result_str) > 200:
                            result_str = result_str[:200] + "... [truncated]"
                        print(f"[JARVIS] Fallback Tool result:")
                        print(f"        {result_str}")

                        yield {
                            "type": "tool_call_result",
                            "agent": "jarvis",
                            "id": exec_id,
                            "server": server_name,
                            "tool": real_tool_name,
                            "result": result,
                        }
                    except Exception as exc:
                        error_msg = str(exc)
                        print(f"\n[JARVIS] Fallback Tool execution failed: {scoped_name} - {error_msg}")
                        self.conversation.append({"role": "tool", "content": f"[Error] {error_msg}"})
                        yield {
                            "type": "tool_call_error",
                            "agent": "jarvis",
                            "id": exec_id,
                            "server": server_name,
                            "tool": real_tool_name,
                            "error": error_msg,
                        }

                continue

            reply = content.strip()
            self.conversation.append({"role": "assistant", "content": reply})
            if emitted_assistant_start:
                yield {"type": "assistant_complete", "agent": "jarvis"}
            yield {"type": "request_complete", "agent": "jarvis"}
            print(f"\n[JARVIS] Fallback stream completed")
            print(f"[JARVIS] Final response generated")
            print("="*50 + "\n")
            return

        print(f"\n[JARVIS] Fallback stream completed (Max loops exceeded)")
        print("="*50 + "\n")
        yield {"type": "request_error", "agent": "jarvis", "error": "Max tool-call loops exceeded."}
        yield {"type": "request_complete", "agent": "jarvis"}


    # ------------------------------------------------------------------
    # Streaming LLM turn — yields structured events for SSE delivery
    # ------------------------------------------------------------------

    async def chat_stream(self, user_message: str):
        """
        Async generator that yields structured event dicts.

        Event types emitted:
          request_start
          assistant_start
          assistant_delta   { content: str }
          tool_call_start   { id, server, tool, arguments }
          tool_call_result  { id, server, tool, result }
          tool_call_error   { id, server, tool, error }
          assistant_complete
          request_complete
          request_error     { error: str }
        """
        from app.agents.multi_agent import Router, CAPABILITY_REGISTRY, Worker, ROUTER_FAILED

        print("\n" + "="*50)
        print("[JARVIS] New request")
        print(f"[JARVIS] User: {user_message!r}")

        self.conversation.append({"role": "user", "content": user_message})
        yield {"type": "request_start", "agent": "jarvis"}

        # -----------------------------------------------------------------------
        # Medium 1: Run Router to classify the request
        # -----------------------------------------------------------------------
        yield {
            "type": "tool_call_start",
            "agent": "router",
            "id": "router_1",
            "server": "router",
            "tool": "analyze_request",
            "arguments": {"message": user_message}
        }

        router = Router()
        print(f"\n[ROUTER] Starting")
        print(f"[ROUTER] Model: {router.model}")
        decision = await router.route(user_message, self.conversation)

        # -----------------------------------------------------------------------
        # Hard 4: Fallback — if Router failed, run single-agent with all enabled tools
        # -----------------------------------------------------------------------
        if decision is ROUTER_FAILED or decision.get("_router_failed"):
            print(f"\n[ROUTER] Decision: ROUTER_FAILED (fallback triggered)")
            yield {
                "type": "tool_call_error",
                "agent": "router",
                "id": "router_1",
                "server": "router",
                "tool": "analyze_request",
                "error": "Router unavailable — falling back to single-agent execution."
            }
            # Fall back to full single-agent execution (original behaviour)
            async for event in self._fallback_stream():
                yield event
            return

        print(f"[ROUTER] Decision:")
        print(f"        task_type: {decision.get('task_type')}")
        print(f"        action: {decision.get('action')}")
        print(f"        capabilities: {decision.get('capabilities')}")
        print(f"        response: {decision.get('response')}")
        print(f"        worker_instruction: {decision.get('worker_instruction')}")
        print(f"        reason: {decision.get('reason')}")

        yield {
            "type": "tool_call_result",
            "agent": "router",
            "id": "router_1",
            "server": "router",
            "tool": "analyze_request",
            "result": decision
        }

        if decision.get("action") == "respond":
            response_text = decision["response"]
            print("[ROUTER] Decision: direct_response")
            self.conversation.append({"role": "assistant", "content": response_text})
            yield {"type": "assistant_start", "agent": "jarvis"}
            if response_text:
                yield {"type": "assistant_delta", "agent": "jarvis", "content": response_text}
            yield {"type": "assistant_complete", "agent": "jarvis"}
            yield {"type": "request_complete", "agent": "jarvis"}
            return

        # -----------------------------------------------------------------------
        # TR-3: Resolve capabilities → Tool Snapshot → Worker tools
        #
        # Step 1: capability names → server names  (CAPABILITY_REGISTRY, unchanged)
        # Step 2: Create a ToolSnapshot from the Registry. The registry inherently
        #         filters out disabled tools and disabled servers.
        # Step 3: Map snapshot back to provider-formatted tools using tool_map.
        #         (MCP execution paths remain completely unchanged)
        # -----------------------------------------------------------------------
        requested_caps = decision.get("capabilities", [])
        resolved_servers: set[str] = set()
        for cap in requested_caps:
            if cap in CAPABILITY_REGISTRY:
                for mcp in CAPABILITY_REGISTRY[cap]["mcps"]:
                    resolved_servers.add(mcp)

        # TR-3: Create the immutable snapshot representing enabled tools for these servers
        search_query = decision.get("worker_instruction", user_message)
        discovered_tools = tool_registry.search_tools(
            search_query,
            servers=resolved_servers,
            enabled_only=True,
            available_only=True,
        )
        if not discovered_tools:
            print("[TOOL SEARCH] No metadata matches; using capability candidates.")
            candidate_snapshot = tool_registry.create_snapshot(servers=resolved_servers)
        else:
            candidate_snapshot = ToolSnapshot(tools=discovered_tools)
        selected_names = selector.select(
            search_query,
            candidates=candidate_snapshot.tools,
        )
        selected_set = set(selected_names)
        snapshot = ToolSnapshot(
            tools=[meta for meta in candidate_snapshot.tools if meta.name in selected_set]
        )

        # Boundary: ToolSnapshot -> provider format (using self.tool_map for raw tools)
        # tool_map is the execution-side lookup; we only reach through it here
        # to format tools for the LLM — actual MCP calls still use tool_map directly.
        worker = Worker(tools=[])
        allowed_tools: list[dict] = []
        for meta in snapshot.tools:
            entry = self.tool_map.get(meta.name)
            if entry is None:
                continue
            server_name, mcp_tool = entry
            allowed_tools.append(worker.provider.format_tool(server_name, mcp_tool))
            
        worker.tools = allowed_tools
        worker.allowed_tool_names = snapshot.tool_names

        print(f"\n[ORCHESTRATOR] Processing router decision")
        print(f"[ORCHESTRATOR] Selected capabilities: {requested_caps}")
        print(f"[ORCHESTRATOR] Enabled MCPs considered: {sorted(self.enabled_mcps)}")
        print(f"[ORCHESTRATOR] Selected MCPs: {sorted(resolved_servers)}")
        print(f"[ORCHESTRATOR] Registry-eligible tools: {len(snapshot)} (enabled_only=True)")
        print(f"[ORCHESTRATOR] Selected tools:")
        for t_def in allowed_tools:
            print(f"        - {t_def['function']['name']}")
        print(f"[ORCHESTRATOR] Creating worker")

        # -----------------------------------------------------------------------
        # Medium 5: Announce Worker initialisation to Activity pane
        # -----------------------------------------------------------------------
        yield {
            "type": "tool_call_start",
            "agent": "worker",
            "id": "worker_1",
            "server": "worker",
            "tool": "initialize",
            "arguments": {
                "task_type": decision.get("task_type"),
                "instruction": decision.get("worker_instruction"),
                "allowed_servers": sorted(resolved_servers)
            }
        }
        yield {
            "type": "tool_call_result",
            "agent": "worker",
            "id": "worker_1",
            "server": "worker",
            "tool": "initialize",
            "result": f"Worker initialised with {len(allowed_tools)} tool(s) from {sorted(resolved_servers)}."
        }

        # -----------------------------------------------------------------------
        # Medium 3: Build Worker with restricted tools
        # Hard 1: Worker.allowed_tool_names provides the enforcement lookup
        # -----------------------------------------------------------------------
        print(f"\n[WORKER] Starting")
        print(f"[WORKER] Model: {worker.model}")
        print(f"[WORKER] Available tools:")
        for t_name in sorted(worker.allowed_tool_names):
            print(f"        - {t_name}")

        worker_sys_prompt = worker.build_system_prompt(
            decision.get("worker_instruction") or user_message
        )

        loop_index = 0
        MAX_LOOPS = 20  # guard against runaway tool loops
        first_worker_turn = True

        while loop_index < MAX_LOOPS:
            loop_index += 1
            # Medium 3 / Hard 1: use ONLY the Worker's restricted tool list
            tools_payload = allowed_tools if allowed_tools else None

            # Inject Worker system prompt into a scoped conversation copy
            scoped_conversation = [
                {"role": "system", "content": self.conversation[0]["content"] + "\n\n" + worker_sys_prompt}
            ]
            scoped_conversation.extend(self.conversation[1:])

            # --- Call Ollama (stream=True for real-time token delivery) ---
            try:
                response = worker.provider.chat(
                    model=worker.model,
                    messages=scoped_conversation,
                    tools=tools_payload,
                    stream=True,
                )
            except ProviderError as exc:
                if not exc.supports_tools and tools_payload:
                    try:
                        response = worker.provider.chat(
                            model=worker.model,
                            messages=scoped_conversation,
                            tools=None,
                            stream=True,
                        )
                    except Exception as exc2:
                        yield {"type": "request_error", "agent": "jarvis", "error": str(exc2)}
                        return
                else:
                    yield {"type": "request_error", "agent": "jarvis", "error": str(exc)}
                    return
            except Exception as exc:
                yield {"type": "request_error", "agent": "jarvis", "error": str(exc)}
                return

            content = ""
            tool_calls = []
            emitted_assistant_start = False
            buffered_first_turn = first_worker_turn

            # --- Consume the streaming response synchronously (ollama lib is sync) ---
            self.clear_cancel()  # reset at start of each Ollama call
            cancelled = False
            t0 = time.time()
            p_tokens, c_tokens = None, None

            for chunk in response:
                if self._cancel_requested:
                    cancelled = True
                    break
                
                # Extract tokens from chunk if available
                p_eval = getattr(chunk, "prompt_eval_count", None)
                if p_eval is not None:
                    p_tokens = p_eval
                c_eval = getattr(chunk, "eval_count", None)
                if c_eval is not None:
                    c_tokens = c_eval

                delta = chunk.message.content or ""
                if delta:
                    content += delta
                    if not buffered_first_turn:
                        if not emitted_assistant_start:
                            yield {"type": "assistant_start", "agent": "jarvis"}
                            emitted_assistant_start = True
                        yield {"type": "assistant_delta", "agent": "jarvis", "content": delta}
                if chunk.message.tool_calls:
                    for tc in chunk.message.tool_calls:
                        tool_calls.append(tc)

            duration_ms = int((time.time() - t0) * 1000)
            t_tokens = (p_tokens + c_tokens) if (p_tokens is not None and c_tokens is not None) else None

            from app.bookkeeping.service import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=worker.model,
                role="worker",
                provider=worker.provider.name,
                success=True,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                duration_ms=duration_ms
            )

            if cancelled:
                reply = content.strip()
                if reply:
                    self.conversation.append({"role": "assistant", "content": reply})
                if emitted_assistant_start:
                    yield {"type": "assistant_complete", "agent": "jarvis"}
                yield {"type": "request_complete", "agent": "jarvis", "cancelled": True}
                return

            if buffered_first_turn:
                first_worker_turn = False
                content, plan_steps = worker.extract_plan(content)
                if plan_steps:
                    print(f"[WORKER PLAN] {' -> '.join(plan_steps)}")
                    yield {
                        "type": "plan_created",
                        "agent": "worker",
                        "id": "worker_plan_1",
                        "steps": plan_steps,
                    }
                if content:
                    yield {"type": "assistant_start", "agent": "jarvis"}
                    emitted_assistant_start = True
                    yield {"type": "assistant_delta", "agent": "jarvis", "content": content}

            # --- Tool calls ---
            if tool_calls:
                # Save assistant turn with tool_calls
                assistant_entry: dict = {"role": "assistant"}
                if content:
                    assistant_entry["content"] = content
                assistant_entry["tool_calls"] = [
                    {"function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
                self.conversation.append(assistant_entry)

                for tc in tool_calls:
                    scoped_name = tc.function.name
                    arguments = tc.function.arguments or {}
                    parts = scoped_name.split("__", 1)
                    server_name = parts[0] if len(parts) == 2 else scoped_name
                    real_tool_name = parts[1] if len(parts) == 2 else scoped_name

                    exec_id = f"exec-{id(tc)}"

                    # -----------------------------------------------------------
                    # Hard 1: Strict tool isolation — block any tool not in the
                    # Worker's explicitly allowed set (hallucination protection)
                    # -----------------------------------------------------------
                    if scoped_name not in worker.allowed_tool_names:
                        error_msg = (
                            f"Tool '{scoped_name}' is not in the Worker's allowed tool list. "
                            f"Allowed: {sorted(worker.allowed_tool_names)}. "
                            "This call has been blocked by the tool-isolation guard."
                        )
                        print(f"\n[WORKER] Tool call BLOCKED (Tool isolation guard): {scoped_name}")
                        self.conversation.append({"role": "tool", "content": f"[Blocked] {error_msg}"})
                        yield {
                            "type": "tool_call_error",
                            "agent": "worker",
                            "id": exec_id,
                            "server": server_name,
                            "tool": real_tool_name,
                            "error": error_msg,
                        }
                        continue

                    yield {
                        "type": "tool_call_start",
                        "agent": "worker",
                        "id": exec_id,
                        "server": server_name,
                        "tool": real_tool_name,
                        "arguments": arguments,
                    }

                    print(f"\n[WORKER] Tool call:")
                    print(f"        {scoped_name} with args: {arguments}")

                    try:
                        result = await self.execute_tool(scoped_name, arguments)
                        self.conversation.append({"role": "tool", "content": result})
                        
                        result_str = str(result)
                        if len(result_str) > 200:
                            result_str = result_str[:200] + "... [truncated]"
                        print(f"[WORKER] Tool result:")
                        print(f"        {result_str}")

                        yield {
                            "type": "tool_call_result",
                            "agent": "worker",
                            "id": exec_id,
                            "server": server_name,
                            "tool": real_tool_name,
                            "result": result,
                        }
                    except Exception as exc:
                        error_msg = str(exc)
                        print(f"\n[WORKER] Tool execution failed: {scoped_name} - {error_msg}")
                        self.conversation.append({"role": "tool", "content": f"[Error] {error_msg}"})
                        yield {
                            "type": "tool_call_error",
                            "agent": "worker",
                            "id": exec_id,
                            "server": server_name,
                            "tool": real_tool_name,
                            "error": error_msg,
                        }

                # Loop again to get the post-tool reply
                continue

            # --- Plain assistant reply, loop ends ---
            reply = content.strip()
            self.conversation.append({"role": "assistant", "content": reply})

            if emitted_assistant_start:
                yield {"type": "assistant_complete", "agent": "jarvis"}
            yield {"type": "request_complete", "agent": "jarvis"}
            print(f"\n[WORKER] Completed")
            print(f"\n[JARVIS] Final response generated")
            print("="*50 + "\n")
            return

        # Exceeded loop guard
        print(f"\n[WORKER] Completed (Max loops exceeded)")
        print(f"\n[JARVIS] Final response generated with error")
        print("="*50 + "\n")
        yield {"type": "request_error", "agent": "jarvis", "error": "Max tool-call loops exceeded."}
        yield {"type": "request_complete", "agent": "jarvis"}



# ---------------------------------------------------------------------------
# Startup banner & validation
# ---------------------------------------------------------------------------

def validate_provider():
    """
    Check the configured default provider is reachable.

    For Ollama: verifies the model is present in the local model list.
    For paid providers (gemini, anthropic, openai): just verifies the API key
    is set. We skip list_models() because paid providers do not require a
    local model pre-pull — an invalid model name will fail at first chat() call.
    """
    model_config = get_model_config("default")
    provider = get_provider(model_config.provider)

    # For paid providers, check the API key is present and skip list_models()
    if provider.name in ("gemini", "anthropic", "openai"):
        from app.llm.credentials import get_provider_api_key
        key = get_provider_api_key(provider.name)
        if not key:
            print(f"\n[WARNING] No API key found for provider '{provider.name}'.")
            print(f"          Set {provider.name.upper()}_API_KEY in .env or configure it via the UI.")
            print(f"          Jarvis will start but LLM calls will fail until a key is set.\n")
        else:
            print(f"[OK] Provider '{provider.name}' API key is set.")
        return True  # Allow startup even without a key — user may set it via UI

    # For Ollama: check model is available locally
    try:
        available = provider.list_models()
    except ProviderError as exc:
        print(f"\n[FATAL] Cannot reach {provider.name} provider: {exc}")
        return False

    if not any(model_config.model in model for model in available):
        print(f"\n[FATAL] Model '{model_config.model}' is not available from {provider.name}.")
        print(f"        Available models: {available}")
        print(f"        Configure an available {provider.name} model in app.llm.config.")
        return False

    return True


def print_banner(connected: list, failed: list, tool_map: dict):
    model_config = get_model_config("default")
    print("\n" + "=" * 50)
    print("         Jarvis MCP Test Harness")
    print("=" * 50)
    print(f"\n  Provider: {model_config.provider}")
    print(f"  Model  : {model_config.model}\n")

    print("  Connected MCP Servers:")
    for name in connected:
        print(f"    ✓ {name}")
    for name in failed:
        print(f"    ✗ {name}  (failed to start)")

    print("\n  Available MCP Tools:")
    for key, (server_name, mcp_tool) in tool_map.items():
        _, tool_name = _parse_tool_key(key)
        print(f"    ✓ {tool_name}  [{server_name}]")

    print("\n  Type your message and press Enter.")
    print("  Type  'exit'  or  'quit'  to stop.\n")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_agent():
    # 1. Validate Ollama before doing anything else
    if not validate_provider():
        return

    agent = JarvisAgent()

    print("\nStarting MCP servers...")
    connected, failed = await agent.connect_servers()

    if not connected:
        print("[FATAL] No MCP servers connected. Exiting.")
        await agent.shutdown()
        return

    print_banner(connected, failed, agent.tool_map)

    # 2. Interactive loop
    try:
        while True:
            try:
                user_input = input("Jarvis> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                print("Goodbye!")
                break

            await agent.chat(user_input)
            print()  # blank line after each reply for readability

    finally:
        await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(run_agent())
