# A1_REPORT

## Architecture Before
The Tool Registry (`app/tools/registry.py`) and Tool Selector (`app/tools/selector.py`) were previously intertwined. The selector imported the global registry singleton to perform filtering, blurring the boundary between the registry catalog and the deterministic selection logic. The registry API itself contained redundant retrieval functions (`list_tools`, `get_tools_for_capabilities`, `get_tools_for_servers`, `get_enabled_tool_names`) that accomplished the same filtering logic under different names. 

## Problems Found
1. **Coupling:** `selector.select()` imported `tool_registry` directly. A Tool Selector should receive candidates rather than fetching them from a global singleton itself, keeping it pure and testable.
2. **Redundant API:** The ToolRegistry had 5 different retrieval methods serving similar purposes with overlapping arguments.
3. **Dead Code:** `get_enabled_tool_names` was unused in the current orchestration flow.
4. **Agent Orchestration Coupling:** `ollama_agent.py` was pulling candidates from multiple different sources with inconsistent logic.

## Changes Made
1. **Unified Registry API:** Consolidated retrieval into a single, clean `get_tools(servers, capabilities, enabled_only, available_only)` method.
2. **Backward Compatibility Aliases:** Provided `get_tools_for_server`, `get_tools_for_capability`, and `list_tools` as thin wrappers around `get_tools`.
3. **Decoupled Selector:** Removed `tool_registry` import from `selector.py`. The selector now requires `candidates` to be explicitly provided by the caller.
4. **Orchestrator Updates:** Updated `ollama_agent.py` to fetch candidates using `tool_registry.get_tools()` and pass them cleanly into the selector.
5. **Testing Foundation:** Replaced `pytest` requirement with standard `python -m` execution for `test_selector.py` and created comprehensive isolated tests in `test_registry.py`.

## Files Changed
* `[MODIFY]` `app/tools/registry.py`: Unified API, removed dead code.
* `[MODIFY]` `app/tools/selector.py`: Removed registry import, mandated candidates.
* `[MODIFY]` `app/tools/__init__.py`: Updated docstrings.
* `[MODIFY]` `app/agents/ollama_agent.py`: Passed candidate tools explicitly to selector.
* `[MODIFY]` `app/tools/test_selector.py`: Updated to pass candidates.
* `[NEW]` `app/tools/test_registry.py`: Created comprehensive unit tests.

## What Was Preserved
* The concept and structure of `ToolMetadata` and `ToolSnapshot` were entirely preserved, as they effectively represent the model-agnostic neutral state boundaries.
* The deterministic selection and scoring rules inside `selector.py` were preserved without modification.
* Existing scoped `server__tool` naming convention was preserved.
* The `search_tools` mechanism relying on substring intersections was preserved as the A1 metadata-discovery baseline.

## What Was Removed
* Unused `get_enabled_tool_names()` and redundant list-retrieval internal logic inside `ToolRegistry`.
* `from app.tools import tool_registry` was removed from the selector.

## Registry Boundary
**What the registry owns:**
* Tracking the existence of all MCP tools (`ToolMetadata`).
* Managing enabled/disabled policy flags and available/unavailable server status.
* Querying and filtering tools by capability or server.
* Emitting immutable `ToolSnapshot` sets for worker execution.
* Performing baseline, model-agnostic textual search on metadata.

**What the registry does NOT own:**
* Determining which tools *should* be selected for a specific prompt.
* Communicating with LLM providers (Ollama/Gemini).
* Executing the MCP tools or maintaining the client sessions.

## Future Compatibility
The refactored `ToolRegistry` now exposes a purely metadata-driven, provider-agnostic interface.
* **Tool Discovery:** Future semantic search or vector database integrations can simply consume `get_tools()` and return ranked IDs without being tangled in registry state logic.
* **Multiple LLM Providers:** The registry operates exclusively on `ToolMetadata`, avoiding any Provider schema entanglement. The provider adapters can reliably map the `ToolSnapshot` to their specific schema requirements.
* **Agentic Discovery:** A future planner or discovery agent can safely query the registry interface using `get_tools_for_capability()` without risk of side-effects or unexpected LLM calls.

## Validation
1. **Compilation:** Executed `python -m py_compile` across all modified files (`registry.py`, `selector.py`, `ollama_agent.py`, `client.py`, `server.py`). No syntax errors.
2. **Tests:** Executed `python -m app.tools.test_registry` and `python -m app.tools.test_selector`. Both passed successfully.
3. **Isolation Check:** Verified via static analysis that `registry.py` imports no LLM providers, and that `selector.py` imports no `registry.py`.
