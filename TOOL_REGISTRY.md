# Tool Registry (TR-3)

## What is the Tool Registry?

The Tool Registry (pp/tools/) is the **single source of truth** for all MCP tools known to Jarvis.

It is a centralized, in-memory catalog that stores structured metadata about every tool discovered from every MCP server.

---

## Responsibility Boundaries

The system explicitly enforces strict responsibility boundaries:

| Layer                 | Responsibility                                                                 |
|-----------------------|--------------------------------------------------------------------------------|
| **MCP Client**        | Connects to servers, lists tools (discovery), executes tools via session.      |
| **Tool Registry**     | Maintains canonical catalog, tool metadata, capabilities, and enabled state.   |
| **Orchestrator**      | Determines which capabilities a task requires.                                 |
| **Tool Snapshot**     | Immutable subset of enabled tools assigned to a specific execution worker.     |
| **LLM Provider**      | Converts raw MCP schemas into provider-specific schemas (e.g. Ollama/Gemini).  |

---

## What the Registry owns

| Responsibility                          | Owner           |
|-----------------------------------------|-----------------|
| Knowing which tools exist               | **Tool Registry** |
| Storing tool metadata (name, desc, schema) | **Tool Registry** |
| Grouping tools by server / capability   | **Tool Registry** |
| Filtering tools (enabled, available)    | **Tool Registry** |
| Generating Tool Snapshots               | **Tool Registry** |
| Connecting to MCP servers               | MCP Client      |
| Calling / executing MCP tools           | MCP Client      |
| Managing MCP sessions / connections     | MCP Client      |
| Formatting tools for an LLM provider   | LLM Provider    |

---

## Architecture position

`	ext
                  MCP SERVERS
                       │
                       ▼
                 MCP CLIENT
                       │
                 tool discovery
                       │
                       ▼
              ┌─────────────────┐
              │  TOOL REGISTRY  │
              │                 │
              │ What exists?    │
              │ Where is it?    │
              │ What capability?│
              │ Enabled?        │
              │ Schema?         │
              └────────┬────────┘
                       │
                       ▼
                ORCHESTRATOR
                       │
              What does this task
              actually need?
                       │
                       ▼
                TOOL SNAPSHOT
                       │
                       ▼
                  LLM PROVIDER
                       │
          model-specific formatting
                       │
                       ▼
                    WORKER
                       │
                       ▼
                 MCP CLIENT
                       │
                       ▼
                 TOOL EXECUTION
`

---

## How tools are registered

During JarvisAgent.connect_servers(), after each MCP server's tools are discovered via session.list_tools(), each tool is automatically passed to 	ool_registry.register_mcp_tool().

This is the **only** registration point. Tools are never manually registered.

`python
# Inside connect_servers() — automatic, dynamic registration
for tool in result.tools:
    tool_registry.register_mcp_tool(server_name, tool, available=True)
`

The registry stores the full raw inputSchema verbatim for future LLM adapter use.

---

## Snapshot Lifecycle

Instead of repeatedly querying the global registry during a task, the orchestrator creates a ToolSnapshot.

`	ext
Task begins
    ↓
Capabilities determined
    ↓
Registry queried (create_snapshot)
    ↓
Snapshot created
    ↓
Worker receives snapshot
    ↓
Task executes
    ↓
Snapshot discarded
`

A snapshot is immutable and guaranteed to contain only **enabled** and **eligible** tools. The registry completely filters out any tool or server that is disabled.

---

## How capabilities work

Each MCP server is mapped to a capability bucket via a deterministic table in egistry.py:

| Server       | Capability       |
|--------------|-----------------|
| memory     | memory         |
| ilesystem | ilesystem     |
| playwright | rowser        |
| exa        | web_research   |
| 	avily     | web_research   |
| irecrawl  | web_research   |
| whatsapp   | communication  |
| 	erminal   | 	erminal       |

Unknown servers default to general.

This classification is intentionally simple and deterministic in TR-1/TR-3.
Future phases may introduce LLM-based or ML-based classification.

---

## Registry API (quick reference)

`python
from app.tools import tool_registry

# Create a snapshot for a task
snapshot = tool_registry.create_snapshot(servers=["memory", "terminal"])

# Get names from snapshot
names = snapshot.tool_names
has_memory = snapshot.has_tool("memory__search_nodes")

# Enable / Disable (immediately affects future snapshots)
tool_registry.enable_tool("filesystem__write_file")
tool_registry.disable_tool("filesystem__write_file")

# Bulk server enable/disable
tool_registry.set_server_enabled("terminal", False)

# Lookup single tool metadata
meta = tool_registry.get_tool("memory__search_nodes")

# Registry summary (for logging/debugging)
tool_registry.summary()
`

---

## Files

| File                         | Purpose                                          |
|------------------------------|--------------------------------------------------|
| pp/tools/__init__.py      | Package init; exports 	ool_registry & models   |
| pp/tools/models.py        | ToolMetadata & ToolSnapshot definitions      |
| pp/tools/registry.py      | ToolRegistry class with all operations         |
