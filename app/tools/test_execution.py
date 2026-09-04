"""
Tests for Tool Execution Gateway (A8)
======================================

Tests for provider-neutral tool execution abstraction.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.execution import ExecutionResult, ToolExecutionGateway
from app.tools.models import ToolMetadata
from app.tools.registry import ToolRegistry


# --- Fixtures ---


@pytest.fixture
def registry():
    """Create a tool registry with test tools."""
    from app.tools.models import ToolMetadata
    reg = ToolRegistry()
    
    # Add a simple enabled tool
    reg.register_tool(
        ToolMetadata(
            name="test__search",
            server="test",
            tool_name="search",
            description="Search tool",
            enabled=True,
            available=True,
            input_schema={"required": ["query"]},
            capability="general",
        )
    )
    
    # Add a disabled tool
    reg.register_tool(
        ToolMetadata(
            name="test__disabled_tool",
            server="test",
            tool_name="disabled_tool",
            description="Disabled tool",
            enabled=False,
            available=True,
            input_schema={},
            capability="general",
        )
    )
    
    # Add an unavailable tool
    reg.register_tool(
        ToolMetadata(
            name="offline__lookup",
            server="offline",
            tool_name="lookup",
            description="Offline tool",
            enabled=True,
            available=False,
            input_schema={},
            capability="general",
        )
    )
    
    return reg


@pytest.fixture
def mock_sessions():
    """Create mock MCP sessions."""
    sessions = {}
    
    # Session for 'test' server
    test_session = MagicMock()
    test_session.call_tool = AsyncMock()
    sessions["test"] = test_session
    
    return sessions


@pytest.fixture
def tool_map():
    """Create a tool_map for test tools."""
    return {
        "test__search": ("test", MagicMock(tool_name="search")),
        "test__disabled_tool": ("test", MagicMock(tool_name="disabled_tool")),
        "offline__lookup": ("offline", MagicMock(tool_name="lookup")),
    }


@pytest.fixture
def gateway(registry, mock_sessions, tool_map):
    """Create an execution gateway for testing."""
    return ToolExecutionGateway(
        tool_registry=registry,
        sessions=mock_sessions,
        tool_map=tool_map,
    )


# --- Tests: Basic Success Cases ---


@pytest.mark.asyncio
async def test_execute_tool_success(gateway):
    """Test successful tool execution."""
    # Setup
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Search result")]
    
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    # Execute
    result = await gateway.execute("test__search", {"query": "test"})
    
    # Verify
    assert result.status == "success"
    assert result.is_error is False
    assert "Search result" in result.content
    assert result.metadata["duration_ms"] >= 0
    gateway.sessions["test"].call_tool.assert_called_once_with("search", {"query": "test"})


@pytest.mark.asyncio
async def test_execute_tool_with_empty_arguments(gateway):
    """Test execution with empty arguments when none are required."""
    # Modify registry to have a tool with no required args
    from app.tools.models import ToolMetadata
    gateway.tool_registry.register_tool(
        ToolMetadata(
            name="test__greet",
            server="test",
            tool_name="greet",
            description="Greet tool",
            enabled=True,
            available=True,
            input_schema={"required": []},
            capability="general",
        )
    )
    gateway.tool_map["test__greet"] = ("test", MagicMock(tool_name="greet"))
    
    # Setup
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Hello")]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    # Execute
    result = await gateway.execute("test__greet", {})
    
    # Verify
    assert result.status == "success"
    assert "Hello" in result.content


# --- Tests: Unknown Tool ---


@pytest.mark.asyncio
async def test_execute_unknown_tool(gateway):
    """Test execution of a tool that doesn't exist."""
    result = await gateway.execute("unknown__tool", {})
    
    assert result.status == "unknown_tool"
    assert result.is_error is True
    assert "Unknown tool" in result.content
    assert result.error_type == "unknown_tool"


# --- Tests: Disabled Tool ---


@pytest.mark.asyncio
async def test_execute_disabled_tool(gateway):
    """Test execution of a disabled tool."""
    result = await gateway.execute("test__disabled_tool", {})
    
    assert result.status == "unavailable_tool"
    assert result.is_error is True
    assert "disabled" in result.content.lower()
    assert result.error_type == "disabled"


# --- Tests: Unavailable Tool ---


@pytest.mark.asyncio
async def test_execute_unavailable_tool(gateway):
    """Test execution of a tool whose server is not connected."""
    result = await gateway.execute("offline__lookup", {})
    
    assert result.status == "unavailable_tool"
    assert result.is_error is True
    assert "unavailable" in result.content.lower()
    assert result.error_type == "unavailable"


# --- Tests: Argument Validation ---


@pytest.mark.asyncio
async def test_execute_missing_required_arguments(gateway):
    """Test that missing required arguments are caught."""
    result = await gateway.execute("test__search", {})  # missing 'query'
    
    assert result.status == "invalid_arguments"
    assert result.is_error is True
    assert "Missing required arguments" in result.content
    assert "query" in result.content


