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

# Load .env file if present (e.g. UBER_CLIENT_ID etc.) before settings are imported.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment variables

from ollama import Client
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from config.settings import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_STREAM, MCP_SERVERS, SYSTEM_PROMPT

# Build the Ollama client: None → localhost default, URL string → remote endpoint
client = Client(host=OLLAMA_HOST) if OLLAMA_HOST else Client()

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
# MCP → Ollama tool schema conversion
# ---------------------------------------------------------------------------

def mcp_tool_to_ollama(server_name: str, mcp_tool) -> dict:
    """
    Convert an MCP tool definition to the dict format expected by Ollama's
    tool-calling API.
    """
    scoped_name = _tool_key(server_name, mcp_tool.name)

    # MCP tools carry a JSON Schema under input_schema
    input_schema = mcp_tool.input_schema or {}
    properties_raw = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    # Convert each property to Ollama's Property shape
    properties = {}
    for prop_name, prop_schema in properties_raw.items():
        properties[prop_name] = {
            "type": prop_schema.get("type", "string"),
            "description": prop_schema.get("description", ""),
        }
        # Preserve nested items for array types
        if "items" in prop_schema:
            properties[prop_name]["items"] = prop_schema["items"]

    return {
        "type": "function",
        "function": {
            "name": scoped_name,
            "description": mcp_tool.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ---------------------------------------------------------------------------
# Core agent
# ---------------------------------------------------------------------------

class JarvisAgent:
    def __init__(self):
        self.sessions: dict[str, ClientSession] = {}   # server_name → session
        self.tool_map: dict[str, tuple[str, any]] = {} # scoped_tool_key → (server_name, mcp_tool)
        self.ollama_tools: list[dict] = []             # full tool defs discovered at startup
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

    def get_active_tools(self) -> list[dict]:
        """
        Return only the tool definitions for currently-enabled MCP servers.
        This is what gets passed to Ollama — disabled servers are invisible.
        """
        active = []
        for tool_def in self.ollama_tools:
            scoped_name = tool_def["function"]["name"]
            server_name = scoped_name.split("__", 1)[0]
            if server_name in self.enabled_mcps:
                active.append(tool_def)
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

        # Discover tools from every connected server
        for server_name in connected:
            try:
                result = await self.sessions[server_name].list_tools()
                for tool in result.tools:
                    key = _tool_key(server_name, tool.name)
                    self.tool_map[key] = (server_name, tool)
                    self.ollama_tools.append(mcp_tool_to_ollama(server_name, tool))
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
        required_fields = mcp_tool.input_schema.get("required", []) if mcp_tool.input_schema else []
        missing = [f for f in required_fields if f not in arguments]
        if missing:
            error_msg = f"[Validation Error] Missing required arguments for {real_tool_name}: {missing}"
            print(f"  [MCP] Status  : VALIDATION FAILED")
            print(f"  [MCP] Result  : {error_msg}")
            return error_msg
        # -------------------------

        # --- Booking Safety Guard -----------------------------------------------
        # uber_request_ride must NEVER fire automatically based on LLM inference.
        # This gate runs in Python regardless of what the LLM decided.
        if real_tool_name == "uber_request_ride":
            print("\n" + "!" * 60)
            print("  [SAFETY] The LLM wants to call uber_request_ride.")
            print(f"  [SAFETY] Arguments: {json.dumps(arguments, indent=2)}")
            print("!" * 60)
            try:
                answer = input(
                    "\n  >>> Type YES (all caps) to confirm the ride request, "
                    "or anything else to cancel: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer != "YES":
                print("  [SAFETY] Ride request CANCELLED by user.")
                return "[Booking cancelled] The user did not confirm the ride request."
            print("  [SAFETY] User confirmed. Proceeding with uber_request_ride.\n")
        # ------------------------------------------------------------------------

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

            # Record provider usage for Exa, Tavily, Firecrawl
            if server_name in ("exa", "tavily", "firecrawl"):
                actual_count = 1
                metadata_str = None
                
                # Attempt to extract actual usage from result if it's JSON structured
                if not result.is_error and result.content:
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

                from bookkeeping import bookkeeping_service
                bookkeeping_service.record_provider_usage(
                    provider=server_name,
                    operation=real_tool_name,
                    success=not result.is_error,
                    request_count=actual_count,
                    estimated_count=1,
                    duration_ms=duration_ms,
                    error_info=str(result.content) if result.is_error else None,
                    metadata=metadata_str,
                )

            # Extract a clean text result
            if result.is_error:
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

        # Agentic loop: keep calling Ollama until it returns a plain reply
        while True:
            tools_payload = self.get_active_tools()
            try:
                response = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=self.conversation,
                    tools=tools_payload,
                    stream=OLLAMA_STREAM,
                )
            except ollama.ResponseError as exc:
                # Some models (e.g. vision models) reject requests that include
                # a tools field entirely. Detect this and retry without tools.
                if "does not support tools" in str(exc) and tools_payload:
                    print("  [LLM] Model does not support tools — retrying without tool definitions.")
                    try:
                        response = ollama.chat(
                            model=OLLAMA_MODEL,
                            messages=self.conversation,
                            tools=None,
                            stream=OLLAMA_STREAM,
                        )
                    except Exception as exc2:
                        print(f"  [LLM] [Ollama error] {exc2}")
                        return ""
                else:
                    print(f"  [LLM] [Ollama error] {exc}")
                    return ""
            except Exception as exc:
                print(f"  [LLM] [Unexpected error talking to Ollama] {exc}")
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
        print(f"\n[JARVIS] Running in single-agent fallback mode with OLLAMA_MODEL: {OLLAMA_MODEL}")
        loop_index = 0
        MAX_LOOPS = 20

        while loop_index < MAX_LOOPS:
            loop_index += 1
            tools_payload = self.get_active_tools()
            print(f"[JARVIS] Available tools for fallback: {[t['function']['name'] for t in tools_payload] if tools_payload else []}")

            try:
                response = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=self.conversation,
                    tools=tools_payload,
                    stream=True,
                )
            except ollama.ResponseError as exc:
                if "does not support tools" in str(exc) and tools_payload:
                    try:
                        response = ollama.chat(
                            model=OLLAMA_MODEL,
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

            from bookkeeping import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=OLLAMA_MODEL,
                role="fallback",
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
        from multi_agent import Router, CAPABILITY_REGISTRY, Worker, ROUTER_FAILED

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
        # Medium 2: Resolve capabilities → enabled MCP servers → actual tools
        # Hard 2: Enforce disabled MCPs by intersecting with self.enabled_mcps
        # Hard 3: Unknown capabilities have already been stripped by validate_decision()
        # -----------------------------------------------------------------------
        requested_caps = decision.get("capabilities", [])
        resolved_servers: set[str] = set()
        for cap in requested_caps:
            if cap in CAPABILITY_REGISTRY:
                for mcp in CAPABILITY_REGISTRY[cap]["mcps"]:
                    resolved_servers.add(mcp)

        # Hard 2: only servers the user has actually enabled
        allowed_servers = resolved_servers.intersection(self.enabled_mcps)

        # Medium 2: resolve actual tool defs for allowed servers
        allowed_tools: list[dict] = []
        for tool_def in self.ollama_tools:
            server_name = tool_def["function"]["name"].split("__", 1)[0]
            if server_name in allowed_servers:
                allowed_tools.append(tool_def)

        print(f"\n[ORCHESTRATOR] Processing router decision")
        print(f"[ORCHESTRATOR] Selected capabilities: {requested_caps}")
        print(f"[ORCHESTRATOR] Enabled MCPs considered: {sorted(self.enabled_mcps)}")
        print(f"[ORCHESTRATOR] Selected MCPs: {sorted(allowed_servers)}")
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
                "allowed_servers": sorted(allowed_servers)
            }
        }
        yield {
            "type": "tool_call_result",
            "agent": "worker",
            "id": "worker_1",
            "server": "worker",
            "tool": "initialize",
            "result": f"Worker initialised with {len(allowed_tools)} tool(s) from {sorted(allowed_servers)}."
        }

        # -----------------------------------------------------------------------
        # Medium 3: Build Worker with restricted tools
        # Hard 1: Worker.allowed_tool_names provides the enforcement lookup
        # -----------------------------------------------------------------------
        worker = Worker(tools=allowed_tools)
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
                response = ollama.chat(
                    model=worker.model,
                    messages=scoped_conversation,
                    tools=tools_payload,
                    stream=True,
                )
            except ollama.ResponseError as exc:
                if "does not support tools" in str(exc) and tools_payload:
                    try:
                        response = ollama.chat(
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

            from bookkeeping import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=worker.model,
                role="worker",
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

def validate_ollama():
    """Check Ollama is reachable and the requested model is available."""
    effective_host = OLLAMA_HOST or "localhost:11434"
    try:
        models_resp = client.list()  # uses the configured client (local or remote)
        available = [m.model for m in models_resp.models]
    except Exception as exc:
        print(f"\n[FATAL] Cannot reach Ollama service at {effective_host}: {exc}")
        print("        Make sure Ollama is running  (ollama serve)")
        return False

    if not any(OLLAMA_MODEL in m for m in available):
        print(f"\n[FATAL] Model '{OLLAMA_MODEL}' is not available at {effective_host}.")
        print(f"        Available models: {available}")
        print(f"        Pull it with:  ollama pull {OLLAMA_MODEL}")
        return False

    return True


def print_banner(connected: list, failed: list, tool_map: dict):
    effective_host = OLLAMA_HOST or "localhost:11434"
    print("\n" + "=" * 50)
    print("         Jarvis MCP Test Harness")
    print("=" * 50)
    print(f"\n  Model  : {OLLAMA_MODEL}")
    print(f"  Endpoint: {effective_host}\n")

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
    if not validate_ollama():
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
