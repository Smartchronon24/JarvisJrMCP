# TR-3 Complete — Tool Registry as the Authoritative Selection Boundary

## Files Created
- (No new project files were required. Added a temporary validation script scratch/test_tr3.py).

## Files Modified
- pp/tools/models.py: Added the immutable ToolSnapshot dataclass representing a specific execution environment.
- pp/tools/__init__.py: Exported ToolSnapshot for use across the app.
- pp/tools/registry.py: Added the create_snapshot() API that enforces filtering rules and generates a snapshot.
- pp/agents/ollama_agent.py: 
  - Refactored get_active_tools() to use ToolSnapshot.
  - Removed duplicated tool availability logic in the orchestrator. The orchestrator now relies entirely on the registry to generate a snapshot of eligible tools.
- TOOL_REGISTRY.md: Documented the new ToolSnapshot architecture and boundaries.

## Architecture Changes
- Introduced **Tool Snapshot**: A lightweight abstraction representing exactly what tools are enabled and selected for a specific execution.
- Removed duplicated enabled_mcps checks in the orchestrator. The registry inherently filters out disabled tools and servers during snapshot creation.

## Registry Responsibility
The registry is now definitively the authoritative source for tool metadata and eligibility. It provides a purely Pythonic, memory-based representation of the available tools, completely independent of LLM providers or MCP execution logic.

## Snapshot Behavior
A ToolSnapshot is generated dynamically by the registry when the orchestrator resolves a task's capabilities. It guarantees that:
- It only contains enabled tools.
- It only contains tools from enabled servers.
- The worker is securely restricted to this snapshot (worker.allowed_tool_names = snapshot.tool_names).

## Provider Boundary
The provider boundary is strictly maintained in ollama_agent.py. The orchestrator maps the selected ToolSnapshot names back into raw mcp_tool objects via self.tool_map, and then hands them to the provider for formatting (provider.format_tool()). The registry itself knows nothing about Gemini, Ollama, or OpenAI format requirements.

## Validation
Passed all lightweight checks, including:
- Python compilation (compileall).
- Validation of snapshot capabilities and server restriction.
- Validation that disabled tools and server-disabled tools are aggressively excluded from snapshots.

## Explicitly NOT Changed
- MCP execution flows (self.tool_map usage).
- Gemini schema implementations.
- Routing agent intelligence.
- WhatsApp/Terminal MCP internal functionality.
