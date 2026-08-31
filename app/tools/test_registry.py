"""
Tests for Tool Registry A1 Foundation.
"""
from app.tools.registry import ToolRegistry
from app.tools.discovery import DiscoveryRequest, ToolDiscovery, DiscoveryResult
from app.tools.models import ToolMetadata, ToolSnapshot
from app.tools.selector import selector

def test_registry_registration_and_identity():
    reg = ToolRegistry()
    t1 = ToolMetadata(
        name="server1__tool1", server="server1", tool_name="tool1", capability="cap1", description="", input_schema={}
    )
    reg.register_tool(t1)
    
    assert reg.get_tool("server1__tool1") is t1
    assert reg.get_tool("missing") is None

def test_registry_multiple_tools_and_retrieval():
    reg = ToolRegistry()
    tools = [
        ToolMetadata(name="s1__t1", server="s1", tool_name="t1", capability="c1", description="", input_schema={}),
        ToolMetadata(name="s1__t2", server="s1", tool_name="t2", capability="c2", description="", input_schema={}),
        ToolMetadata(name="s2__t1", server="s2", tool_name="t1", capability="c1", description="", input_schema={}),
    ]
    reg.register_tools(tools)
    
    all_tools = reg.get_tools()
    assert len(all_tools) == 3
    
    # By Server
    s1_tools = reg.get_tools_for_server("s1")
    assert len(s1_tools) == 2
    assert {t.name for t in s1_tools} == {"s1__t1", "s1__t2"}
    
    # By Capability
    c1_tools = reg.get_tools_for_capability("c1")
    assert len(c1_tools) == 2
    assert {t.name for t in c1_tools} == {"s1__t1", "s2__t1"}

def test_registry_state_filtering():
    reg = ToolRegistry()
    tools = [
        ToolMetadata(name="t1", server="s1", tool_name="t1", capability="c1", description="", input_schema={}, enabled=True, available=True),
        ToolMetadata(name="t2", server="s1", tool_name="t2", capability="c1", description="", input_schema={}, enabled=False, available=True),
        ToolMetadata(name="t3", server="s2", tool_name="t3", capability="c1", description="", input_schema={}, enabled=True, available=False),
    ]
    reg.register_tools(tools)
    
    assert len(reg.get_tools(enabled_only=True)) == 2  # t1, t3
    assert len(reg.get_tools(available_only=True)) == 2  # t1, t2
    assert len(reg.get_tools(enabled_only=True, available_only=True)) == 1  # t1

def test_snapshot_creation():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(name="t1", server="s1", tool_name="t1", capability="c1", description="", input_schema={}, enabled=True))
    reg.register_tool(ToolMetadata(name="t2", server="s1", tool_name="t2", capability="c1", description="", input_schema={}, enabled=False))
    
    snap = reg.create_snapshot()
    assert len(snap) == 1
    assert snap.has_tool("t1")
    assert not snap.has_tool("t2")

def test_search_foundation():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(name="t1", server="s1", tool_name="t1", capability="c1", description="Sends a message to user", input_schema={}))
    reg.register_tool(ToolMetadata(name="t2", server="s1", tool_name="t2", capability="c1", description="Reads a file from disk", input_schema={}))
    reg.register_tool(ToolMetadata(name="t3", server="s2", tool_name="t3", capability="c2", description="Reads network message", input_schema={}))
    
    # Search for message
    matches = reg.search_tools("message")
    assert len(matches) == 2
    assert {t.name for t in matches} == {"t1", "t3"}
    
    # Filtered search
    matches = reg.search_tools("message", servers=["s1"])
    assert len(matches) == 1
    assert matches[0].name == "t1"


