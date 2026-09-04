"""C1/C2 stable MCP boundary and metadata normalization tests."""

from types import SimpleNamespace

import pytest

from app.tools.models import ToolMetadata, ToolMetadataError
from app.tools.registry import ToolRegistry


def test_mcp_definition_is_normalized_to_canonical_name_and_schema() -> None:
    metadata = ToolRegistry().register_mcp_tool(
        "  filesystem ",
        SimpleNamespace(
            name=" read_file ",
            description=" Read a file. ",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )

    assert metadata.name == "filesystem__read_file"
    assert metadata.server == "filesystem"
    assert metadata.tool_name == "read_file"
    assert metadata.description == "Read a file."
    assert metadata.capability == "filesystem"
    assert metadata.parameter_names == ["path"]


@pytest.mark.parametrize(
    "definition, message",
    [
        (SimpleNamespace(description="missing name"), "name"),
        (SimpleNamespace(name="tool", inputSchema=[]), "schema"),
        (SimpleNamespace(name="tool", inputSchema={"properties": []}), "properties"),
        (SimpleNamespace(name="tool", inputSchema={"required": "path"}), "required"),
    ],
)
def test_malformed_mcp_definitions_are_rejected(definition, message: str) -> None:
    with pytest.raises(ToolMetadataError, match=message):
        ToolRegistry().register_mcp_tool("filesystem", definition)


def test_direct_metadata_rejects_malformed_schema() -> None:
    with pytest.raises(ToolMetadataError, match="input_schema"):
        ToolMetadata(
            name="filesystem__read_file",
            server="filesystem",
            tool_name="read_file",
            capability="filesystem",
            description="Read a file",
            input_schema={"properties": []},
        )
