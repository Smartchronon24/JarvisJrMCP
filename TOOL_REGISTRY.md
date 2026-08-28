# Tool Registry (TR-1)

## What is the Tool Registry?

The Tool Registry (`app/tools/`) is the **single source of truth** for all MCP tools known to Jarvis.

It is a centralized, in-memory catalog that stores structured metadata about every tool discovered from every MCP server.

---

## Why does it exist?

Without a registry, tool knowledge was scattered across:
- `JarvisAgent.tool_map` — raw MCP tool objects
- `JarvisAgent.llm_tools` — provider-formatted dicts
- `JarvisAgent.enabled_mcps` — server-level enable/disable
- `CAPABILITY_REGISTRY` in `multi_agent.py` — static capability definitions

As Jarvis scales to potentially hundreds of tools and many MCP servers, having a single, queryable, structured catalog becomes essential for:
- Tool selection by capability
- Runtime enable/disable per-tool or per-server
- Future UI display
- Future schema adaptation per LLM provider
- Future tool scoring and relevance ranking

---

## What the Registry owns

| Responsibility                          | Owner           |
|-----------------------------------------|-----------------|
| Knowing which tools exist               | **Tool Registry** |
| Storing tool metadata (name, desc, schema) | **Tool Registry** |
| Grouping tools by server / capability   | **Tool Registry** |
| Filtering tools (enabled, available)    | **Tool Registry** |
| Connecting to MCP servers               | MCP Client      |
| Calling / executing MCP tools           | MCP Client      |
| Managing MCP sessions / connections     | MCP Client      |
| Formatting tools for an LLM provider   | LLM Provider    |

---

## What the MCP Client owns

The MCP Client (`JarvisAgent`) remains responsible for:
- Starting and connecting MCP server processes
- Maintaining live `ClientSession` objects
- Executing tool calls via `session.call_tool()`
- Tool validation, result parsing, and error handling

The registry **never** calls any MCP tool.

---

## Architecture position

```
MCP Servers
     |
MCP Client  ← connects, calls, manages sessions
     |
Tool Discovery  ← list_tools() per server
     |
TOOL REGISTRY  ← catalog, filter, metadata
     |
Tool Selection / Filtering
     |
Agent
     |
MCP Client
     |
Tool Execution
```

---

## How tools are registered

During `JarvisAgent.connect_servers()`, after each MCP server's tools are discovered via `session.list_tools()`, each tool is automatically passed to `tool_registry.register_mcp_tool()`.

This is the **only** registration point. Tools are never manually registered.

```python
# Inside connect_servers() — automatic, dynamic registration
for tool in result.tools:
    tool_registry.register_mcp_tool(server_name, tool, available=True)
```

The registry stores the full raw `inputSchema` verbatim for future LLM adapter use.

---

## How capabilities work

Each MCP server is mapped to a capability bucket via a deterministic table in `registry.py`:

| Server       | Capability       |
|--------------|-----------------|
| `memory`     | `memory`         |
| `filesystem` | `filesystem`     |
| `playwright` | `browser`        |
| `exa`        | `web_research`   |
| `tavily`     | `web_research`   |
| `firecrawl`  | `web_research`   |
| `whatsapp`   | `communication`  |
| `terminal`   | `terminal`       |

Unknown servers default to `general`.

This classification is intentionally simple and deterministic in TR-1.
Future phases may introduce LLM-based or ML-based classification.

---

## Registry API (quick reference)

```python
from app.tools import tool_registry

# List all tools
tool_registry.list_tools()

# Filter by server
tool_registry.list_tools(server="memory")

# Filter by capability
tool_registry.list_tools(capability="web_research")

# Only enabled tools
tool_registry.list_tools(enabled_only=True)

# Multi-capability retrieval
tool_registry.get_tools_for_capabilities(["memory", "communication"])

# Enable / Disable
tool_registry.enable_tool("filesystem__write_file")
tool_registry.disable_tool("filesystem__write_file")

# Bulk server enable/disable
tool_registry.set_server_enabled("terminal", False)

# Lookup single tool
meta = tool_registry.get_tool("memory__search_nodes")

# Registry summary (for logging/debugging)
tool_registry.summary()
```

---

## Files

| File                         | Purpose                                          |
|------------------------------|--------------------------------------------------|
| `app/tools/__init__.py`      | Package init; exports `tool_registry` singleton  |
| `app/tools/models.py`        | `ToolMetadata` dataclass definition              |
| `app/tools/registry.py`      | `ToolRegistry` class with all operations         |
