"""
A4 — Representative Tool Selection Tests
=========================================
Tests cover the 7 required task scenarios from the A4 spec.

All tests are isolated:
  - No running MCP servers
  - No live Ollama / Gemini / network calls
  - LLMToolSelector is tested by mocking the LLM response
  - DeterministicToolSelector is tested directly

Usage::

    python -m app.tools.test_discovery_selection
"""

from __future__ import annotations

import sys
import os

# Ensure project root is on path when run as __main__
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.tools.models import ToolMetadata, ToolSnapshot
from app.tools.registry import ToolRegistry
from app.tools.selector import (
    DeterministicToolSelector,
    LLMToolSelector,
    ToolSelectionStrategy,
)

# ---------------------------------------------------------------------------
# Test registry fixture
# ---------------------------------------------------------------------------

def _make_meta(
    name: str,
    *,
    server: str,
    capability: str,
    description: str,
    params: list[str] | None = None,
) -> ToolMetadata:
    props = {p: {"type": "string"} for p in (params or [])}
    return ToolMetadata(
        name=name,
        server=server,
        tool_name=name.split("__", 1)[-1],
        capability=capability,
        description=description,
        input_schema={"type": "object", "properties": props},
    )


def build_test_registry() -> ToolRegistry:
    reg = ToolRegistry()
    tools = [
        # Memory
        _make_meta("memory__search_nodes", server="memory", capability="memory",
                   description="Search memory for stored entities and relationships.",
                   params=["query", "limit"]),
        _make_meta("memory__read_graph", server="memory", capability="memory",
                   description="Read the full memory knowledge graph.",
                   params=["random_string"]),
        _make_meta("memory__create_entities", server="memory", capability="memory",
                   description="Create new entities in memory.",
                   params=["entities"]),
        _make_meta("memory__delete_entities", server="memory", capability="memory",
                   description="Delete entities from memory by name.",
                   params=["entityNames"]),
        _make_meta("memory__add_observations", server="memory", capability="memory",
                   description="Add observations about entities in memory.",
                   params=["observations"]),
        # WhatsApp
        _make_meta("whatsapp__search_contacts", server="whatsapp", capability="communication",
                   description="Search WhatsApp contacts by name or phone number.",
                   params=["query", "limit"]),
        _make_meta("whatsapp__get_direct_chat_by_contact", server="whatsapp", capability="communication",
                   description="Get or create a direct chat with a WhatsApp contact.",
                   params=["contact_id"]),
        _make_meta("whatsapp__list_messages", server="whatsapp", capability="communication",
                   description="List recent messages in a WhatsApp conversation.",
                   params=["chat_id", "limit"]),
        _make_meta("whatsapp__send_message", server="whatsapp", capability="communication",
                   description="Send a WhatsApp message to a contact or group.",
                   params=["chat_id", "message"]),
        _make_meta("whatsapp__send_file", server="whatsapp", capability="communication",
                   description="Send a file via WhatsApp.",
                   params=["chat_id", "file_path"]),
        # Web research
        _make_meta("exa__web_search_exa", server="exa", capability="web_research",
                   description="Search the web using Exa for recent, relevant results.",
                   params=["query", "num_results"]),
        _make_meta("firecrawl__firecrawl_scrape", server="firecrawl", capability="web_research",
                   description="Scrape and extract clean content from a URL.",
                   params=["url"]),
        _make_meta("tavily__tavily_search", server="tavily", capability="web_research",
                   description="Search the web using Tavily for real-time information.",
                   params=["query", "max_results"]),
        # Terminal
        _make_meta("terminal__createSession", server="terminal", capability="terminal",
                   description="Create a new terminal session.",
                   params=["id"]),
        _make_meta("terminal__type", server="terminal", capability="terminal",
                   description="Type a command into an active terminal session.",
                   params=["session_id", "text"]),
        _make_meta("terminal__sendKey", server="terminal", capability="terminal",
                   description="Send a keystroke (e.g. Enter) to a terminal session.",
                   params=["session_id", "key"]),
        _make_meta("terminal__getContent", server="terminal", capability="terminal",
                   description="Read current output from a terminal session.",
                   params=["session_id"]),
        # Filesystem
        _make_meta("filesystem__read_file", server="filesystem", capability="filesystem",
                   description="Read the contents of a file from disk.",
                   params=["path"]),
        _make_meta("filesystem__write_file", server="filesystem", capability="filesystem",
                   description="Write content to a file on disk.",
                   params=["path", "content"]),
        _make_meta("filesystem__list_directory", server="filesystem", capability="filesystem",
                   description="List the contents of a directory.",
                   params=["path"]),
    ]
    reg.register_tools(tools)
    return reg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_deterministic(request: str, candidates: list[ToolMetadata]) -> list[str]:
    sel = DeterministicToolSelector()
    return sel.select(request, candidates)


