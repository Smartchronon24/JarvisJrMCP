"""
Tool Registry — Data Models
============================
Defines the structured representation for a registered tool.

Each ToolMetadata instance is the canonical record of a single MCP tool
inside the Tool Registry. It carries everything needed to:
  - identify the tool (name, server, capability)
  - understand it (description, input_schema)
  - control its availability (enabled, available)

The registry is NOT responsible for executing tools.
Tool execution remains the responsibility of the MCP client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolMetadata:
    """
    Canonical in-registry representation of a single MCP tool.

    Fields
    ------
    name : str
        The scoped tool name used throughout Jarvis, e.g. ``memory__search_nodes``.
        This is always ``<server>__<original_tool_name>``.

    server : str
        The MCP server that owns this tool, e.g. ``"memory"``, ``"whatsapp"``.

    tool_name : str
        The original (unscoped) tool name as reported by the MCP server,
        e.g. ``"search_nodes"``.  Used when actually calling the tool via MCP.

    capability : str
        High-level capability bucket this tool belongs to, e.g.
        ``"memory"``, ``"filesystem"``, ``"browser"``, ``"communication"``,
        ``"web_research"``, ``"terminal"``.

    description : str
        Human-readable description sourced directly from the MCP server.

    input_schema : dict
        The raw ``inputSchema`` / ``input_schema`` dict from the MCP tool
        definition.  Preserved verbatim so that future model adapters can
        convert it to Gemini / OpenAI / Anthropic format as needed.

    enabled : bool
        Runtime flag.  Disabled tools are known to the registry but excluded
        from ``list_tools(enabled_only=True)`` results.  Defaults to ``True``.

    available : bool
        Whether the tool's server is currently connected and reachable.
        Set to ``False`` if the server failed to start.  Defaults to ``True``.
    """

    name: str                        # scoped key  e.g. "memory__search_nodes"
    server: str                      # server name e.g. "memory"
    tool_name: str                   # raw MCP name e.g. "search_nodes"
    capability: str                  # capability bucket e.g. "memory"
    description: str                 # from MCP server
    input_schema: dict[str, Any]     # raw MCP inputSchema — preserved verbatim
    enabled: bool = True
    available: bool = True

    # ------------------------------------------------------------------ #
    #  Convenience                                                         #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        status = []
        if not self.enabled:
            status.append("disabled")
        if not self.available:
            status.append("unavailable")
        status_str = f" [{', '.join(status)}]" if status else ""
        return (
            f"ToolMetadata("
            f"name={self.name!r}, "
            f"server={self.server!r}, "
            f"capability={self.capability!r}"
            f"{status_str})"
        )
