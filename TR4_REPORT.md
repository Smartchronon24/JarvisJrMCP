# TR-4 Complete — Gemini Multi-Agent Stability & Provider Hardening

## 1. Root Cause
The Gemini failures were caused by two distinct issues:

1. **Client Lifecycle Closure:** The google.genai.Client instances were being created per GeminiProvider instance. Since Router and Worker create separate instances of GeminiProvider, the previous client was getting garbage-collected or going out of scope during the transition, which closed the underlying HTTP async connections. This caused the "Cannot send a request, as the client has been closed" error during Worker delegation.
2. **Schema Incompatibility:** The Gemini API requires that any property with 	ype: ARRAY explicitly defines its items schema. The previous _build_gemini_tools implementation completely ignored the items property of arrays and did not traverse nested objects, resulting in the "missing field" rejection from the Gemini backend when tools (like memory MCP) contained raw array definitions.

## 2. Changes
- pp/llm/gemini.py:
  - **Class-level Client Cache:** Promoted _client and _api_key to _shared_client and _shared_api_key as class-level attributes. This ensures that across multiple instances of GeminiProvider, a single safe google.genai.Client lifecycle is maintained.
  - **Recursive Schema Normalization:** Replaced the shallow _build_gemini_tools list comprehension with a uild_schema() recursive helper function. This correctly parses nested objects and ensures arrays always get a safe items fallback (Type.STRING) if omitted in the MCP schema.

## 3. Gemini Lifecycle
The updated architecture uses a shared-client approach:
`	ext
Router → Gemini Provider (Instance 1) ─┐
                                       │
                                   Gemini Client (Class-level Singleton)
                                       │
Worker → Gemini Provider (Instance 2) ─┘
`
This avoids connection churn and completely eliminates the unexpected closure error.

## 4. Schema Handling
The Tool Registry remains completely provider-agnostic. The schema pipeline is now:
`	ext
Original MCP schema (Verbatim, potentially missing array items)
        ↓
Tool Registry
        ↓
Gemini adapter (app/llm/gemini.py)
        ↓
Recursive normalization (Injects default item types)
        ↓
Gemini API (Accepted)
`

## 5. Validation
A lightweight script (scratch/test_gemini_integration.py) was written and run against actual Gemini instances.
- **Python compilation:** PASS
- **Provider import validation:** PASS
- **Gemini provider initialization:** PASS
- **Router-only Gemini request:** PASS (Verified correct simple math result).
- **Router → Worker Gemini request:** PASS (Successfully yielded without client closure).
- **Worker MCP tool call:** PASS (Successfully called memory__search_nodes).
- **Tool Registry unchanged:** PASS (Architecture remained perfectly preserved).

## 6. Regression Requirements
- Ollama works unaffected since all changes were scoped to gemini.py.
- ToolRegistry retains its architectural purity.
- MCP client execution is completely unchanged.
