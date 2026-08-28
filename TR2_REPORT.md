# Tool Registry TR-2 — Implementation Report

## 1. Files Created
None required for this phase. The registry files were already created in TR-1 (__init__.py, models.py, egistry.py). I created a temporary test script (scratch/test_tr2.py) to validate the new integration logic.

## 2. Files Modified
- pp/agents/ollama_agent.py:
  - Orchestrator tool resolution was updated to fetch tools exclusively via the registry (TR-2B).
  - Updated orchestrator logging to correctly report registry filtering behavior.
- pp/tools/registry.py:
  - Added TR-2D API methods: get_enabled_tool_names() and get_tools_for_server().

## 3. How the registry now participates in orchestration
The orchestration pipeline now uses the registry as the **authoritative filter** for tool eligibility:
1. The Router selects a capability (e.g., web_research).
2. The Orchestrator resolves the capability to server names (e.g., exa, tavily, firecrawl) using the existing deterministic CAPABILITY_REGISTRY.
3. The Orchestrator calls 	ool_registry.get_tools_for_servers(..., enabled_only=True).
4. The Registry evaluates per-tool enable/disable state and returns a filtered list of ToolMetadata.
5. The ToolMetadata objects are then mapped back to the raw mcp_tool representations using self.tool_map right at the boundary where they are sent to the LLM.

This perfectly separates **Tool Selection** (Registry) from **Tool Execution** (MCP Client), strictly adhering to the specified boundary pattern.

## 4. MCP discovery status
MCP discovery remains fully functional. Discovered tools from session.list_tools() continue to be automatically registered into the Tool Registry during connect_servers(), exactly as implemented in TR-1.

## 5. Capability filtering
Works perfectly. Capability matching queries the registry exactly as requested, retrieving precise and accurate subsets. Tested for memory, 	erminal, web_research, and messaging.

## 6. Disabled tools exclusion
Functions correctly. Disabling a tool (e.g., whatsapp__send_message) or a server natively impacts get_tools_for_servers(). Any tool with enabled=False is excluded from the LLM Worker payload.

## 7. What remains for TR-3
For TR-3 and beyond, Jarvis can now confidently start transitioning:
- The CAPABILITY_REGISTRY mapping logic into the registry layer.
- Automatic routing based on rich capabilities.
- Advanced capabilities mapping, embeddings/search, or LLM-based categorization of tools.
- Gemini multi-agent tool schema adaptations right inside the adapter boundary!

## 8. Architectural concerns
- The raw mcp_tool objects are temporarily cached in self.tool_map to cross the boundary. As the adapter framework evolves (e.g. for fixing Gemini schema formatting), it may be beneficial for the registry to act completely independently from self.tool_map by storing necessary schema transformations internally, or standardizing execution payloads via dicts rather than raw SDK objects. This is safe as implemented for TR-2 but is a known point of refinement for TR-3+.