class _MockLLMSelector(LLMToolSelector):
    """
    LLMToolSelector subclass that replaces the LLM call with a fixed response.
    Used to test the parsing/validation/fallback pipeline without network calls.
    """

    def __init__(self, mock_response: str, **kwargs):
        super().__init__(**kwargs)
        self._mock_response = mock_response

    def _select_via_llm(self, request, candidates, limit):
        from app.tools.selector import _parse_llm_selection
        valid_names = {meta.name for meta in candidates}
        parsed = _parse_llm_selection(self._mock_response, valid_names)
        if parsed is None:
            return None
        return parsed[:limit]


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------

def test_memory_retrieval():
    """
    'What do you remember about me?'
    → should surface read tools (search_nodes, read_graph)
    → should NOT surface mutation tools (create_entities, delete_entities) by default
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["memory"], enabled_only=True)
    request = "What do you remember about me?"

    # Test: LLM mock returns only retrieval tools
    sel = _MockLLMSelector(
        '["memory__search_nodes", "memory__read_graph"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "memory__search_nodes" in selected or "memory__read_graph" in selected, \
        f"Expected retrieval tool, got: {selected}"
    assert "memory__create_entities" not in selected, \
        "Mutation tool should not be selected for a read-only memory query"
    assert "memory__delete_entities" not in selected
    print(f"[PASS] Memory retrieval: {selected}")


def test_memory_mutation():
    """
    'Forget that my preferred name is Navaneth.'
    → should surface delete tool
    → should NOT surface read tools
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["memory"], enabled_only=True)
    request = "Forget that my preferred name is Navaneth."

    sel = _MockLLMSelector(
        '["memory__delete_entities"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "memory__delete_entities" in selected, \
        f"Delete tool expected for mutation request, got: {selected}"
    assert "memory__search_nodes" not in selected
    print(f"[PASS] Memory mutation: {selected}")


def test_whatsapp_contact_lookup():
    """
    'Find the contact 917358247423.'
    → should return search_contacts only (single-step lookup)
    → should NOT return all WhatsApp tools
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["communication"], enabled_only=True)
    request = "Find the contact 917358247423."

    sel = _MockLLMSelector(
        '["whatsapp__search_contacts"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "whatsapp__search_contacts" in selected
    assert "whatsapp__send_message" not in selected, \
        "Send tool should not be selected for a contact lookup"
    assert len(selected) <= 3, \
        f"Too many tools selected for a simple lookup: {selected}"
    print(f"[PASS] WhatsApp contact lookup: {selected}")


def test_whatsapp_message_search_workflow():
    """
    "Find John's recent messages."
    → multi-step workflow: search_contacts → get_direct_chat → list_messages
    → send_message must NOT be included
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["communication"], enabled_only=True)
    request = "Find John's recent messages."

    sel = _MockLLMSelector(
        '["whatsapp__search_contacts", "whatsapp__get_direct_chat_by_contact", "whatsapp__list_messages"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "whatsapp__search_contacts" in selected
    assert "whatsapp__list_messages" in selected
    assert "whatsapp__send_message" not in selected, \
        "LLM should not select send_message for a read workflow"
    print(f"[PASS] WhatsApp message search (multi-step): {selected}")


def test_web_research():
    """
    'Search the web for the latest NVIDIA GPU news.'
    → should select at least one web_research tool
    → should NOT select whatsapp, filesystem, or terminal tools
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["web_research"], enabled_only=True)
    request = "Search the web for the latest NVIDIA GPU news."

    sel = _MockLLMSelector(
        '["exa__web_search_exa"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    web_tools = {t for t in selected if "exa" in t or "tavily" in t or "firecrawl" in t}
    assert len(web_tools) >= 1, f"Expected at least one web tool, got: {selected}"
    assert not any("whatsapp" in t for t in selected)
    assert not any("filesystem" in t for t in selected)
    print(f"[PASS] Web research: {selected}")


def test_terminal_execution_workflow():
    """
    'Run a Python command that prints the current directory.'
    → needs full terminal workflow: createSession → type → sendKey → getContent
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["terminal"], enabled_only=True)
    request = "Run a Python command that prints the current directory."

    sel = _MockLLMSelector(
        '["terminal__createSession", "terminal__type", "terminal__sendKey", "terminal__getContent"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "terminal__type" in selected
    assert "terminal__getContent" in selected
    print(f"[PASS] Terminal execution workflow: {selected}")


def test_general_chat_no_tools():
    """
    'Hello, how are you?'
    → LLM correctly identifies no tools are needed
    → empty list or minimal tools returned
    """
    reg = build_test_registry()
    candidates = reg.get_tools(enabled_only=True)  # all tools
    request = "Hello, how are you?"

    sel = _MockLLMSelector("[]", fallback=DeterministicToolSelector())
    selected = sel.select(request, candidates)
    assert len(selected) == 0, \
        f"No tools expected for general chat, got: {selected}"
    print(f"[PASS] General chat (no tools): {selected}")


def test_llm_parse_error_falls_back_to_deterministic():
    """
    When the LLM returns unparseable output, the selector should fall back
    to DeterministicToolSelector and return a valid result.
    """
    reg = build_test_registry()
    candidates = reg.get_tools(capabilities=["memory"], enabled_only=True)
    request = "What do you know about me?"

    sel = _MockLLMSelector("This is not JSON at all!", fallback=DeterministicToolSelector())
    selected = sel.select(request, candidates)
    # Fallback should still return something from memory candidates
    assert isinstance(selected, list)
    assert all(isinstance(n, str) for n in selected)
    print(f"[PASS] Fallback on parse error: {selected}")


def test_llm_selector_validates_names():
    """
    LLM response containing invented tool names must be filtered out.
    Only names from the candidate set should appear in the output.
    """
    reg = build_test_registry()
    candidates = [reg.get_tool("memory__search_nodes"), reg.get_tool("memory__delete_entities")]
    candidates = [c for c in candidates if c is not None]
    request = "Search my memory."

    # LLM returns one valid name and one hallucinated name
    sel = _MockLLMSelector(
        '["memory__search_nodes", "memory__invented_fake_tool"]',
        fallback=DeterministicToolSelector(),
    )
    selected = sel.select(request, candidates)
    assert "memory__search_nodes" in selected
    assert "memory__invented_fake_tool" not in selected, \
        "Hallucinated tool name must be filtered out"
    print(f"[PASS] LLM selector validates names (no hallucinations): {selected}")


def test_snapshot_immutability():
    """
    ToolSnapshot created from selection result must not mutate the registry.
    """
    reg = build_test_registry()
    total_before = len(reg.get_tools())
    candidates = reg.get_tools(capabilities=["memory"], enabled_only=True)

    sel = _MockLLMSelector('["memory__search_nodes"]', fallback=DeterministicToolSelector())
    selected_names = sel.select("What do you remember?", candidates)

    tools = [reg.get_tool(n) for n in selected_names if reg.get_tool(n)]
    snapshot = ToolSnapshot(tools=tools)

    assert len(reg.get_tools()) == total_before, "Registry was mutated by selection!"
    assert len(snapshot) == len(tools)
    print(f"[PASS] Snapshot immutability: registry has {total_before} tools, snapshot has {len(snapshot)}")


def test_disabled_tools_excluded():
    """
    A disabled tool must never appear in selection output even if candidates
    are pulled before filtering — this verifies the registry boundary.
    """
    reg = build_test_registry()
    reg.disable_tool("whatsapp__send_message")

    candidates = reg.get_tools(capabilities=["communication"], enabled_only=True)
    names = {meta.name for meta in candidates}
    assert "whatsapp__send_message" not in names, "Disabled tool leaked into enabled_only query"
    print(f"[PASS] Disabled tools excluded: {names}")


def test_deterministic_selector_before_after():
    """
    Measure before/after tool counts: all tools vs selected for a representative request.
    Prints an observability table.
    """
    reg = build_test_registry()
    all_tools = reg.get_tools(enabled_only=True)
    request = "Find John's recent WhatsApp messages."
    candidates = reg.get_tools(capabilities=["communication"], enabled_only=True)

    det = DeterministicToolSelector()
    selected = det.select(request, candidates)

    print(f"\n[OBSERVABILITY] Request: {request!r}")
    print(f"  Registry total   : {len(all_tools)}")
    print(f"  Discovery candidates: {len(candidates)} (communication only)")
    print(f"  Selected by deterministic: {len(selected)}")
    print(f"  Selected tools   : {selected}")
    rejected = [m.name for m in candidates if m.name not in selected]
    print(f"  Rejected tools   : {rejected}")
    print(f"[PASS] Observability table printed.")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    tests = [
        test_memory_retrieval,
        test_memory_mutation,
        test_whatsapp_contact_lookup,
        test_whatsapp_message_search_workflow,
        test_web_research,
        test_terminal_execution_workflow,
        test_general_chat_no_tools,
        test_llm_parse_error_falls_back_to_deterministic,
        test_llm_selector_validates_names,
        test_snapshot_immutability,
        test_disabled_tools_excluded,
        test_deterministic_selector_before_after,
    ]
    print(f"\n{'='*60}")
    print("A4 Tool Discovery & Selection Tests")
    print(f"{'='*60}")
    failed = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"[FAIL] {test.__name__}: {exc}")
            failed.append(test.__name__)
    print(f"\n{'='*60}")
    if failed:
        print(f"FAILED: {len(failed)} / {len(tests)}")
        for name in failed:
            print(f"  - {name}")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    run_all()
