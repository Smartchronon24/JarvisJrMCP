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
        self.ollama_tools: list[dict] = []             # tool defs for Ollama
        self.conversation: list[dict] = [              # message history
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self._exit_stack = AsyncExitStack()

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
            result = await session.call_tool(real_tool_name, arguments)

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
            tools_payload = self.ollama_tools if self.ollama_tools else None
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
