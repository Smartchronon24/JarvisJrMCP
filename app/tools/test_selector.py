"""
Simple test for the deterministic tool selector (hard‑task verification).
"""

import os
import sys

# Ensure the project root is on the path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(PROJECT_ROOT)

from app.tools.selector import selector, DeterministicToolSelector
from app.tools import tool_registry
from app.tools.models import ToolMetadata

def register_dummy_tools():
    # Clear any existing tools (for a clean test environment)
    # The registry does not provide a clear method; we'll remove by iterating.
    for name in list(tool_registry._tools.keys()):
        tool_registry.remove_tool(name)

    dummy_tools = [
        ToolMetadata(
            name="filesystem__read_file",
            server="filesystem",
            tool_name="read_file",
            capability="filesystem",
            description="Read a file",
            input_schema={},
        ),
        ToolMetadata(
            name="filesystem__write_file",
            server="filesystem",
            tool_name="write_file",
            capability="filesystem",
            description="Write a file",
            input_schema={},
        ),
        ToolMetadata(
            name="terminal__type",
            server="terminal",
            tool_name="type",
            capability="terminal",
            description="Type into terminal",
            input_schema={},
        ),
        ToolMetadata(
            name="memory__search_nodes",
            server="memory",
            tool_name="search_nodes",
            capability="memory",
            description="Search memory nodes",
            input_schema={},
        ),
        ToolMetadata(
            name="whatsapp__send_message",
            server="whatsapp",
            tool_name="send_message",
            capability="communication",
            description="Send a WhatsApp message",
            input_schema={},
        ),
    ]
    for meta in dummy_tools:
        tool_registry.register_tool(meta)


def main():
    register_dummy_tools()
    request = "Read a Python file and inspect its contents."
    candidates = tool_registry.get_tools()
    selected = selector.select(request, candidates=candidates)
    print("Selected tools for request:", request)
    for name in selected:
        print(" -", name)
    # Simple assertion: should include at least one filesystem tool
    assert any(name.startswith("filesystem__") for name in selected), "Filesystem tool not selected"
    print("Test passed.")


def test_navigation_prefers_navigate_over_click():
    tools = [
        ToolMetadata(
            name="playwright__browser_click",
            server="playwright",
            tool_name="browser_click",
            capability="browser",
            description="Click a target",
            input_schema={"properties": {"target": {}}},
        ),
        ToolMetadata(
            name="playwright__browser_navigate",
            server="playwright",
            tool_name="browser_navigate",
            capability="browser",
            description="Navigate to a URL",
            input_schema={"properties": {"url": {}}},
        ),
    ]
    assert DeterministicToolSelector().select(
        "Please open youtube for me", tools, max_tools=1
    ) == ["playwright__browser_navigate"]


def test_phone_requests_prefer_tools_with_phone_lookup_inputs():
    tools = [
        ToolMetadata(
            name="messaging__download_media",
            server="messaging",
            tool_name="download_media",
            capability="communication",
            description="Download media from a message",
            input_schema={"properties": {"message_id": {}, "chat_jid": {}}},
        ),
        ToolMetadata(
            name="messaging__get_contact",
            server="messaging",
            tool_name="get_contact",
            capability="communication",
            description="Look up a contact by phone number",
            input_schema={"properties": {"phone_number": {}}},
        ),
    ]
    assert DeterministicToolSelector().select(
        "Get the contact +917358247423", tools, max_tools=1
    ) == ["messaging__get_contact"]


if __name__ == "__main__":
    main()
