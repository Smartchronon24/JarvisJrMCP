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
            "MEMORY_FILE_PATH": str(BASE_DIR / "data" / "memory.jsonl"),
        },
    },
    # Example: add more servers later like this:
    # "filesystem": {
    #     "command": "npx.cmd",
    #     "args": ["-y", "@modelcontextprotocol/server-filesystem", str(BASE_DIR)],
    #     "env": {**os.environ},
    # },
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

General rules:
- For general knowledge questions answer directly without tools.
- Keep responses concise and helpful.
"""