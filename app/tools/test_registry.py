"""
Tests for Tool Registry A1 Foundation.
"""
from app.tools.registry import ToolRegistry
from app.tools.models import ToolMetadata, ToolSnapshot

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
