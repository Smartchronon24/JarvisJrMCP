import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Endpoint preset — switch between LOCAL and REMOTE by changing these 3 lines
# ---------------------------------------------------------------------------

# --- LOCAL (your machine) ---
# OLLAMA_HOST  = None                      # None → connects to localhost:11434
# OLLAMA_MODEL = "llama3.1:8b"

# --- REMOTE (company server) ---
# OLLAMA_HOST  = "http://10.1.1.105:31434"
# OLLAMA_MODEL = "gpt-oss:120b-cloud"

# Active preset ↓
OLLAMA_HOST  =  None                  #"http://ollama-llama.ai-s1.sloopstash.stg"         
OLLAMA_MODEL =  "gpt-oss:120b-cloud"     #  "llama3.2:3b"     
OLLAMA_STREAM = True  # Set False to wait for full response before printing

MCP_SERVERS = {
    "memory": {
        "command": "npx.cmd",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env": {
            **os.environ,
            "MEMORY_FILE_PATH": str(BASE_DIR / "data" / "MemoryMCP" / "memory.jsonl"),
        },
    },
    "uber": {
        "command": "npx.cmd",
        # mcp-uber (199-mcp/mcp-uber) — OAuth 2.0 + Uber REST API, no browser automation
        "args": ["-y", "mcp-uber"],
        "env": {
            **os.environ,
            # Credentials are read from environment variables.
            # Set these in a .env file (see .env.example) or in your shell.
            # NEVER hardcode credentials here.
            "UBER_CLIENT_ID":     os.environ.get("UBER_CLIENT_ID", ""),
            "UBER_CLIENT_SECRET": os.environ.get("UBER_CLIENT_SECRET", ""),
            "UBER_REDIRECT_URI":  os.environ.get("UBER_REDIRECT_URI", "http://localhost:3000/callback"),
            "UBER_ENVIRONMENT":   os.environ.get("UBER_ENVIRONMENT", "sandbox"),
        },
    },
}

SYSTEM_PROMPT = """You are Jarvis, a personal AI assistant.

You have access to MCP (Model Context Protocol) tools that let you interact with external systems.
Each tool has an authoritative input schema.

When calling a tool:
- use the exact tool name
- use the exact argument names
- follow the provided input schema
- do not invent parameters
- do not rename parameters
- do not fabricate tool results
- do not claim an action succeeded unless the tool result confirms success

Memory MCP Rules:
- Never invent entities, observations, relations, or stored memories.
- If you need information from memory, retrieve it using the appropriate MCP tool first.
- If the tool returns no matching information, say that the information was not found.
- Do not construct a fictional answer from assumptions.
- Preserve historical values when the user explicitly changes,
renames, replaces, or updates an existing fact and the previous
value may be useful for future questions.

Do not preserve every transient value.

Uber MCP Rules:
- All Uber tools require a 'userId' argument — use 'jarvis' as the default userId.
- uber_get_price_estimates requires numeric latitude/longitude coordinates, not place names.
  If the user provides a place name, ask them for coordinates or tell them the lat/lng
  needed. Do NOT invent coordinates.
- Before calling any authenticated Uber tool (estimates, ride request, status, cancel),
  check whether the user has set an access token. If not, call uber_get_auth_url first.
- NEVER call uber_request_ride without explicit user confirmation. The application will
  enforce a confirmation gate before the ride request executes.
- Report Uber API responses exactly as returned. Do not embellish or invent ride results.
- If an Uber tool returns an error, report the exact error text to the user.
- Uber sandbox mode is active: ride requests may return synthetic data.

General rules:
- For general knowledge questions answer directly without tools.
- Keep responses concise and helpful.
"""