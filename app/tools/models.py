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


def _normalize_text(value: Any, *, default: str = "") -> str:
    """Return a trimmed string while preserving empty values as valid metadata."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


_SERVER_CAPABILITY_MAP: dict[str, str] = {
    "memory": "memory",
    "filesystem": "filesystem",
    "playwright": "browser",
    "exa": "web_research",
    "tavily": "web_research",
    "firecrawl": "web_research",
    "whatsapp": "communication",
    "terminal": "terminal",
}


def _guess_capability(server_name: str | None) -> str:
    if not server_name:
        return "general"
    return _SERVER_CAPABILITY_MAP.get(server_name, "general")


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

    def __post_init__(self) -> None:
        """Normalize the minimal metadata needed for consistent registry discovery."""
        self.name = _normalize_text(self.name)
        self.server = _normalize_text(self.server)
        self.tool_name = _normalize_text(self.tool_name)
        self.capability = _normalize_text(self.capability) or _guess_capability(self.server)
        self.description = _normalize_text(self.description)

        if not self.name:
            if self.server and self.tool_name:
                self.name = f"{self.server}__{self.tool_name}"
            elif self.tool_name:
                self.name = self.tool_name

        if not self.tool_name and self.name and "__" in self.name:
            _, self.tool_name = self.name.split("__", 1)

        if not self.server and self.name and "__" in self.name:
            self.server, _ = self.name.split("__", 1)

        if not isinstance(self.input_schema, dict):
            self.input_schema = {}

    @property
    def parameter_names(self) -> list[str]:
        """Return parameter names from the schema's properties, if available."""
        schema = self.input_schema or {}
        if not isinstance(schema, dict):
            return []
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return []
        return [str(name).strip() for name in properties.keys() if str(name).strip()]

    @property
    def search_terms(self) -> list[str]:
        """Return a lightweight, normalized searchable text blob."""
        parts = [
            self.name,
            self.tool_name,
            self.server,
            self.capability,
            self.description,
            " ".join(self.parameter_names),
        ]
        return [term for term in " ".join(part for part in parts if part).split() if term]

    @property
    def search_text(self) -> str:
        return " ".join(self.search_terms)

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

@dataclass(frozen=True)
class ToolSnapshot:
    """
    An immutable snapshot of tools selected for a specific execution.
    Contains only enabled, eligible tools selected for a task.
    
    The orchestrator creates a snapshot via the registry, and the worker
    is guaranteed to only receive tools present in this snapshot.
    """
    tools: list[ToolMetadata]

    @property
    def tool_names(self) -> set[str]:
        """Return a set of scoped tool names in this snapshot."""
        return {t.name for t in self.tools}

    def has_tool(self, name: str) -> bool:
        """Check if a tool is present in this snapshot."""
        return name in self.tool_names

    def __len__(self) -> int:
        return len(self.tools)

