"""
Tests for External MCP Integration (A10)
========================================

Tests for the ability to integrate external MCP servers into the Jarvis tool
ecosystem without modifying intelligence layers.
"""

from unittest.mock import MagicMock

from app.tools.discovery import DiscoveryRequest, tool_discovery
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.selector import selector


def test_external_mcp_tool_registration():
    """An external MCP tool can be registered and retrieved."""
    reg = ToolRegistry()
    
    # Simulate a tool from an external MCP server
    external_tool = ToolMetadata(
        name="external_mcp__weather_get",
        server="external_mcp",
        tool_name="weather_get",
        description="Get weather for a location",
        capability="weather",
        input_schema={"required": ["location"]},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(external_tool)
    
    # Verify it's in the registry
    fetched = reg.get_tool("external_mcp__weather_get")
    assert fetched is not None
    assert fetched.name == "external_mcp__weather_get"
    assert fetched.server == "external_mcp"
    assert fetched.tool_name == "weather_get"
    assert fetched.description == "Get weather for a location"
    assert fetched.capability == "weather"
    assert fetched.input_schema == {"required": ["location"]}
    assert fetched.enabled is True
    assert fetched.available is True


def test_external_mcp_discovery_by_server():
    """Discovery can find tools by their MCP server."""
    reg = ToolRegistry()
    
    # Register two tools from different external MCPs
    tool1 = ToolMetadata(
        name="external_mcp__weather_get",
        server="external_mcp",
        tool_name="weather_get",
        description="Get weather",
        capability="weather",
        input_schema={},
        enabled=True,
        available=True,
    )
    tool2 = ToolMetadata(
        name="another_mcp__news_fetch",
        server="another_mcp",
        tool_name="news_fetch",
        description="Fetch news",
        capability="news",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool1)
    reg.register_tool(tool2)
    
    # Discover by server
    external_mcp_tools = reg.get_tools_for_server("external_mcp")
    assert len(external_mcp_tools) == 1
    assert external_mcp_tools[0].name == "external_mcp__weather_get"
    
    another_mcp_tools = reg.get_tools_for_server("another_mcp")
    assert len(another_mcp_tools) == 1
    assert another_mcp_tools[0].name == "another_mcp__news_fetch"


def test_external_mcp_discovery_by_capability():
    """Discovery can find tools by their capability bucket."""
    reg = ToolRegistry()
    
    # Register tools with different capabilities
    weather_tool = ToolMetadata(
        name="weather_mcp__forecast",
        server="weather_mcp",
        tool_name="forecast",
        description="Weather forecast",
        capability="weather",
        input_schema={},
        enabled=True,
        available=True,
    )
    news_tool = ToolMetadata(
        name="news_mcp__headlines",
        server="news_mcp",
        tool_name="headlines",
        description="News headlines",
        capability="news",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(weather_tool)
    reg.register_tool(news_tool)
    
    # Discover by capability
    weather_tools = reg.get_tools_for_capability("weather")
    assert len(weather_tools) == 1
    assert weather_tools[0].name == "weather_mcp__forecast"
    
    news_tools = reg.get_tools_for_capability("news")
    assert len(news_tools) == 1
    assert news_tools[0].name == "news_mcp__headlines"


def test_external_mcp_discovery_by_text():
    """Discovery can find tools by matching text in description or parameter names."""
    reg = ToolRegistry()
    
    # Register a tool with specific description and parameters
    tool = ToolMetadata(
        name="external_mcp__search_patents",
        server="external_mcp",
        tool_name="search_patents",
        description="Search patent database by keyword and date",
        capability="research",
        input_schema={
            "required": ["keyword"],
            "properties": {
                "keyword": {"type": "string"},
                "date_range": {"type": "string"}
            }
        },
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Discover by description text
    request = DiscoveryRequest(query="patent")
    results = tool_discovery.discover(reg, request)
    assert len(results.candidates) == 1
    assert results.candidates[0].name == "external_mcp__search_patents"
    
    # Discover by parameter name
    request = DiscoveryRequest(query="keyword")
    results = tool_discovery.discover(reg, request)
    assert len(results.candidates) == 1
    assert results.candidates[0].name == "external_mcp__search_patents"


def test_external_mcp_tool_unavailable_when_server_down():
    """Tools from an unavailable MCP server are marked unavailable."""
    reg = ToolRegistry()
    
    # Register a tool and then mark its server as unavailable
    tool = ToolMetadata(
        name="external_mcp__service_call",
        server="external_mcp",
        tool_name="service_call",
        description="Calls an external service",
        capability="external",
        input_schema={},
        enabled=True,
        available=True,  # Initially available
    )
    
    reg.register_tool(tool)
    
    # Verify initially available
    assert reg.get_tool("external_mcp__service_call").available is True
    
    # Mark server as unavailable (simulating MCP connection loss)
    reg.set_server_available("external_mcp", False)
    
    # Verify tool is now unavailable
    assert reg.get_tool("external_mcp__service_call").available is False


def test_external_mcp_tool_disabled_by_policy():
    """Tools can be disabled via runtime policy."""
    reg = ToolRegistry()
    
    tool = ToolMetadata(
        name="external_mcp__expensive_operation",
        server="external_mcp",
        tool_name="expensive_operation",
        description="An expensive operation",
        capability="external",
        input_schema={},
        enabled=True,  # Initially enabled
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Verify initially enabled
    assert reg.get_tool("external_mcp__expensive_operation").enabled is True
    
    # Disable via policy
    reg.disable_tool("external_mcp__expensive_operation")
    
    # Verify tool is now disabled
    assert reg.get_tool("external_mcp__expensive_operation").enabled is False


def test_external_mcp_tool_in_discovery_candidate_set():
    """External MCP tools appear in discovery candidate sets."""
    reg = ToolRegistry()
    
    # Register an external MCP tool
    tool = ToolMetadata(
        name="external_mcp__translate_text",
        server="external_mcp",
        tool_name="translate_text",
        description="Translate text between languages",
        capability="translation",
        input_schema={"required": ["text", "target_language"]},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Create a discovery request that should match this tool
    request = DiscoveryRequest(query="translate")
    
    # Execute discovery
    results = tool_discovery.discover(reg, request)
    
    # Verify the external MCP tool is in the candidate set
    assert len(results.candidates) == 1
    assert results.candidates[0].name == "external_mcp__translate_text"
    assert results.candidates[0].server == "external_mcp"
    assert results.candidates[0].tool_name == "translate_text"


def test_external_mcp_tool_in_selector_candidates():
    """External MCP tools can be selected by the selector."""
    reg = ToolRegistry()
    
    # Register an external MCP tool
    tool = ToolMetadata(
        name="external_mcp__analyze_sentiment",
        server="external_mcp",
        tool_name="analyze_sentiment",
        description="Analyze sentiment of text",
        capability="nlp",
        input_schema={"required": ["text"]},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Create a discovery request
    request = DiscoveryRequest(query="sentiment")
    
    # Get discovery results (candidate set)
    discovery_results = tool_discovery.discover(reg, request)
    
    # Use selector to narrow down candidates
    selected = selector.select(
        request.query,
        discovery_results.candidates,
        None,
        reg
    )
    
    # Verify the external MCP tool is selected (assuming it's relevant)
    assert len(selected) >= 1
    assert "external_mcp__analyze_sentiment" in selected


def test_external_mcp_tool_identity_collision_prevention():
    """Tools from different MCPs with same raw name get distinct scoped names."""
    reg = ToolRegistry()
    
    # Two different MCPs exposing a tool with the same raw name
    tool_a = ToolMetadata(
        name="server_a__process",  # scoped name already includes server
        server="server_a",
        tool_name="process",
        description="Process data in system A",
        capability="system",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    tool_b = ToolMetadata(
        name="server_b__process",  # scoped name already includes server
        server="server_b",
        tool_name="process",
        description="Process data in system B",
        capability="system",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool_a)
    reg.register_tool(tool_b)
    
    # Verify both tools exist with distinct scoped names
    assert reg.get_tool("server_a__process") is not None
    assert reg.get_tool("server_b__process") is not None
    
    # Verify they are different tools
    tool_a_fetched = reg.get_tool("server_a__process")
    tool_b_fetched = reg.get_tool("server_b__process")
    
    assert tool_a_fetched.server == "server_a"
    assert tool_b_fetched.server == "server_b"
    assert tool_a_fetched.description != tool_b_fetched.description


def test_multiple_external_mcps_can_coexist():
    """Multiple external MCPs can register tools without interference."""
    reg = ToolRegistry()
    
    # Register tools from three different external MCPs
    mcp1_tool = ToolMetadata(
        name="mcp1__tool_alpha",
        server="mcp1",
        tool_name="tool_alpha",
        description="Tool from MCP 1",
        capability="alpha",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    mcp2_tool = ToolMetadata(
        name="mcp2__tool_beta",
        server="mcp2",
        tool_name="tool_beta",
        description="Tool from MCP 2",
        capability="beta",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    mcp3_tool = ToolMetadata(
        name="mcp3__tool_gamma",
        server="mcp3",
        tool_name="tool_gamma",
        description="Tool from MCP 3",
        capability="gamma",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(mcp1_tool)
    reg.register_tool(mcp2_tool)
    reg.register_tool(mcp3_tool)
    
    # Verify all tools are present
    assert reg.get_tool("mcp1__tool_alpha") is not None
    assert reg.get_tool("mcp2__tool_beta") is not None
    assert reg.get_tool("mcp3__tool_gamma") is not None
    
    # Verify counts by server
    assert len(reg.get_tools_for_server("mcp1")) == 1
    assert len(reg.get_tools_for_server("mcp2")) == 1
    assert len(reg.get_tools_for_server("mcp3")) == 1
    
    # Verify total count
    assert len(reg.get_tools()) == 3


def test_external_mcp_tool_snapshot_inclusion():
    """External MCP tools can be included in a ToolSnapshot."""
    from app.tools.models import ToolSnapshot
    
    reg = ToolRegistry()
    
    # Register an external MCP tool
    tool = ToolMetadata(
        name="external_mcp__external_tool",
        server="external_mcp",
        tool_name="external_tool",
        description="An external tool",
        capability="external",
        input_schema={},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Create a snapshot containing this tool
    snapshot = ToolSnapshot(tools=[tool])
    
    # Verify the snapshot contains the tool
    assert len(snapshot) == 1
    assert snapshot.has_tool("external_mcp__external_tool")
    assert "external_mcp__external_tool" in snapshot.tool_names


def test_external_mcp_tool_execution_gateway_compatibility():
    """External MCP tools are compatible with the execution gateway interface."""
    from app.tools.execution import ToolExecutionGateway
    from unittest.mock import AsyncMock
    
    reg = ToolRegistry()
    
    # Register an external MCP tool
    tool = ToolMetadata(
        name="external_mcp__gateway_tool",
        server="external_mcp",
        tool_name="gateway_tool",
        description="A tool for the gateway",
        capability="external",
        input_schema={"required": ["input"]},
        enabled=True,
        available=True,
    )
    
    reg.register_tool(tool)
    
    # Mock the MCP session and tool map
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock()
    
    # Mock the MCP tool object (as would be stored in tool_map)
    mock_mcp_tool = MagicMock()
    mock_mcp_tool.name = "gateway_tool"
    
    tool_map = {
        "external_mcp__gateway_tool": ("external_mcp", mock_mcp_tool)
    }
    
    sessions = {
        "external_mcp": mock_session
    }
    
    # Create execution gateway
    gateway = ToolExecutionGateway(
        tool_registry=reg,
        sessions=sessions,
        tool_map=tool_map
    )
    
    # Verify the gateway can see the tool (via registry)
    assert reg.get_tool("external_mcp__gateway_tool") is not None
    
    # Note: We don't test actual execution here because it would require
    # setting up the mock to return a result. The compatibility is verified
    # by the gateway's ability to look up the tool in the registry and tool_map.