@pytest.mark.asyncio
async def test_execute_with_extra_arguments(gateway):
    """Test that extra arguments don't cause failures."""
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Result")]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test", "extra": "arg"})
    
    assert result.status == "success"
    # The gateway passes all arguments to MCP; MCP decides what to do with extras
    gateway.sessions["test"].call_tool.assert_called_once_with("search", {"query": "test", "extra": "arg"})


# --- Tests: Tool Error Handling ---


@pytest.mark.asyncio
async def test_execute_tool_returns_error(gateway):
    """Test handling of tool errors (is_error=True from MCP)."""
    result_mock = MagicMock()
    result_mock.is_error = True
    result_mock.content = "Tool-reported error"
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "error"
    assert result.is_error is True
    assert "Tool-reported error" in result.content
    assert result.error_type == "tool_error"


@pytest.mark.asyncio
async def test_execute_tool_mcp_exception(gateway):
    """Test handling of MCP execution exceptions."""
    gateway.sessions["test"].call_tool.side_effect = Exception("MCP connection lost")
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "runtime_error"
    assert result.is_error is True
    assert "MCP connection lost" in result.content
    assert result.error_type == "mcp_execution_error"


# --- Tests: Result Normalization ---


@pytest.mark.asyncio
async def test_execute_tool_empty_response(gateway):
    """Test handling of empty tool responses."""
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = []
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "success"
    assert "(no content returned)" in result.content


@pytest.mark.asyncio
async def test_execute_tool_multiple_content_items(gateway):
    """Test handling of multiple content items in result."""
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [
        MagicMock(text="Line 1"),
        MagicMock(text="Line 2"),
        MagicMock(text="Line 3"),
    ]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "success"
    assert "Line 1" in result.content
    assert "Line 2" in result.content
    assert "Line 3" in result.content


@pytest.mark.asyncio
async def test_execute_tool_content_without_text_attribute(gateway):
    """Test handling of content items without text attribute."""
    # Create a simple object that doesn't have text attribute
    class SimpleContent:
        def __str__(self):
            return "String representation"
    
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [SimpleContent()]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "success"
    assert "String representation" in result.content


# --- Tests: Server Not Connected ---


@pytest.mark.asyncio
async def test_execute_server_not_connected(registry, tool_map):
    """Test execution when server session is missing."""
    # Create gateway with empty sessions dict
    gateway = ToolExecutionGateway(
        tool_registry=registry,
        sessions={},  # No 'test' server
        tool_map=tool_map,
    )
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "runtime_error"
    assert result.is_error is True
    assert "not connected" in result.content.lower()


# --- Tests: Tool Not in Map ---


@pytest.mark.asyncio
async def test_execute_tool_not_in_map(registry, mock_sessions):
    """Test execution when tool is registered but not in tool_map."""
    gateway = ToolExecutionGateway(
        tool_registry=registry,
        sessions=mock_sessions,
        tool_map={},  # Empty map
    )
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "runtime_error"
    assert result.is_error is True
    assert "not found in execution map" in result.content


# --- Tests: Server Mismatch ---


@pytest.mark.asyncio
async def test_execute_server_mismatch(registry, mock_sessions):
    """Test execution when tool_map has wrong server name."""
    # tool_map says 'test' but registry says 'wrong_server'
    tool_map = {
        "test__search": ("wrong_server", MagicMock()),
    }
    
    gateway = ToolExecutionGateway(
        tool_registry=registry,
        sessions=mock_sessions,
        tool_map=tool_map,
    )
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "runtime_error"
    assert result.is_error is True
    assert "mismatch" in result.content.lower()


# --- Tests: Bookkeeping Callback ---


@pytest.mark.asyncio
async def test_execute_calls_bookkeeping_callback_on_success(gateway):
    """Test that bookkeeping callback is called on success."""
    callback = MagicMock()
    gateway.on_tool_executed = callback
    
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Result")]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "success"
    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == "test__search"  # scoped name
    assert args[1] == "search"  # real tool name
    assert args[2] >= 0  # duration_ms
    assert args[3] is True  # success
    assert args[4] is None  # error_info


@pytest.mark.asyncio
async def test_execute_calls_bookkeeping_callback_on_error(gateway):
    """Test that bookkeeping callback is called on error."""
    callback = MagicMock()
    gateway.on_tool_executed = callback
    
    gateway.sessions["test"].call_tool.side_effect = Exception("Test error")
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.is_error is True
    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == "test__search"
    assert args[1] == "search"
    assert args[2] >= 0  # duration_ms
    assert args[3] is False  # success
    assert "Test error" in args[4]  # error_info


@pytest.mark.asyncio
async def test_execute_no_callback_when_none_provided(gateway):
    """Test that execution works when no callback is provided."""
    # gateway.on_tool_executed is already None
    assert gateway.on_tool_executed is None
    
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Result")]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    # Should not raise
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "success"


# --- Tests: Boundary Enforcement ---