def build_discovery_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tool(
        ToolMetadata(
            name="whatsapp__search_contacts",
            server="whatsapp",
            tool_name="search_contacts",
            capability="communication",
            description="Search WhatsApp contacts by name.",
            input_schema={"properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}},
        )
    )
    reg.register_tool(
        ToolMetadata(
            name="whatsapp__list_messages",
            server="whatsapp",
            tool_name="list_messages",
            capability="communication",
            description="Read recent WhatsApp messages from a conversation.",
            input_schema={"properties": {"chat_id": {"type": "string"}, "limit": {"type": "integer"}}},
        )
    )
    reg.register_tool(
        ToolMetadata(
            name="whatsapp__send_message",
            server="whatsapp",
            tool_name="send_message",
            capability="communication",
            description="Send a WhatsApp message to a contact.",
            input_schema={"properties": {"chat_id": {"type": "string"}, "message": {"type": "string"}}},
        )
    )
    reg.register_tool(
        ToolMetadata(
            name="filesystem__read_file",
            server="filesystem",
            tool_name="read_file",
            capability="filesystem",
            description="Read a file from disk.",
            input_schema={"properties": {"path": {"type": "string"}, "encoding": {"type": "string"}}},
        )
    )
    return reg


def test_discovery_search_by_tool_name():
    reg = build_discovery_registry()
    matches = reg.search_tools("search_contacts")
    assert [meta.name for meta in matches] == ["whatsapp__search_contacts"]


def test_discovery_search_by_description():
    reg = build_discovery_registry()
    matches = reg.search_tools("recent messages")
    names = {meta.name for meta in matches}
    assert "whatsapp__list_messages" in names


def test_discovery_search_by_capability():
    reg = build_discovery_registry()
    matches = reg.search_tools("", capabilities=["communication"])
    assert {meta.name for meta in matches} == {"whatsapp__search_contacts", "whatsapp__list_messages", "whatsapp__send_message"}


def test_discovery_search_by_parameter_name():
    reg = build_discovery_registry()
    matches = reg.discover_tools(parameter_name="chat_id")
    assert {meta.name for meta in matches} == {"whatsapp__list_messages", "whatsapp__send_message"}


def test_discovery_server_filtering():
    reg = build_discovery_registry()
    matches = reg.search_tools("message", servers=["whatsapp"])
    assert {meta.name for meta in matches} == {"whatsapp__list_messages", "whatsapp__send_message"}


def test_discovery_excludes_disabled_tool():
    reg = build_discovery_registry()
    reg.disable_tool("whatsapp__send_message")
    matches = reg.search_tools("send a WhatsApp message")
    names = {meta.name for meta in matches}
    assert "whatsapp__send_message" not in names
    assert "whatsapp__list_messages" in names


def test_discovery_excludes_disabled_server():
    reg = build_discovery_registry()
    reg.set_server_enabled("whatsapp", False)
    matches = reg.search_tools("WhatsApp message")
    assert matches == []


def test_discovery_empty_or_no_match_query():
    reg = build_discovery_registry()
    assert reg.search_tools("") == []
    assert reg.search_tools("not-a-real-tool-name") == []


def test_discovery_multiple_relevant_candidates():
    reg = build_discovery_registry()
    matches = reg.search_tools("WhatsApp contact")
    names = {meta.name for meta in matches}
    assert "whatsapp__search_contacts" in names
    assert "whatsapp__send_message" in names or "whatsapp__search_contacts" in names
    matches = reg.search_tools("message")
    assert {meta.name for meta in matches} == {"whatsapp__list_messages", "whatsapp__send_message"}


def test_discovery_registry_remains_provider_agnostic():
    reg = ToolRegistry()
    reg.register_tool(
        ToolMetadata(
            name="custom_provider__lookup_customer",
            server="custom_provider",
            tool_name="lookup_customer",
            capability="general",
            description="Look up a customer record.",
            input_schema={"properties": {"customer_id": {"type": "string"}}},
        )
    )
    matches = reg.discover_tools(query="customer lookup", parameter_name="customer_id")
    assert [meta.name for meta in matches] == ["custom_provider__lookup_customer"]


def test_discovery_result_can_feed_selector():
    reg = build_discovery_registry()
    request = DiscoveryRequest(query="send WhatsApp message", enabled_only=True, available_only=True)
    result = reg.discover(request)
    selected = selector.select(request.query, candidates=result.candidates)
    assert selected
    assert "whatsapp__send_message" in selected


def test_selector_output_can_become_snapshot():
    reg = build_discovery_registry()
    candidates = reg.search_tools("WhatsApp contact")
    selected = selector.select("WhatsApp contact", candidates=candidates)
    tools = [reg.get_tool(name) for name in selected if reg.get_tool(name)]
    snapshot = ToolSnapshot(tools=tools)
    assert len(snapshot) >= 1
    assert snapshot.has_tool(selected[0])


def test_discovery_strategy_is_replaceable():
    class FakeDiscovery(ToolDiscovery):
        def discover(self, registry, request):
            return DiscoveryResult(request=request, candidates=[registry.get_tool("whatsapp__list_messages")])

    reg = build_discovery_registry()
    reg.set_discovery_strategy(FakeDiscovery())
    result = reg.discover(DiscoveryRequest(query="read my messages", enabled_only=True, available_only=True))
    assert [meta.name for meta in result.candidates] == ["whatsapp__list_messages"]


def test_selection_restricts_to_discovery_candidates():
    from app.tools.selector import LLMToolSelector, DeterministicToolSelector

    reg = build_discovery_registry()
    candidates = reg.search_tools("WhatsApp contact")
    selector = LLMToolSelector(fallback=DeterministicToolSelector())

    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        def select(self, request, candidate_list, max_tools, runtime_state=None):
            return ["whatsapp__search_contacts", "not_in_candidates"]

    # Simulate a model output with one hallucinated name; the selector should drop it.
    selector._select_via_llm = lambda request, candidate_list, limit: ["whatsapp__search_contacts", "not_in_candidates"]
    selected = selector.select("find a WhatsApp contact", candidates=candidates)
    assert selected == ["whatsapp__search_contacts"]


def test_selection_returns_empty_when_no_candidates_are_relevant():
    reg = build_discovery_registry()
    candidates = reg.search_tools("not a real tool")
    assert candidates == []


def test_selection_respects_discovery_boundary_for_no_tool_tasks():
    from app.tools.selector import LLMToolSelector, DeterministicToolSelector

    reg = build_discovery_registry()
    selector = LLMToolSelector(fallback=DeterministicToolSelector())
    selector._select_via_llm = lambda request, candidate_list, limit: []
    selected = selector.select("What is the capital of France?", candidates=reg.search_tools("WhatsApp message"))
    assert selected == []


def test_discovery_deduplicates_candidates():
    reg = ToolRegistry()
    reg.register_tool(ToolMetadata(
        name="memory__search_nodes",
        server="memory",
        tool_name="search_nodes",
        capability="memory",
        description="Search stored memory for user facts and notes.",
        input_schema={"properties": {"query": {"type": "string"}}},
    ))
    reg.register_tool(ToolMetadata(
        name="memory__search_nodes",
        server="memory",
        tool_name="search_nodes",
        capability="memory",
        description="Search stored memory for user facts and notes.",
        input_schema={"properties": {"query": {"type": "string"}}},
    ))
    tools = reg.search_tools("remember facts")
    assert [meta.name for meta in tools] == ["memory__search_nodes"]


def test_discovery_handles_synonyms_and_natural_language_queries():
    reg = build_discovery_registry()
    matches = reg.search_tools("read my latest messages")
    names = {meta.name for meta in matches}
    assert "whatsapp__list_messages" in names


def test_discovery_exposes_match_trace_for_explainability():
    reg = build_discovery_registry()
    result = reg.discover(DiscoveryRequest(query="find contact", enabled_only=True, available_only=True))
    assert result.candidates
    assert any(meta.name == "whatsapp__search_contacts" for meta in result.candidates)
    assert "whatsapp__search_contacts" in result.matched_terms


if __name__ == "__main__":
    import sys
    import os
    # Ensure the project root is on the path
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    sys.path.append(PROJECT_ROOT)
    
    test_registry_registration_and_identity()
    test_registry_multiple_tools_and_retrieval()
    test_registry_state_filtering()
    test_snapshot_creation()
    test_search_foundation()
    print("All registry tests passed.")