@pytest.mark.asyncio
async def test_selector_cannot_invoke_arbitrary_tools(gateway):
    """
    Test that the gateway validates tools against the registry.
    This ensures Python doesn't let arbitrary tools be invoked.
    """
    # Try to execute a tool that exists in tool_map but not in registry
    fake_tool_map = {
        "fake__tool": ("fake", MagicMock()),
    }
    gateway.tool_map = fake_tool_map
    
    # Should fail because registry doesn't have this tool
    result = await gateway.execute("fake__tool", {})
    
    assert result.status == "unknown_tool"
    assert result.is_error is True


# --- Tests: isError Alternative (provider compatibility) ---


@pytest.mark.asyncio
async def test_execute_handles_isError_attribute(gateway):
    """Test handling of isError (camelCase) used by some providers."""
    result_mock = MagicMock()
    # Don't set is_error, but set isError instead (some providers use this)
    del result_mock.is_error
    result_mock.isError = True
    result_mock.content = "Error message"
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    result = await gateway.execute("test__search", {"query": "test"})
    
    assert result.status == "error"
    assert result.is_error is True


@pytest.mark.asyncio
async def test_execute_treats_application_failure_envelope_as_error(gateway):
    """Tool-level success=false must not become a gateway success."""
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [
        MagicMock(text='{"success": false, "message": "recipient not found"}')
    ]
    gateway.sessions["test"].call_tool.return_value = result_mock

    result = await gateway.execute("test__search", {"query": "test"})

    assert result.status == "error"
    assert result.is_error is True
    assert result.error_type == "tool_error"
    assert "recipient not found" in result.content


# --- Integration-style test ---


@pytest.mark.asyncio
async def test_execute_full_happy_path(gateway):
    """
    Integration test: full execution flow for a success case.
    """
    # Simulate a complete tool execution flow
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [
        MagicMock(text="Found 3 results:"),
        MagicMock(text="1. Result A"),
        MagicMock(text="2. Result B"),
    ]
    gateway.sessions["test"].call_tool.return_value = result_mock
    
    # Execute
    result = await gateway.execute(
        "test__search",
        {"query": "Python tutorials"}
    )
    
    # Verify complete flow
    assert result.status == "success"
    assert result.is_error is False
    assert "Found 3 results" in result.content
    assert "Result A" in result.content
    assert result.metadata["duration_ms"] >= 0
    
    # Verify MCP was called correctly
    gateway.sessions["test"].call_tool.assert_called_once_with(
        "search",
        {"query": "Python tutorials"}
    )


@pytest.mark.asyncio
async def test_invalid_argument_payload_is_rejected(gateway):
    """Malformed payloads should fail cleanly before execution."""
    result = await gateway.execute("test__search", ["not", "a", "dict"])

    assert result.status == "invalid_arguments"
    assert result.is_error is True
    assert result.retryable is False
    assert "dictionary" in result.content.lower()


@pytest.mark.asyncio
async def test_unexpected_arguments_are_rejected(gateway):
    """Schema-defined arguments should reject unexpected payload keys."""
    gateway.tool_registry.get_tool("test__search").input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    result = await gateway.execute("test__search", {"query": "test", "unexpected": "value"})

    assert result.status == "invalid_arguments"
    assert result.is_error is True
    assert "Unexpected arguments" in result.content
    assert result.retryable is False


@pytest.mark.asyncio
async def test_runtime_failure_is_marked_retryable(gateway):
    """Temporary MCP/runtime issues should be flagged as potentially retryable."""
    gateway.sessions["test"].call_tool.side_effect = TimeoutError("connection timed out")

    result = await gateway.execute("test__search", {"query": "test"})

    assert result.status == "runtime_error"
    assert result.retryable is True
    assert "timed out" in result.content.lower()


@pytest.mark.asyncio
async def test_success_result_propagation_remains_intact(gateway):
    """Successful results should reach the worker without summarization or mutation."""
    expected = "Exact machine result\nLine 2"
    result_mock = MagicMock()
    result_mock.is_error = False
    result_mock.content = [MagicMock(text="Exact machine result"), MagicMock(text="Line 2")]
    gateway.sessions["test"].call_tool.return_value = result_mock

    result = await gateway.execute("test__search", {"query": "test"})

    assert result.status == "success"
    assert result.content == expected
    assert result.is_error is False
    assert result.retryable is False


@pytest.mark.asyncio
async def test_error_result_contains_normalized_message(gateway):
    """Tool-level errors should be normalized and surfaced with a message."""
    result_mock = MagicMock()
    result_mock.is_error = True
    result_mock.content = "mcp tool rejected request"
    gateway.sessions["test"].call_tool.return_value = result_mock

    result = await gateway.execute("test__search", {"query": "test"})

    assert result.status == "error"
    assert result.is_error is True
    assert result.error_type == "tool_error"
    assert "mcp tool rejected request" in result.content
    assert result.retryable is False
    assert result.message == result.content
